from pathlib import Path


# -----------------------------------------------------------------------
# Directories: if any path segment matches, skip the file entirely
# -----------------------------------------------------------------------
EXCLUDED_DIRS = {
    "node_modules", ".git", "__pycache__", ".pytest_cache",
    "dist", "build", ".next", ".nuxt", "out",
    "venv", ".venv", "env", ".env",
    "vendor", "target", ".cargo",
    "coverage", ".nyc_output", "htmlcov",
    ".tox", "site-packages", ".mypy_cache",
    ".ruff_cache", ".hypothesis",
}

# -----------------------------------------------------------------------
# File extensions we care about
# -----------------------------------------------------------------------
SUPPORTED_EXTENSIONS = {
    # Core languages (Phase 2 AST support)
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go",
    # Future language support
    ".rs", ".java", ".c", ".cpp", ".h", ".hpp",
    # Config and structure (useful for understanding the project)
    ".yaml", ".yml", ".toml",
    # Markdown: we fetch README for project summary in Phase 7
    ".md",
}

# -----------------------------------------------------------------------
# Specific filenames to always skip
# -----------------------------------------------------------------------
EXCLUDED_FILENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Pipfile.lock", "Cargo.lock",
    "go.sum", "go.mod",
    ".DS_Store", "Thumbs.db",
    "bundle.js", "chunk.js",
}

# -----------------------------------------------------------------------
# Minified & bundle file patterns to always skip
# -----------------------------------------------------------------------
EXCLUDED_SUFFIXES = {
    ".min.js", ".min.mjs", ".min.cjs",
    ".min.css", ".bundle.js", ".bundle.min.js",
    ".chunk.js",
}

# -----------------------------------------------------------------------
# Max file size: skip files above this (generated/minified code)
# -----------------------------------------------------------------------
MAX_FILE_SIZE_BYTES = 150_000  # 150 KB


def should_include_file(path: str, size_bytes: int) -> bool:
    """
    Returns True if this file should be included in the manifest.

    Exclusion priority:
    1. Directory exclusion (fastest, checked first)
    2. Filename exclusion
    3. Minified / bundle suffix exclusion
    4. Extension check
    5. File size check
    """
    p = Path(path)

    # 1. Check every directory component in the path
    # Path("src/__pycache__/utils.py").parts = ("src", "__pycache__", "utils.py")
    for part in p.parts[:-1]:
        if part in EXCLUDED_DIRS:
            return False
        # Catch patterns like "package.egg-info"
        if part.endswith(".egg-info"):
            return False

    # 2. Check filename
    if p.name in EXCLUDED_FILENAMES:
        return False

    # 3. Check minified / bundle suffix
    name_lower = p.name.lower()
    for suffix in EXCLUDED_SUFFIXES:
        if name_lower.endswith(suffix):
            return False

    # 4. Check extension
    if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return False

    # 5. Check size
    if size_bytes > MAX_FILE_SIZE_BYTES:
        return False

    return True


# -----------------------------------------------------------------------
# Language detection by extension
# -----------------------------------------------------------------------
LANGUAGE_MAP = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".md": "Markdown",
}


def detect_language(path: str) -> str:
    """Detect programming language from file extension."""
    ext = Path(path).suffix.lower()
    return LANGUAGE_MAP.get(ext, "Unknown")