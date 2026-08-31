"""
AST-based code chunker for Phase 5.

Chunk types:
  module   - file-level: module docstring + reconstructed import statements
  function - one function's complete source extracted by line numbers
  class    - class header + docstring (methods are separate function chunks)

WHY LINE-BASED EXTRACTION OVER RE-PARSING:
FunctionInfo and ClassInfo from Phase 2 store precise line_start and
line_end. Extracting source is: split raw_content on newlines, slice
by index. No re-parsing needed. The chunk content is the exact original
source, indentation and comments included. This matters for code
embeddings: the model needs real code, not a reconstructed approximation.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class CodeChunk:
    """
    A single retrievable unit of code.
    Stored in ChromaDB as one document with metadata.
    """
    chunk_id: str           # unique: "{sanitized_path}::{symbol_name}::{line_start}::{symbol_type}"
    content: str            # exact source text sent to the embedding model
    file_path: str
    symbol_name: str        # function name, class name, or "module"
    symbol_type: str        # "function" | "class" | "module"
    language: str
    line_start: int
    line_end: int
    complexity: Optional[float]    # None for module and class chunks
    risk_level: Optional[str]      # from Phase 4 ComplexityScore on the file


def make_chunks(
    file_path: str,
    language: str,
    raw_content: str,
    symbol_table,
    complexity_score=None
) -> list:
    """
    Produce all chunks for a single file.
    Returns list[CodeChunk]. Always at least one chunk (the module chunk)
    unless raw_content is empty.
    """
    if not raw_content:
        return []

    lines = raw_content.split('\n')
    chunks = []

    module_chunk = _make_module_chunk(file_path, language, symbol_table)
    if module_chunk:
        chunks.append(module_chunk)

    for func in symbol_table.functions:
        chunk = _make_function_chunk(file_path, language, lines, func, complexity_score)
        if chunk:
            chunks.append(chunk)

    for cls in symbol_table.classes:
        chunk = _make_class_chunk(file_path, language, lines, cls, complexity_score)
        if chunk:
            chunks.append(chunk)

    # Disambiguate any duplicate chunk IDs (e.g. identical symbol names on the same line)
    seen_ids = {}
    unique_chunks = []
    for chunk in chunks:
        base_id = chunk.chunk_id
        if base_id in seen_ids:
            seen_ids[base_id] += 1
            chunk.chunk_id = f"{base_id}_{seen_ids[base_id]}"
        else:
            seen_ids[base_id] = 0
        unique_chunks.append(chunk)

    return unique_chunks


# -----------------------------------------------------------------------
# Chunk constructors
# -----------------------------------------------------------------------

def _make_module_chunk(file_path: str, language: str, symbol_table) -> Optional[CodeChunk]:
    """
    Module chunk = module docstring + reconstructed import statements.

    WHY RECONSTRUCT IMPORTS INSTEAD OF EXTRACTING LINES:
    Import statements can be scattered across a file (some at top,
    some inside conditionals in legacy Python). Reconstructing from
    ImportInfo objects gives a clean, consolidated view of all imports.
    This is more useful for retrieval: "where is 'requests' used?"
    finds this chunk even if the import is on line 847.
    """
    parts = []

    if symbol_table.module_docstring:
        parts.append(f'"""{symbol_table.module_docstring}"""')

    if symbol_table.imports:
        import_lines = []
        for imp in symbol_table.imports:
            if imp.is_from_import:
                names_str = ', '.join(imp.names) if imp.names else '*'
                import_lines.append(f"from {imp.module} import {names_str}")
            else:
                import_lines.append(f"import {imp.module}")
        parts.append('\n'.join(import_lines))

    if not parts:
        return None

    content = f"# MODULE: {file_path}\n" + '\n\n'.join(parts)
    return CodeChunk(
        chunk_id=_make_chunk_id(file_path, "module", "module", line_start=1),
        content=content,
        file_path=file_path,
        symbol_name="module",
        symbol_type="module",
        language=language,
        line_start=1,
        line_end=min(30, len(parts[0].split('\n'))),
        complexity=None,
        risk_level=None
    )


def _make_function_chunk(
    file_path: str,
    language: str,
    lines: list,
    func,
    complexity_score
) -> Optional[CodeChunk]:
    """
    Function chunk = complete function source extracted by line numbers.

    WHY INCLUDE A HEADER COMMENT:
    The embedding model has no context about which file this chunk came
    from. Prepending "# function_name (file/path.py)" gives the model
    the function name and file path as part of the text being embedded.
    Queries like "where is validate_user defined?" now match this header
    comment in addition to the function body content.
    """
    content = _extract_lines(lines, func.line_start, func.line_end)
    if not content:
        return None

    header = f"# {func.name} ({file_path})"
    full_content = f"{header}\n{content}"

    # Match function to its complexity score
    complexity = None
    if complexity_score and complexity_score.function_scores:
        complexity = complexity_score.function_scores.get(func.name)
        # radon prefixes methods with "ClassName." — try that if direct lookup fails
        if complexity is None and func.is_method:
            for key, val in complexity_score.function_scores.items():
                if key.endswith(f'.{func.name}'):
                    complexity = val
                    break

    risk_level = complexity_score.risk_level if complexity_score else None

    return CodeChunk(
        chunk_id=_make_chunk_id(file_path, func.name, "function", line_start=func.line_start),
        content=full_content,
        file_path=file_path,
        symbol_name=func.name,
        symbol_type="function",
        language=language,
        line_start=func.line_start,
        line_end=func.line_end,
        complexity=float(complexity) if complexity is not None else None,
        risk_level=risk_level
    )


def _make_class_chunk(
    file_path: str,
    language: str,
    lines: list,
    cls,
    complexity_score
) -> Optional[CodeChunk]:
    """
    Class chunk = class declaration + class docstring.

    WHY NOT INCLUDE METHOD BODIES HERE:
    Methods are separate function chunks. Including them in the class
    chunk creates large, unfocused chunks that combine two distinct
    retrieval targets: "what is this class for?" (class chunk) and
    "what does this method do?" (function chunk).

    We take lines from class_start to min(class_start + 15, class_end).
    15 lines captures the declaration, docstring, and class variables
    in almost all real-world cases without pulling in method bodies.
    """
    header_end = min(cls.line_start + 15, cls.line_end)
    content = _extract_lines(lines, cls.line_start, header_end)
    if not content:
        return None

    header = f"# class {cls.name} ({file_path})"
    full_content = f"{header}\n{content}"

    risk_level = complexity_score.risk_level if complexity_score else None

    return CodeChunk(
        chunk_id=_make_chunk_id(file_path, cls.name, "class", line_start=cls.line_start),
        content=full_content,
        file_path=file_path,
        symbol_name=cls.name,
        symbol_type="class",
        language=language,
        line_start=cls.line_start,
        line_end=header_end,
        complexity=None,
        risk_level=risk_level
    )


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _extract_lines(lines: list, line_start: int, line_end: int) -> str:
    """
    Extract source lines by 1-indexed line numbers. Clamps to valid range.
    """
    start = max(0, line_start - 1)
    end = min(len(lines), line_end)
    return '\n'.join(lines[start:end]).strip()


def _make_chunk_id(
    file_path: str,
    symbol_name: str,
    symbol_type: str,
    line_start: int = 0
) -> str:
    """
    Unique, deterministic chunk ID for ChromaDB.

    WHY line_start IS REQUIRED:
    Multiple classes in the same file can have methods with identical names
    (e.g. __init__, render, __repr__). Without line_start, two different
    methods in two different classes produce the same ID:
      fastapi/responses.py::render::function  (line 12)
      fastapi/responses.py::render::function  (line 47)
    ChromaDB raises DuplicateIDError on batch insert.
    Adding line_start makes every chunk unique:
      fastapi/responses.py::render::12::function
      fastapi/responses.py::render::47::function
    """
    safe_path = file_path.replace('/', '_').replace('.', '_').replace('-', '_')
    safe_name = symbol_name.replace('.', '_').replace(' ', '_')
    return f"{safe_path}::{safe_name}::{line_start}::{symbol_type}"