from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FunctionInfo:
    name: str
    params: list
    line_start: int
    line_end: int
    docstring: Optional[str]
    is_async: bool
    is_method: bool          # True if defined inside a class body


@dataclass
class ClassInfo:
    name: str
    bases: list              # list of base class name strings
    method_names: list       # just the names, not FunctionInfo objects
    line_start: int
    line_end: int
    docstring: Optional[str]


@dataclass
class ImportInfo:
    module: str              # "os", "src.utils", "./components/Button"
    names: list              # ["Path", "getcwd"] or [] for bare imports
    is_from_import: bool     # True: "from X import Y", False: "import X"
    is_internal: bool        # True if resolves to a file in our manifest


@dataclass
class SymbolTable:
    file_path: str
    language: str
    module_docstring: Optional[str]
    functions: list = field(default_factory=list)    # list[FunctionInfo]
    classes: list = field(default_factory=list)      # list[ClassInfo]
    imports: list = field(default_factory=list)      # list[ImportInfo]
    parse_error: bool = False
    parse_error_detail: Optional[str] = None

    @property
    def all_function_names(self) -> list:
        return [f.name for f in self.functions]

    @property
    def all_class_names(self) -> list:
        return [c.name for c in self.classes]

    @property
    def internal_imports(self) -> list:
        return [i for i in self.imports if i.is_internal]

    @property
    def external_imports(self) -> list:
        return [i for i in self.imports if not i.is_internal]

    @property
    def undocumented_functions(self) -> list:
        return [f for f in self.functions if not f.docstring]