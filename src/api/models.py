"""
Pydantic models for API request and response validation.

All models are defined here so main.py stays focused on routing logic.
"""
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# -----------------------------------------------------------------------
# Request models
# -----------------------------------------------------------------------

class AnalyzeOptions(BaseModel):
    """
    Optional pipeline configuration per request.
    All fields have defaults so the client can omit the options object entirely.
    """
    github_token: Optional[str] = None
    incremental: bool = False
    # Keep initial results fast; uncached explanations read the exact Git blob.
    # Set false only when synchronous vector indexing is required.
    defer_code_index: bool = True

    @field_validator("github_token")
    @classmethod
    def validate_github_token(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and len(value) > 500:
            raise ValueError("github_token cannot exceed 500 characters")
        return value


class AnalyzeRequest(BaseModel):
    repo_url: str
    options: AnalyzeOptions = Field(default_factory=AnalyzeOptions)

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
    The API also supports requesting named result sections so the initial
    report view does not download graph and explanation payloads it has not opened.
    """
    job_id: str
    repo_url: str
    status: str                    # "queued" | "running" | "complete" | "failed"
    current_phase: Optional[str]   # which agent is currently running
    phases_completed: list
    progress_pct: int              # 0-100
    explanations_completed: int = 0
    explanations_total: int = 0
    # Why explanations are missing, when they are. `explanations_failed > 0`
    # with `explanations_completed == 0` is a provider outage, not a skip.
    explanations_failed: int = 0
    explanation_error: Optional[str] = None
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
    file_explanations_md: Optional[str] = None
    agent_context: str
    summary: dict
    complexity_report: dict
    explanations: dict
    explanation_status: Optional[str] = None
    code_index_status: Optional[str] = "ready"
    graph_summary: dict
    graph_data: Optional[dict] = None
    analyzed_files: list[dict] = Field(default_factory=list)


class FileExplanationResponse(BaseModel):
    file_path: str
    explanation: str
    cached: bool = False


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
    redis_configured: Optional[bool] = None
    redis_connected: Optional[bool] = None
    queue_mode: Optional[str] = None
    queue_depth: Optional[int] = None


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
