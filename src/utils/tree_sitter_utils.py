"""
Parser factory for tree-sitter.

Initializes and caches language parsers. Initialization is expensive
(loads grammar binaries). We do it once per language per process.
"""
from typing import Optional

# Module-level cache: language string -> Parser object
_parser_cache: dict = {}


def get_parser(language: str):
    """
    Get a cached tree-sitter Parser for the given language.

    Returns None if the language is not supported or the grammar
    package is not installed.

    WHY A CACHE:
    Creating a Parser object involves loading the grammar binary and
    compiling the language. For 300 Python files, doing that 300 times
    would add noticeable overhead. We initialize once and reuse.
    """
    if language in _parser_cache:
        return _parser_cache[language]

    lang = _build_language(language)
    if lang is None:
        return None

    parser = _create_parser(lang)
    if parser is None:
        return None

    _parser_cache[language] = parser
    return parser


def _build_language(language: str):
    """
    Build a tree-sitter Language object for the given language string.
    Returns None if the grammar package is not installed.
    """
    try:
        from tree_sitter import Language

        if language == "Python":
            import tree_sitter_python as tsp
            return Language(tsp.language())

        elif language == "JavaScript":
            import tree_sitter_javascript as tsj
            return Language(tsj.language())

        elif language == "TypeScript":
            import tree_sitter_typescript as tst
            return Language(tst.language_typescript())

        # TypeScript TSX variant (.tsx files)
        elif language == "TSX":
            import tree_sitter_typescript as tst
            return Language(tst.language_tsx())

        elif language == "Go":
            import tree_sitter_go as tsg
            return Language(tsg.language())

        elif language == "Rust":
            import tree_sitter_rust as tsr
            return Language(tsr.language())

        elif language == "Java":
            import tree_sitter_java as tsj_java
            return Language(tsj_java.language())

        elif language in ("C", "C/C++ Header"):
            import tree_sitter_c as tsc
            return Language(tsc.language())

        elif language in ("C++", "C++ Header"):
            import tree_sitter_cpp as tscpp
            return Language(tscpp.language())

        else:
            return None

    except (ImportError, AttributeError, Exception):
        return None


def _create_parser(language_object):
    """
    Create a Parser from a Language object.
    Handles API differences between tree-sitter 0.21.x and 0.22.x.

    0.21.x: Parser() then parser.set_language(lang)
    0.22.x: Parser(lang) directly
    """
    try:
        from tree_sitter import Parser

        # Try the newer API first (0.22+)
        try:
            return Parser(language_object)
        except TypeError:
            # Fall back to 0.21.x API
            parser = Parser()
            parser.set_language(language_object)
            return parser

    except Exception:
        return None


def supported_languages() -> list:
    return ["Python", "JavaScript", "TypeScript", "Go", "Rust", "Java", "C", "C++"]