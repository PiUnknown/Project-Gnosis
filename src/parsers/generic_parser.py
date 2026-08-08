"""
src/parsers/generic_parser.py

Generic AST symbol extraction using tree-sitter for Go, Rust, Java, C, and C++.

Its only contract: given a tree-sitter tree, source bytes, and the language string,
return extracted symbols in the form of a tuple: (None, functions, classes, imports).

WHY A GENERIC PARSER:
Rather than writing five separate files for Go, Rust, Java, C, and C++, we consolidate
them into a single generic parser. This simplifies imports, keeps the parser interface
clean, and makes it easier to share helper functions (like the C/C++ declarator unwrapper).
"""
from typing import Optional, Tuple
from pathlib import PurePosixPath

from src.parsers.base import FunctionInfo, ClassInfo, ImportInfo


# -----------------------------------------------------------------------
# Parameter Extraction Helpers
# -----------------------------------------------------------------------

def _extract_go_params(params_node) -> list:
    """
    Extract parameter names from a Go parameters node.
    Handles: (a, b int, c string), variadic (args ...int), anonymous (int).
    """
    if not params_node:
        return []
    names = []
    for child in params_node.named_children:
        if child.type == 'parameter_declaration':
            # E.g. a, b int
            for param_child in child.named_children:
                if param_child.type == 'identifier':
                    names.append(param_child.text.decode('utf-8'))
        elif child.type == 'variadic_parameter_declaration':
            # E.g. args ...int
            id_node = child.child_by_field_name('name')
            if id_node:
                names.append(id_node.text.decode('utf-8'))
    return names


def _extract_rust_params(params_node) -> list:
    """
    Extract parameter names from a Rust parameters node.
    Handles: typed patterns (x: i32), self/receiver (&self, self), patterns.
    """
    if not params_node:
        return []
    names = []
    for child in params_node.named_children:
        if child.type == 'parameter':
            pat = child.child_by_field_name('pattern')
            if pat:
                names.append(pat.text.decode('utf-8'))
        elif child.type == 'self_parameter':
            names.append('self')
    return names


def _extract_java_params(params_node) -> list:
    """
    Extract parameter names from a Java formal_parameters node.
    Handles: typed parameters (int x), spread parameters (String... args).
    """
    if not params_node:
        return []
    names = []
    for child in params_node.named_children:
        if child.type == 'formal_parameter':
            name_node = child.child_by_field_name('name')
            if not name_node:
                for sub in child.named_children:
                    if sub.type == 'identifier':
                        name_node = sub
            if name_node:
                names.append(name_node.text.decode('utf-8'))
        elif child.type == 'spread_parameter':
            name_node = child.child_by_field_name('name')
            if name_node:
                names.append(name_node.text.decode('utf-8'))
    return names


# -----------------------------------------------------------------------
# C/C++ Declarator & Name Resolution Helpers
# -----------------------------------------------------------------------

def _unwrap_c_declarator(node) -> Optional[object]:
    """
    Unwrap the nested C/C++ declarator chain down to the identifier.
    function_definition.declarator may be: pointer_declarator -> function_declarator -> identifier,
    reference_declarator, parenthesized_declarator, etc.
    """
    if not node:
        return None
    if node.type in ('identifier', 'qualified_identifier', 'field_identifier'):
        return node

    decl = node.child_by_field_name('declarator')
    if decl:
        return _unwrap_c_declarator(decl)

    # Fallback to search named children for nested declarators
    for child in node.children:
        if child.type in ('identifier', 'qualified_identifier', 'field_identifier', 'pointer_declarator',
                          'function_declarator', 'reference_declarator', 'parenthesized_declarator'):
            res = _unwrap_c_declarator(child)
            if res:
                return res
    return None


def _find_c_parameters_node(node) -> Optional[object]:
    """
    Recursively walk the C/C++ declarator chain to find the parameter_list node.
    """
    if not node:
        return None
    if node.type == 'parameter_list':
        return node

    decl = node.child_by_field_name('declarator')
    if decl:
        res = _find_c_parameters_node(decl)
        if res:
            return res

    for child in node.children:
        if child.type in ('pointer_declarator', 'function_declarator', 'reference_declarator',
                          'parenthesized_declarator', 'parameter_list'):
            res = _find_c_parameters_node(child)
            if res:
                return res
    return None


def _extract_c_params(node) -> list:
    """
    Find parameter_list in the C/C++ function declarator and extract parameter names.
    """
    plist = _find_c_parameters_node(node)
    if not plist:
        return []
    names = []
    for child in plist.named_children:
        if child.type == 'parameter_declaration':
            decl = child.child_by_field_name('declarator')
            if decl:
                name_node = _unwrap_c_declarator(decl)
                if name_node:
                    names.append(name_node.text.decode('utf-8'))
    return names


# -----------------------------------------------------------------------
# Text-based Import Parsing Helpers
# -----------------------------------------------------------------------

def _parse_rust_use(text: str) -> Tuple[str, list]:
    """
    Parse a Rust use_declaration to extract module and imported names.
    E.g. use crate::utils::Foo; -> ("crate::utils", ["Foo"])
         use std::collections::{HashMap, HashSet}; -> ("std::collections", ["HashMap", "HashSet"])
    """
    text = text.strip()
    if text.startswith('use '):
        text = text[4:]
    text = text.rstrip(';')
    if '::{' in text:
        prefix, suffix = text.split('::{', 1)
        suffix = suffix.rstrip('}')
        names = [n.strip() for n in suffix.split(',') if n.strip()]
        return prefix.strip(), names
    elif '::' in text:
        parts = text.split('::')
        prefix = '::'.join(parts[:-1])
        names = [parts[-1]]
        return prefix.strip(), names
    else:
        return "", [text.strip()]


def _parse_java_import(text: str) -> Tuple[str, list]:
    """
    Parse a Java import_declaration to extract module package and imported names.
    E.g. import java.util.HashMap; -> ("java.util", ["HashMap"])
    """
    text = text.strip()
    if text.startswith('import '):
        text = text[7:]
    text = text.rstrip(';')
    if '.' in text:
        parts = text.split('.')
        module = '.'.join(parts[:-1])
        name = parts[-1]
        return module.strip(), [name.strip()]
    else:
        return "", [text.strip()]


# -----------------------------------------------------------------------
# Symbol Extraction Dispatch Entry Point
# -----------------------------------------------------------------------

def extract_symbols(tree, source_bytes: bytes, language: str) -> Tuple[None, list, list, list]:
    """
    Walk tree-sitter AST and extract FunctionInfo, ClassInfo, and ImportInfo nodes.
    """
    functions = []
    classes = []
    imports = []

    # Map to track Rust impl blocks: type_name -> list of method names
    rust_impl_methods: dict = {}

    if language == 'Rust':
        # Pre-scan Rust impl blocks to associate methods with structs/traits/enums later
        def pre_scan(node):
            if node.type == 'impl_item':
                type_node = node.child_by_field_name('type')
                if type_node:
                    type_name = type_node.text.decode('utf-8')
                    method_names = []
                    body = node.child_by_field_name('body')
                    if body:
                        for child in body.named_children:
                            if child.type == 'function_item':
                                name_node = child.child_by_field_name('name')
                                if name_node:
                                    method_names.append(name_node.text.decode('utf-8'))
                    rust_impl_methods[type_name] = rust_impl_methods.get(type_name, []) + method_names
            for child in node.children:
                pre_scan(child)
        pre_scan(tree.root_node)

    def walk(node, in_class_body: bool = False, current_class_methods: Optional[list] = None):
        nonlocal functions, classes, imports

        ntype = node.type

        # 1. Imports
        if language == 'Go' and ntype == 'import_spec':
            path_node = node.child_by_field_name('path')
            if path_node:
                val = path_node.text.decode('utf-8').strip('"')
                imports.append(ImportInfo(
                    module=val,
                    names=[],
                    is_from_import=False,
                    is_internal=False
                ))

        elif language == 'Rust' and ntype == 'use_declaration':
            val = node.text.decode('utf-8')
            module, names = _parse_rust_use(val)
            imports.append(ImportInfo(
                module=module,
                names=names,
                is_from_import=True,
                is_internal=False
            ))

        elif language == 'Java' and ntype == 'import_declaration':
            val = node.text.decode('utf-8')
            module, names = _parse_java_import(val)
            imports.append(ImportInfo(
                module=module,
                names=names,
                is_from_import=True,
                is_internal=False
            ))

        elif language in ('C', 'C++', 'C/C++ Header', 'C++ Header') and ntype == 'preproc_include':
            path_node = node.child_by_field_name('path')
            if path_node:
                val = path_node.text.decode('utf-8')
                imports.append(ImportInfo(
                    module=val,
                    names=[],
                    is_from_import=False,
                    is_internal=False
                ))

        # 2. Classes
        is_class_node = False

        if language == 'Go' and ntype == 'type_declaration':
            for spec in node.named_children:
                if spec.type == 'type_spec':
                    name_node = spec.child_by_field_name('name')
                    type_node = spec.child_by_field_name('type')
                    if name_node and type_node and type_node.type in ('struct_type', 'interface_type'):
                        class_name = name_node.text.decode('utf-8')
                        classes.append(ClassInfo(
                            name=class_name,
                            bases=[],
                            method_names=[],
                            line_start=node.start_point[0] + 1,
                            line_end=node.end_point[0] + 1,
                            docstring=None
                        ))

        elif language == 'Rust' and ntype in ('struct_item', 'enum_item', 'trait_item'):
            name_node = node.child_by_field_name('name')
            if name_node:
                class_name = name_node.text.decode('utf-8')
                method_names = []
                if ntype == 'trait_item':
                    for child in node.children:
                        if child.type == 'declaration_list':
                            for sub in child.named_children:
                                if sub.type in ('function_item', 'function_signature_item'):
                                    sub_name = sub.child_by_field_name('name')
                                    if sub_name:
                                        method_names.append(sub_name.text.decode('utf-8'))
                else:
                    method_names = rust_impl_methods.get(class_name, [])

                classes.append(ClassInfo(
                    name=class_name,
                    bases=[],
                    method_names=method_names,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    docstring=None
                ))

        elif language == 'Java' and ntype in ('class_declaration', 'interface_declaration', 'enum_declaration'):
            name_node = node.child_by_field_name('name')
            if name_node:
                class_name = name_node.text.decode('utf-8')
                bases = []
                super_node = node.child_by_field_name('superclass')
                if super_node:
                    val_text = super_node.text.decode('utf-8').strip()
                    if val_text.startswith('extends '):
                        val_text = val_text[8:].strip()
                    bases.append(val_text)
                interfaces_node = node.child_by_field_name('interfaces')
                if interfaces_node:
                    for interface in interfaces_node.named_children:
                        bases.append(interface.text.decode('utf-8'))

                method_names = []
                body = node.child_by_field_name('body')
                if body:
                    for child in body.named_children:
                        if child.type in ('method_declaration', 'constructor_declaration'):
                            sub_name = child.child_by_field_name('name')
                            if sub_name:
                                method_names.append(sub_name.text.decode('utf-8'))

                classes.append(ClassInfo(
                    name=class_name,
                    bases=bases,
                    method_names=method_names,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    docstring=None
                ))
                is_class_node = True
                current_class_methods = method_names

        elif language in ('C++', 'C++ Header') and ntype == 'class_specifier':
            name_node = node.child_by_field_name('name')
            if name_node:
                class_name = name_node.text.decode('utf-8')
                bases = []
                for child in node.children:
                    if child.type == 'base_class_clause':
                        for sub in child.named_children:
                            bases.append(sub.text.decode('utf-8'))

                method_names = []
                body = None
                for child in node.children:
                    if child.type == 'field_declaration_list':
                        body = child
                        break
                if body:
                    for child in body.named_children:
                        if child.type == 'function_definition':
                            name_sub = _unwrap_c_declarator(child.child_by_field_name('declarator'))
                            if name_sub:
                                method_names.append(name_sub.text.decode('utf-8'))
                        elif child.type == 'field_declaration':
                            decl = child.child_by_field_name('declarator')
                            if decl:
                                name_sub = _unwrap_c_declarator(decl)
                                if name_sub:
                                    method_names.append(name_sub.text.decode('utf-8'))

                classes.append(ClassInfo(
                    name=class_name,
                    bases=bases,
                    method_names=method_names,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    docstring=None
                ))
                is_class_node = True
                current_class_methods = method_names

        # 3. Functions
        if language == 'Go' and ntype in ('function_declaration', 'method_declaration'):
            name_node = node.child_by_field_name('name')
            if name_node:
                func_name = name_node.text.decode('utf-8')
                params = _extract_go_params(node.child_by_field_name('parameters'))
                functions.append(FunctionInfo(
                    name=func_name,
                    params=params,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    docstring=None,
                    is_async=False,
                    is_method=False
                ))

        elif language == 'Rust' and ntype == 'function_item':
            name_node = node.child_by_field_name('name')
            if name_node:
                func_name = name_node.text.decode('utf-8')
                params = _extract_rust_params(node.child_by_field_name('parameters'))
                functions.append(FunctionInfo(
                    name=func_name,
                    params=params,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    docstring=None,
                    is_async=False,
                    is_method=in_class_body
                ))

        elif language == 'Java' and ntype in ('method_declaration', 'constructor_declaration'):
            name_node = node.child_by_field_name('name')
            if name_node:
                func_name = name_node.text.decode('utf-8')
                params = _extract_java_params(node.child_by_field_name('parameters'))
                functions.append(FunctionInfo(
                    name=func_name,
                    params=params,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    docstring=None,
                    is_async=False,
                    is_method=in_class_body
                ))

        elif language in ('C', 'C++', 'C/C++ Header', 'C++ Header') and ntype == 'function_definition':
            decl = node.child_by_field_name('declarator')
            name_node = _unwrap_c_declarator(decl)
            if name_node:
                func_name = name_node.text.decode('utf-8')
                params = _extract_c_params(node)
                functions.append(FunctionInfo(
                    name=func_name,
                    params=params,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    docstring=None,
                    is_async=False,
                    is_method=in_class_body
                ))

        # Recursion
        next_in_class_body = in_class_body
        if is_class_node:
            next_in_class_body = True
        elif language == 'Rust' and ntype in ('impl_item', 'trait_item'):
            next_in_class_body = True

        for child in node.children:
            walk(child, next_in_class_body, current_class_methods)

    walk(tree.root_node)
    return None, functions, classes, imports
