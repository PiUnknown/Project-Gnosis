"""
Tests for the AST Parser Agent (Phase 2).

All tests work offline. No GitHub API calls, no Groq calls.
We parse hardcoded source strings to verify symbol extraction.
"""
import pytest
from src.parsers.python_parser import (
    extract_symbols as extract_python,
    clean_docstring,
)
from src.parsers.js_parser import extract_symbols as extract_js
from src.utils.tree_sitter_utils import get_parser
from src.agents.ast_parser import _is_internal_python, _is_internal_js


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def parse_python(source: str):
    parser = get_parser("Python")
    assert parser is not None, "Python tree-sitter grammar not installed"
    tree = parser.parse(bytes(source, 'utf-8'))
    return extract_python(tree, bytes(source, 'utf-8'))


def parse_js(source: str, language: str = "JavaScript"):
    parser = get_parser(language)
    assert parser is not None, f"{language} tree-sitter grammar not installed"
    tree = parser.parse(bytes(source, 'utf-8'))
    return extract_js(tree, bytes(source, 'utf-8'), language)


# -----------------------------------------------------------------------
# Docstring cleaning
# -----------------------------------------------------------------------

class TestCleanDocstring:

    def test_triple_double_quote(self):
        assert clean_docstring('"""Hello world."""') == "Hello world."

    def test_triple_single_quote(self):
        assert clean_docstring("'''Hello world.'''") == "Hello world."

    def test_multiline_docstring(self):
        raw = '"""First line.\n\nSecond paragraph."""'
        result = clean_docstring(raw)
        assert result is not None
        assert "First line." in result

    def test_none_on_empty(self):
        assert clean_docstring('""""""') is None or clean_docstring('""""""') == ''


# -----------------------------------------------------------------------
# Python: functions
# -----------------------------------------------------------------------

class TestPythonFunctions:

    def test_basic_function(self):
        source = '''
def greet(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}"
'''
        _, functions, _, _ = parse_python(source)
        assert len(functions) == 1
        assert functions[0].name == "greet"
        assert "name" in functions[0].params
        assert functions[0].docstring == "Say hello."
        assert functions[0].is_async is False
        assert functions[0].is_method is False

    def test_async_function(self):
        source = '''
async def fetch_user(user_id: int):
    return await db.get(user_id)
'''
        _, functions, _, _ = parse_python(source)
        assert len(functions) == 1
        assert functions[0].is_async is True
        assert functions[0].name == "fetch_user"

    def test_function_no_docstring(self):
        source = '''
def add(a, b):
    return a + b
'''
        _, functions, _, _ = parse_python(source)
        assert functions[0].docstring is None

    def test_function_with_args_and_kwargs(self):
        source = '''
def wrapper(*args, **kwargs):
    pass
'''
        _, functions, _, _ = parse_python(source)
        params = functions[0].params
        assert any('*' in p for p in params)
        assert any('**' in p for p in params)

    def test_multiple_functions(self):
        source = '''
def foo(): pass
def bar(): pass
def baz(): pass
'''
        _, functions, _, _ = parse_python(source)
        names = [f.name for f in functions]
        assert "foo" in names
        assert "bar" in names
        assert "baz" in names

    def test_line_numbers(self):
        source = '''def foo():
    pass
'''
        _, functions, _, _ = parse_python(source)
        assert functions[0].line_start == 1


# -----------------------------------------------------------------------
# Python: classes
# -----------------------------------------------------------------------

class TestPythonClasses:

    def test_basic_class(self):
        source = '''
class PaymentProcessor:
    """Handles payments."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def process(self, amount: float) -> bool:
        return True
'''
        _, functions, classes, _ = parse_python(source)
        assert len(classes) == 1
        assert classes[0].name == "PaymentProcessor"
        assert classes[0].docstring == "Handles payments."
        assert "__init__" in classes[0].method_names
        assert "process" in classes[0].method_names

    def test_methods_appear_in_functions_list(self):
        source = '''
class Foo:
    def method_a(self): pass
    def method_b(self): pass
'''
        _, functions, classes, _ = parse_python(source)
        function_names = [f.name for f in functions]
        assert "method_a" in function_names
        assert "method_b" in function_names
        # Methods are flagged correctly
        assert all(f.is_method for f in functions)

    def test_class_inheritance(self):
        source = '''
class Child(Parent, Mixin):
    pass
'''
        _, _, classes, _ = parse_python(source)
        assert "Parent" in classes[0].bases
        assert "Mixin" in classes[0].bases


# -----------------------------------------------------------------------
# Python: imports
# -----------------------------------------------------------------------

class TestPythonImports:

    def test_bare_import(self):
        source = 'import os\n'
        _, _, _, imports = parse_python(source)
        assert any('os' in i.module for i in imports)
        assert all(not i.is_from_import for i in imports if 'os' in i.module)

    def test_from_import(self):
        source = 'from pathlib import Path\n'
        _, _, _, imports = parse_python(source)
        assert len(imports) == 1
        assert 'pathlib' in imports[0].module
        assert 'Path' in imports[0].names
        assert imports[0].is_from_import is True

    def test_multi_name_import(self):
        source = 'from typing import Optional, List, Dict\n'
        _, _, _, imports = parse_python(source)
        assert 'Optional' in imports[0].names
        assert 'List' in imports[0].names
        assert 'Dict' in imports[0].names

    def test_relative_import(self):
        source = 'from . import utils\n'
        _, _, _, imports = parse_python(source)
        relative = [i for i in imports if i.module.startswith('.')]
        assert len(relative) >= 1

    def test_relative_import_with_module(self):
        source = 'from ..models import User\n'
        _, _, _, imports = parse_python(source)
        assert any(i.module.startswith('..') for i in imports)


# -----------------------------------------------------------------------
# Python: parse error detection
# -----------------------------------------------------------------------

class TestPythonParseErrors:

    def test_detects_syntax_error(self):
        source = 'def broken(\n'  # Unclosed parenthesis
        parser = get_parser("Python")
        tree = parser.parse(bytes(source, 'utf-8'))
        assert tree.root_node.has_error is True

    def test_valid_code_has_no_error(self):
        source = 'def valid(): pass\n'
        parser = get_parser("Python")
        tree = parser.parse(bytes(source, 'utf-8'))
        assert tree.root_node.has_error is False


# -----------------------------------------------------------------------
# Python: module docstring
# -----------------------------------------------------------------------

class TestPythonModuleDocstring:

    def test_module_docstring_extracted(self):
        source = '"""This module handles authentication."""\n\nimport os\n'
        docstring, _, _, _ = parse_python(source)
        assert docstring is not None
        assert "authentication" in docstring

    def test_no_docstring_returns_none(self):
        source = 'import os\n'
        docstring, _, _, _ = parse_python(source)
        assert docstring is None


# -----------------------------------------------------------------------
# JavaScript: functions
# -----------------------------------------------------------------------

class TestJSFunctions:

    def test_function_declaration(self):
        source = '''
function processPayment(userId, amount) {
    return true;
}
'''
        _, functions, _, _ = parse_js(source)
        assert len(functions) == 1
        assert functions[0].name == "processPayment"
        assert "userId" in functions[0].params
        assert "amount" in functions[0].params

    def test_arrow_function(self):
        source = '''
const getUser = async (id) => {
    return await db.find(id);
};
'''
        _, functions, _, _ = parse_js(source)
        assert len(functions) == 1
        assert functions[0].name == "getUser"
        assert functions[0].is_async is True

    def test_exported_function(self):
        source = '''
export function createUser(data) {
    return db.insert(data);
}
'''
        _, functions, _, _ = parse_js(source)
        assert len(functions) == 1
        assert functions[0].name == "createUser"


# -----------------------------------------------------------------------
# JavaScript: classes
# -----------------------------------------------------------------------

class TestJSClasses:

    def test_basic_class(self):
        source = '''
class UserService extends BaseService {
    constructor(db) {
        this.db = db;
    }

    async findById(id) {
        return this.db.find(id);
    }
}
'''
        _, functions, classes, _ = parse_js(source)
        assert len(classes) == 1
        assert classes[0].name == "UserService"
        assert "BaseService" in classes[0].bases
        assert "constructor" in classes[0].method_names
        assert "findById" in classes[0].method_names


# -----------------------------------------------------------------------
# JavaScript: imports
# -----------------------------------------------------------------------

class TestJSImports:

    def test_default_import(self):
        source = "import React from 'react';\n"
        _, _, _, imports = parse_js(source)
        assert len(imports) == 1
        assert imports[0].module == "react"
        assert "React" in imports[0].names

    def test_named_import(self):
        source = "import { useState, useEffect } from 'react';\n"
        _, _, _, imports = parse_js(source)
        assert "useState" in imports[0].names
        assert "useEffect" in imports[0].names

    def test_relative_import(self):
        source = "import { fetchUser } from './api/users';\n"
        _, _, _, imports = parse_js(source)
        assert imports[0].module == "./api/users"


# -----------------------------------------------------------------------
# Internal import resolution
# -----------------------------------------------------------------------

class TestInternalResolution:

    def test_python_relative_is_internal(self):
        assert _is_internal_python('.utils', set()) is True
        assert _is_internal_python('..models', set()) is True

    def test_python_resolves_by_file_path(self):
        file_paths = {'src/utils/github_api.py', 'src/state.py'}
        assert _is_internal_python('src.utils.github_api', file_paths) is True
        assert _is_internal_python('requests', file_paths) is False

    def test_python_resolves_package_init(self):
        file_paths = {'src/utils/__init__.py'}
        assert _is_internal_python('src.utils', file_paths) is True

    def test_js_relative_is_internal(self):
        assert _is_internal_js('./utils') is True
        assert _is_internal_js('../api/users') is True

    def test_js_bare_specifier_is_external(self):
        assert _is_internal_js('react') is False
        assert _is_internal_js('lodash') is False