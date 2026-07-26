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
    is_method: bool


@dataclass
class ClassInfo:
    name: str
    bases: list
    method_names: list
    line_start: int
    line_end: int
    docstring: Optional[str]


@dataclass
class ImportInfo:
    module: str
    names: list
    is_from_import: bool
    is_internal: bool


@dataclass
class SymbolTable:
    file_path: str
    language: str
    module_docstring: Optional[str]
    functions: list = field(default_factory=list)
    classes: list = field(default_factory=list)
    imports: list = field(default_factory=list)
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


# -----------------------------------------------------------------------
# Agent 4 output: one ComplexityScore per scored file
# Stored in state.complexity_scores[file_path]
# Read by Agents 6 and 7
# -----------------------------------------------------------------------

@dataclass
class ComplexityScore:
    """
    Complete complexity and risk profile for one file.

    WHY IN parsers/base.py AND NOT agents/complexity_scorer.py:
    This object is READ by multiple agents (6 and 7), not just written
    by Agent 4. Placing data models in the agent that writes them
    would force reader agents to import the writer agent.
    All shared data models live here so any agent can import them
    without creating circular dependencies.
    """
    file_path: str
    language: str

    # Per-function cyclomatic complexity.
    # key: function name (radon uses "ClassName.method" for methods)
    # value: integer complexity score
    function_scores: dict

    # Aggregate metrics across all functions in the file
    avg_complexity: float          # 0.0 if file has no functions
    max_complexity: float          # 0.0 if file has no functions
    max_complexity_function: str   # name of the worst function, "" if none

    function_count: int
    avg_function_lines: float      # average lines per function, 0.0 if no functions

    # Coupling: number of unique internal files this file imports
    # Sourced from graph_stats[file]['out_degree'] (Phase 3)
    coupling_score: int

    # Documentation health
    undocumented_count: int
    undocumented_ratio: float      # undocumented_count / function_count, 0.0 if no functions

    # Tech debt signals carried forward from upstream agents
    parse_error: bool              # from Phase 2 SymbolTable
    is_in_circular_dep: bool       # from Phase 3 circular_nodes

    line_count: int

    # Risk verdict
    risk_level: str                # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    risk_reasons: list             # list[str]: human-readable reasons, empty for LOW