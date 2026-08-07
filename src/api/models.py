"""
Pydantic models for API request and response validation.

All models are defined here so main.py stays focused on routing logic.
Pydantic validates input automatically: if repo_url is missing or
max_explanations is negative, FastAPI returns a 422 before the handler runs.
"""
from typing import Optional
from pydantic import BaseModel, field_validator


# -----------------------------------------------------------------------
# Request models
# -----------------------------------------------------------------------

class AnalyzeOptions(BaseModel):
    """
    Optional pipeline configuration per request.
    All fields have defaults so the client can omit the options object entirely.
    """
    max_explanations: int = 20
    skip_llm: bool = False
    github_token: Optional[str] = None

    @field_validator("max_explanations")
    @classmethod
    def validate_max_explanations(cls, v: int) -> int:
        if v < 0:
            raise ValueError("max_explanations must be >= 0")
        if v > 100:
            raise ValueError(
                "max_explanations cannot exceed 100. "
                "Groq free tier allows ~6000 requests/day."
            )
        return v


class AnalyzeRequest(BaseModel):
    repo_url: str
    options: AnalyzeOptions = AnalyzeOptions()

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("repo_url cannot be empty")
        if "github.com" not in v:
            raise ValueError(
                "Only GitHub repositories are supported in v1. "
                "URL must contain 'github.com'."
            )
        parts = v.replace("https://", "").replace("http://", "").split("/")
        if len(parts) < 3:
            raise ValueError(
                "URL must be in format https://github.com/owner/repo"
            )
        return v


# -----------------------------------------------------------------------
# Job status models
# -----------------------------------------------------------------------

PHASE_NAMES = [
    "metadata",
    "ingestion",
    "ast_parser",
    "dependency_graph",
    "complexity_scorer",
    "code_rag",
    "explainability",
    "doc_generator"
]

PHASE_PROGRESS = {
    "metadata":          5,
    "ingestion":        20,
    "ast_parser":       35,
    "dependency_graph": 50,
    "complexity_scorer": 60,
    "code_rag":         75,
    "explainability":   90,
    "doc_generator":   100,
}


class JobStatusResponse(BaseModel):
    """
    Returned by GET /jobs/{job_id}.
    Contains progress information but not the full result.

    WHY SEPARATE STATUS AND RESULT ENDPOINTS:
    Status responses are tiny (< 1KB) and polled frequently.
    Result responses can be large (100KB+ for a big repo's onboarding doc).
    Combining them means every poll returns 100KB. Separating them means
    polls are fast and the large payload is fetched exactly once.
    """
    job_id: str
    repo_url: str
    status: str                    # "queued" | "running" | "complete" | "failed"
    current_phase: Optional[str]   # which agent is currently running
    phases_completed: list
    progress_pct: int              # 0-100
    created_at: str
    completed_at: Optional[str]
    error: Optional[str]


class JobSummary(BaseModel):
    """Lightweight job entry for the list endpoint."""
    job_id: str
    repo_url: str
    status: str
    progress_pct: int
    created_at: str
    completed_at: Optional[str]


class JobListResponse(BaseModel):
    total: int
    jobs: list


# -----------------------------------------------------------------------
# Result models
# -----------------------------------------------------------------------

class AnalysisResult(BaseModel):
    """
    Returned by GET /jobs/{job_id}/result when status == "complete".

    Only returns what the client needs. Raw ArchaeonState internals
    (NetworkX graph objects, tree-sitter trees) are not exposed.
    """
    job_id: str
    repo: str
    branch: str
    onboarding_doc: str
    summary: dict
    complexity_report: dict
    explanations: dict
    graph_summary: dict
    skip_llm: Optional[bool] = False


# -----------------------------------------------------------------------
# Generic responses
# -----------------------------------------------------------------------

class SubmitResponse(BaseModel):
    job_id: str
    status: str
    message: str


class HealthResponse(BaseModel):
    status: str
    version: str
    active_jobs: int


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None