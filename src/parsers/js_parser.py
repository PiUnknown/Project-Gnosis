"""
JavaScript and TypeScript AST extraction using tree-sitter.

Handles:
  function_declaration        function foo(a, b) {}
  arrow function (variable)   const foo = (a) => {}
  class_declaration           class Foo extends Bar {}
  method_definition           inside class body
  export_statement            export function foo() {}
  import_statement            import X from './utils'

Does NOT handle in v1 (documented limitations):
  CommonJS require()          const x = require('y')
  Dynamic imports             import('./module').then(...)
  Namespace re-exports        export * from './module'

WHY NOT CommonJS:
  require() is a function call at runtime, not a static import.
  tree-sitter sees it as a call_expression, not an import node.
  Detecting it would require pattern matching on call expressions.
  Deferred to v2: most modern JS/TS uses ES6 imports.

NOTE ON class_heritage:
  In tree-sitter-javascript, `extends Bar` is represented as a child
  node of TYPE 'class_heritage' — it is NOT assigned to a named field.
  child_by_field_name('heritage') always returns None. We instead
  iterate node.children and match on child.type == 'class_heritage'.
"""
from typing import Optional, Tuple
from src.parsers.base import FunctionInfo, ClassInfo, ImportInfo


# -----------------------------------------------------------------------
# Parameter extraction
# -----------------------------------------------------------------------

def _extract_js_params(params_node) -> list:
    """
    Extract parameter names from a JS formal_parameters node.

    Handles: plain identifiers, destructured params (skipped, logged as _),
    rest parameters (...args), TypeScript typed parameters.
    """
    if not params_node:
        return []

    # Single parameter without parens: x => x + 1
    # tree-sitter puts this as an identifier, not formal_parameters
    if params_node.type == 'identifier':
        return [params_node.text.decode('utf-8')]

    result = []
    for child in params_node.named_children:
        t = child.type

        if t == 'identifier':
            result.append(child.text.decode('utf-8'))

        elif t in ('required_parameter', 'optional_parameter'):
            # TypeScript: foo(x: string) or foo(x?: string)
            pattern = child.child_by_field_name('pattern')
            if pattern and pattern.type == 'identifier':
                result.append(pattern.text.decode('utf-8'))

        elif t == 'rest_parameter':
            # ...args
            inner = child.child_by_field_name('pattern')
            if not inner and child.named_children:
                inner = child.named_children[0]
            if inner:
                result.append('...' + inner.text.decode('utf-8'))
            else:
                result.append('...rest')

        elif t in ('object_pattern', 'array_pattern'):
            # Destructured: ({ a, b }) or ([x, y])
            # Too complex to expand cleanly, use placeholder
            result.append('{...}' if t == 'object_pattern' else '[...]')

    return result


# -----------------------------------------------------------------------
# Function extraction
# -----------------------------------------------------------------------

def _extract_js_function(node, is_method: bool = False) -> Optional[FunctionInfo]:
    """
    Extract from function_declaration or method_definition.

    ASYNC DETECTION FOR JS:
    Unlike Python where async creates a different node type
    (async_function_definition), JavaScript uses the same
    function_declaration node type with an 'async' keyword child.
    We scan children for a node with type 'async'.
    """
    name_node = node.child_by_field_name('name')
    if not name_node:
        return None

    is_async = any(child.type == 'async' for child in node.children)

    params_node = node.child_by_field_name('parameters')
    params = _extract_js_params(params_node)

    return FunctionInfo(
        name=name_node.text.decode('utf-8'),
        params=params,
        line_start=node.start_point[0] + 1,
        line_end=node.end_point[0] + 1,
        docstring=None,   # JS has no standardized docstring syntax
        is_async=is_async,
        is_method=is_method
    )


def _extract_arrow_function(declarator_node) -> Optional[FunctionInfo]:
    """
    Extract from a variable_declarator whose value is an arrow_function.

    Pattern:
      const fetchUser = async (id) => { ... }

    AST:
      variable_declarator
        name: identifier "fetchUser"
        value: arrow_function
          async
          parameters: formal_parameters
          body: statement_block
    """
    name_node = declarator_node.child_by_field_name('name')
    if not name_node or name_node.type != 'identifier':
        return None

    value_node = declarator_node.child_by_field_name('value')
    if not value_node or value_node.type != 'arrow_function':
        return None

    is_async = any(child.type == 'async' for child in value_node.children)

    # Arrow functions can have formal_parameters or a bare identifier
    params_node = (
        value_node.child_by_field_name('parameters')
        or value_node.child_by_field_name('parameter')
    )
    params = _extract_js_params(params_node)

    return FunctionInfo(
        name=name_node.text.decode('utf-8'),
        params=params,
        line_start=declarator_node.start_point[0] + 1,
        line_end=declarator_node.end_point[0] + 1,
        docstring=None,
        is_async=is_async,
        is_method=False
    )


# -----------------------------------------------------------------------
# Class extraction
# -----------------------------------------------------------------------

def _extract_js_class(node) -> Tuple[Optional[ClassInfo], list]:
    """
    Extract a ClassInfo and its methods from a class_declaration node.

    WHY node.children INSTEAD OF child_by_field_name('heritage'):
    In tree-sitter-javascript, the extends clause is represented as a
    child node of TYPE 'class_heritage'. It is NOT assigned to a named
    field in the grammar, so child_by_field_name('heritage') always
    returns None. We iterate node.children (which includes anonymous
    and unnamed nodes) and match on child.type == 'class_heritage'.
    """
    name_node = node.child_by_field_name('name')
    if not name_node:
        return None, []

    # FIX: class_heritage is a child node TYPE, not a named field.
    # Iterate all children and find the class_heritage node.
    bases = []
    for child in node.children:
        if child.type == 'class_heritage':
            # class_heritage contains the 'extends' keyword (anonymous)
            # followed by the base class identifier or member expression.
            for subchild in child.named_children:
                if subchild.type in ('identifier', 'member_expression'):
                    bases.append(subchild.text.decode('utf-8'))
            break  # JS only allows a single extends clause

    # Methods inside the class body
    method_names = []
    methods = []
    body = node.child_by_field_name('body')
    if body:
        for child in body.named_children:
            if child.type == 'method_definition':
                method = _extract_js_function(child, is_method=True)
                if method:
                    method_names.append(method.name)
                    methods.append(method)

    class_info = ClassInfo(
        name=name_node.text.decode('utf-8'),
        bases=bases,
        method_names=method_names,
        line_start=node.start_point[0] + 1,
        line_end=node.end_point[0] + 1,
        docstring=None
    )
    return class_info, methods


# -----------------------------------------------------------------------
# Import extraction
# -----------------------------------------------------------------------

def _extract_js_import(node) -> Optional[ImportInfo]:
    """
    Extract from an ES6 import_statement.

    Patterns:
      import React from 'react'
      import { useState, useEffect } from 'react'
      import * as R from 'ramda'
      import defaultExport, { named } from './module'
    """
    module = ''
    names = []

    for child in node.children:
        # The module path is a string node directly inside import_statement
        if child.type == 'string':
            raw = child.text.decode('utf-8')
            module = raw.strip("'\"")

        elif child.type == 'import_clause':
            for subchild in child.named_children:

                if subchild.type == 'identifier':
                    # Default import: import React from '...'
                    names.append(subchild.text.decode('utf-8'))

                elif subchild.type == 'named_imports':
                    # Named imports: { useState, useEffect }
                    for specifier in subchild.named_children:
                        if specifier.type == 'import_specifier':
                            name_node = specifier.child_by_field_name('name')
                            if name_node:
                                names.append(name_node.text.decode('utf-8'))

                elif subchild.type == 'namespace_import':
                    # import * as X from '...'
                    for ns in subchild.named_children:
                        if ns.type == 'identifier':
                            names.append('* as ' + ns.text.decode('utf-8'))

    if not module:
        return None

    return ImportInfo(
        module=module,
        names=names,
        is_from_import=True,
        is_internal=False
    )


# -----------------------------------------------------------------------
# Helpers for export unwrapping
# -----------------------------------------------------------------------

def _process_declaration(node, functions, classes):
    """
    Process a function or class node and append results to output lists.
    Used for both top-level declarations and export-wrapped declarations.
    """
    ntype = node.type

    if ntype == 'function_declaration':
        fn = _extract_js_function(node)
        if fn:
            functions.append(fn)

    elif ntype == 'class_declaration':
        cls, methods = _extract_js_class(node)
        if cls:
            classes.append(cls)
            functions.extend(methods)

    elif ntype in ('lexical_declaration', 'variable_declaration'):
        for child in node.named_children:
            if child.type == 'variable_declarator':
                fn = _extract_arrow_function(child)
                if fn:
                    functions.append(fn)


# -----------------------------------------------------------------------
# Top-level entry point
# -----------------------------------------------------------------------

def extract_symbols(
    tree,
    source_bytes: bytes,
    language: str = 'JavaScript'
) -> Tuple[Optional[str], list, list, list]:
    """
    Walk the root program node and extract all symbols.

    Returns: (module_docstring, functions, classes, imports)

    module_docstring is always None for JS/TS — there is no
    standardized module-level docstring convention.
    """
    root = tree.root_node
    functions = []
    classes = []
    imports = []

    for node in root.named_children:
        ntype = node.type

        if ntype in ('function_declaration', 'class_declaration',
                     'lexical_declaration', 'variable_declaration'):
            _process_declaration(node, functions, classes)

        elif ntype == 'export_statement':
            # Unwrap: export function foo() {} or export default class Foo {}
            # or export const foo = () => {}
            for child in node.named_children:
                if child.type in ('function_declaration', 'class_declaration',
                                  'lexical_declaration', 'variable_declaration'):
                    _process_declaration(child, functions, classes)
                # export default function() {} — anonymous function
                elif child.type == 'function':
                    # Check if it has a name
                    name_node = child.child_by_field_name('name')
                    if name_node:
                        fn = _extract_js_function(child)
                        if fn:
                            functions.append(fn)

        elif ntype == 'import_statement':
            imp = _extract_js_import(node)
            if imp:
                imports.append(imp)

    return None, functions, classes, imports