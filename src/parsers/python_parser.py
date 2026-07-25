"""
Python-specific AST extraction using tree-sitter.

This module knows Python AST node types. It does not know about
state, file manifests, or other agents. Its only contract:
given a tree-sitter tree and source bytes, return extracted symbols.

Key Python AST node types used:
  function_definition       - def foo():
  async_function_definition - async def foo():
  class_definition          - class Foo:
  import_statement          - import os
  import_from_statement     - from pathlib import Path
  decorated_definition      - @decorator\ndef foo():
  parameters                - the (a, b, c) part of a function
  block                     - indented body of function/class
"""
import ast as stdlib_ast
from typing import Optional, Tuple
from src.parsers.base import FunctionInfo, ClassInfo, ImportInfo


# -----------------------------------------------------------------------
# Docstring utilities
# -----------------------------------------------------------------------

def clean_docstring(raw: str) -> Optional[str]:
    """
    Strip Python string delimiters from a raw docstring node text.

    WHY stdlib_ast.literal_eval:
    Python docstrings come in many forms: triple double-quoted,
    triple single-quoted, raw strings (r\"\"\"...\"\"\"), byte strings.
    ast.literal_eval handles all of them correctly. It evaluates
    the string literal and returns the Python string value.
    Manual stripping would need to handle every edge case.
    """
    if not raw:
        return None
    raw = raw.strip()
    try:
        result = stdlib_ast.literal_eval(raw)
        if isinstance(result, str):
            return result.strip() or None
        return None
    except Exception:
        # Fallback: manual stripping for edge cases literal_eval rejects
        for quote in ('"""', "'''", '"', "'"):
            if (raw.startswith(quote)
                    and raw.endswith(quote)
                    and len(raw) >= 2 * len(quote)):
                return raw[len(quote):-len(quote)].strip() or None
        return raw.strip() or None


def _get_block_docstring(block_node) -> Optional[str]:
    """
    Return the docstring from the first statement in a block node,
    or None if the first statement is not a string literal.

    A block's named_children are the actual statements (no whitespace nodes).
    The first statement is a docstring if it is an expression_statement
    containing a single string node.
    """
    if not block_node:
        return None

    for child in block_node.named_children:
        if child.type == 'expression_statement':
            for subchild in child.children:
                if subchild.type == 'string':
                    return clean_docstring(subchild.text.decode('utf-8'))
            # First named child was an expression_statement but no string
            return None
        # First named child is not an expression_statement
        return None

    return None


# -----------------------------------------------------------------------
# Parameter extraction
# -----------------------------------------------------------------------

def _extract_params(params_node) -> list:
    """
    Extract parameter names from a Python parameters node.

    Handles: plain identifiers, typed parameters (x: int),
    default parameters (x=1), typed+default (x: int = 1),
    *args, **kwargs.

    Returns only names, not types or defaults.
    Type information is discarded because it is not needed
    for the symbol table and complicates the extraction significantly.
    """
    if not params_node:
        return []

    result = []
    for child in params_node.named_children:
        t = child.type

        if t == 'identifier':
            result.append(child.text.decode('utf-8'))

        elif t in ('typed_parameter', 'default_parameter', 'typed_default_parameter'):
            name_node = child.child_by_field_name('name')
            if not name_node and child.named_children:
                name_node = child.named_children[0]
            if name_node and name_node.type == 'identifier':
                result.append(name_node.text.decode('utf-8'))

        elif t in ('list_splat_pattern', 'list_splat'):
            # *args
            inner = child.named_children[0] if child.named_children else None
            if inner:
                result.append('*' + inner.text.decode('utf-8'))
            else:
                result.append('*args')

        elif t in ('dictionary_splat_pattern', 'dictionary_splat'):
            # **kwargs
            inner = child.named_children[0] if child.named_children else None
            if inner:
                result.append('**' + inner.text.decode('utf-8'))
            else:
                result.append('**kwargs')

    return result


# -----------------------------------------------------------------------
# Function extraction
# -----------------------------------------------------------------------

def extract_function(node, is_async: bool = False, is_method: bool = False) -> Optional[FunctionInfo]:
    """
    Extract a FunctionInfo from a function_definition node.

    WHY child_by_field_name OVER iterating children:
    tree-sitter assigns named fields to important children. Using
    child_by_field_name('name') gives us exactly the name node
    regardless of what other children (decorators, type annotations)
    appear before it. Iterating and checking types is brittle when
    the grammar adds new optional fields.
    """
    name_node = node.child_by_field_name('name')
    if not name_node:
        return None

    params_node = node.child_by_field_name('parameters')
    body_node = node.child_by_field_name('body')

    return FunctionInfo(
        name=name_node.text.decode('utf-8'),
        params=_extract_params(params_node),
        line_start=node.start_point[0] + 1,   # tree-sitter is 0-indexed
        line_end=node.end_point[0] + 1,
        docstring=_get_block_docstring(body_node),
        is_async=is_async,
        is_method=is_method
    )


# -----------------------------------------------------------------------
# Class extraction
# -----------------------------------------------------------------------

def extract_class(node) -> Tuple[Optional[ClassInfo], list]:
    """
    Extract a ClassInfo and its methods from a class_definition node.

    Returns (ClassInfo, list[FunctionInfo]) — methods are returned
    separately so the agent can add them to the flat functions list.
    This makes it easy to query "all functions in this file" without
    having to know whether they are top-level or class methods.
    """
    name_node = node.child_by_field_name('name')
    if not name_node:
        return None, []

    # Base classes come from the 'superclasses' field
    # which is the (Base1, Base2) argument list after the class name
    bases = []
    superclasses_node = node.child_by_field_name('superclasses')
    if superclasses_node:
        for child in superclasses_node.named_children:
            if child.type in ('identifier', 'dotted_name', 'attribute'):
                bases.append(child.text.decode('utf-8'))

    body_node = node.child_by_field_name('body')
    docstring = _get_block_docstring(body_node)

    method_names = []
    methods = []

    if body_node:
        for child in body_node.named_children:
            fn = None
            if child.type == 'function_definition':
                fn = extract_function(child, is_async=False, is_method=True)
            elif child.type == 'async_function_definition':
                fn = extract_function(child, is_async=True, is_method=True)
            elif child.type == 'decorated_definition':
                # @property\ndef method(self): ...
                definition = child.child_by_field_name('definition')
                if definition:
                    is_async = definition.type == 'async_function_definition'
                    fn = extract_function(definition, is_async=is_async, is_method=True)

            if fn:
                method_names.append(fn.name)
                methods.append(fn)

    class_info = ClassInfo(
        name=name_node.text.decode('utf-8'),
        bases=bases,
        method_names=method_names,
        line_start=node.start_point[0] + 1,
        line_end=node.end_point[0] + 1,
        docstring=docstring
    )
    return class_info, methods


# -----------------------------------------------------------------------
# Import extraction
# -----------------------------------------------------------------------

def extract_import(node) -> Optional[ImportInfo]:
    """
    Extract an ImportInfo from an import_statement or import_from_statement.

    Examples handled:
      import os                     → module="os",       names=[], from=False
      import os, sys                → module="os, sys",  names=[], from=False
      from pathlib import Path      → module="pathlib",  names=["Path"], from=True
      from typing import Optional   → module="typing",   names=["Optional"], from=True
      from . import utils           → module=".",        names=["utils"], from=True
      from ..models import User     → module="..models", names=["User"], from=True
      from typing import *          → module="typing",   names=["*"], from=True
    """
    if node.type == 'import_statement':
        modules = []
        for child in node.named_children:
            if child.type == 'dotted_name':
                modules.append(child.text.decode('utf-8'))
            elif child.type == 'aliased_import':
                for ac in child.children:
                    if ac.type == 'dotted_name':
                        modules.append(ac.text.decode('utf-8'))
                        break
        return ImportInfo(
            module=', '.join(modules),
            names=[],
            is_from_import=False,
            is_internal=False
        )

    elif node.type == 'import_from_statement':
        prefix = ''
        module = ''
        names = []
        past_import_kw = False

        for child in node.children:
            ctype = child.type

            if ctype in ('from', 'import', ',', '(', ')'):
                if ctype == 'import':
                    past_import_kw = True
                continue

            if not past_import_kw:
                if ctype == 'relative_import':
                    # Handles: from . import X  or  from ..models import Y
                    for rc in child.children:
                        if rc.type == 'import_prefix':
                            prefix = rc.text.decode('utf-8')
                        elif rc.type == 'dotted_name':
                            module = rc.text.decode('utf-8')
                elif ctype == 'dotted_name':
                    module = child.text.decode('utf-8')
            else:
                if ctype in ('dotted_name', 'identifier'):
                    names.append(child.text.decode('utf-8'))
                elif ctype == 'aliased_import':
                    for ac in child.children:
                        if ac.type in ('dotted_name', 'identifier'):
                            names.append(ac.text.decode('utf-8'))
                            break
                elif ctype == 'wildcard_import':
                    names.append('*')

        return ImportInfo(
            module=prefix + module,
            names=names,
            is_from_import=True,
            is_internal=False
        )

    return None


# -----------------------------------------------------------------------
# Top-level entry point
# -----------------------------------------------------------------------

def extract_symbols(tree, source_bytes: bytes) -> Tuple[Optional[str], list, list, list]:
    """
    Walk the root module node and extract all top-level symbols.

    Returns: (module_docstring, functions, classes, imports)

    Functions includes both top-level functions AND class methods.
    Classes contains only class-level info (not methods).
    This duplication is intentional: it lets agents query
    "all functions" without needing to recurse into classes.
    """
    root = tree.root_node
    module_docstring = None
    functions = []
    classes = []
    imports = []

    for i, node in enumerate(root.named_children):
        ntype = node.type

        # Module docstring: must be the very first statement
        if i == 0 and ntype == 'expression_statement':
            for child in node.children:
                if child.type == 'string':
                    module_docstring = clean_docstring(child.text.decode('utf-8'))
                    break
            continue

        if ntype == 'function_definition':
            fn = extract_function(node, is_async=False)
            if fn:
                functions.append(fn)

        elif ntype == 'async_function_definition':
            fn = extract_function(node, is_async=True)
            if fn:
                functions.append(fn)

        elif ntype == 'class_definition':
            cls, methods = extract_class(node)
            if cls:
                classes.append(cls)
                functions.extend(methods)

        elif ntype in ('import_statement', 'import_from_statement'):
            imp = extract_import(node)
            if imp:
                imports.append(imp)

        elif ntype == 'decorated_definition':
            # @decorator applied to a function or class
            definition = node.child_by_field_name('definition')
            if definition:
                dtype = definition.type
                if dtype == 'function_definition':
                    fn = extract_function(definition, is_async=False)
                    if fn:
                        functions.append(fn)
                elif dtype == 'async_function_definition':
                    fn = extract_function(definition, is_async=True)
                    if fn:
                        functions.append(fn)
                elif dtype == 'class_definition':
                    cls, methods = extract_class(definition)
                    if cls:
                        classes.append(cls)
                        functions.extend(methods)

    return module_docstring, functions, classes, imports