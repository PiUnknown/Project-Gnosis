# src/api/main.py
import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv()

try:
    __import__("pysqlite3")
    import sys
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass

import logging
import os
import time
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, field_validator

from src.api.job_store import store, BackendUnavailableError
from src.api.models import AnalyzeOptions
from src.api.rate_limit import check_analyze_rate_limit
from src.api.queue import (
    enqueue_analysis_job,
    get_queue_stats,
    QueueDispatchError,
    _local_executor,
)
from src.api.models import (
    JobStatusResponse,
    JobSummary,
    JobListResponse,
    AnalysisResult,
    FileExplanationResponse,
    HealthResponse,
    SubmitResponse
)
from src.utils.github_api import parse_github_url
from src.utils.token_crypto import TokenEncryptionError, encrypt_github_token
from src.utils.token_crypto import decrypt_github_token

VERSION = "1.2.0"
logger = logging.getLogger(__name__)

RESULT_FIELDS = {
    "summary",
    "onboarding_doc",
    "agent_context",
    "file_explanations_md",
    "dependency_rows",
    "graph_data",
    "reading_order",
    "complexity_rows",
    "explanations",
    "analyzed_files",
    "explanation_status",
    "code_index_status",
    "complexity_report_json",
    "complexity_report",
    "circular_deps",
    "circular_deps_truncated",
    "branch",
    "repo",
    "job_id",
    "analysis_mode",
    "files_discovered",
    "files_analyzed",
    "edges",
    "in_degree",
    "out_degree",
    "topological_order",
}

app = FastAPI()

_default_cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8443",
    "http://127.0.0.1:8443",
]
_cors_origins_raw = os.getenv("CORS_ALLOWED_ORIGINS")
_cors_origins = (
    [origin.strip() for origin in _cors_origins_raw.split(",") if origin.strip()]
    if _cors_origins_raw is not None
    else _default_cors_origins
)
if not _cors_origins:
    _cors_origins = _default_cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Server-Timing"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)

@app.middleware("http")
async def add_security_headers(request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - started) * 1000
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Server-Timing"] = f"app;dur={duration_ms:.2f}"
    logger.info(
        "http_request method=%s path=%s status=%s duration_ms=%.2f",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response

# Local fallback executor instance (referenced in test fixtures)
_executor = _local_executor

AGENT_PHASE_MAP = [
    ("01", "INGESTION", "ingestion"),
    ("02", "AST PARSER", "ast_parser"),
    ("03", "DEPENDENCY GRAPH", "dependency_graph"),
    ("04", "COMPLEXITY SCORER", "complexity_scorer"),
    ("05", "CODE RAG", "code_rag"),
    ("06", "ON-DEMAND EXPLANATIONS", "explainability"),
    ("07", "DOC GENERATOR", "doc_generator")
]

class UnifiedAnalyzeRequest(BaseModel):
    repo_url: str
    github_token: Optional[str] = None
    incremental: bool = False
    options: Optional[AnalyzeOptions] = None

    @field_validator("github_token")
    @classmethod
    def validate_github_token(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 500:
            raise ValueError("github_token cannot exceed 500 characters")
        return v

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 2048:
            raise ValueError("repo_url cannot exceed 2048 characters")
        try:
            parse_github_url(v)
        except ValueError as exc:
            raise ValueError(
                "URL must point to a GitHub repository: https://github.com/owner/repo"
            ) from exc
        return v


class FileExplanationRequest(BaseModel):
    file_path: str

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, value: str) -> str:
        path = value.strip()
        if not path or chr(92) in path or path.startswith("/"):
            raise ValueError("file_path must be a repository-relative path")
        if any(part in ("", ".", "..") for part in path.split("/")):
            raise ValueError("file_path must be a normalized repository-relative path")
        return path

def _get_agents_list(job) -> list:
    """Helper to dynamically format the agents list for the frontend."""
    agents = []
    running_idx = -1
    for i, (id_, name, phase) in enumerate(AGENT_PHASE_MAP):
        if job.current_phase == phase:
            running_idx = i
            break

    if running_idx == -1 and job.status == "running":
        for i, (id_, name, phase) in enumerate(AGENT_PHASE_MAP):
            if phase not in job.phases_completed:
                running_idx = i
                break

    for i, (id_, name, phase) in enumerate(AGENT_PHASE_MAP):
        agent_status = "queued"
        if phase in job.phases_completed:
            agent_status = "complete"
        elif i == running_idx:
            if job.status == "failed":
                agent_status = "failed"
            else:
                agent_status = "running"
        elif job.status == "failed" and phase not in job.phases_completed:
            if i == running_idx or (running_idx == -1 and phase not in job.phases_completed):
                agent_status = "failed"
                running_idx = i
            else:
                agent_status = "queued"

        if job.status == "complete":
            agent_status = "complete"

        agents.append({
            "id": id_,
            "name": name,
            "status": agent_status
        })
    return agents

@app.post("/analyze", response_model=SubmitResponse, status_code=202, tags=["Analysis"])
@app.post("/api/analyze", status_code=202)
def analyze(req: UnifiedAnalyzeRequest, request: Request):
    client_ip = request.client.host if request.client else None
    check_analyze_rate_limit(client_ip, getattr(store, "redis_client", None))

    # Extract options
    github_token = req.github_token
    incremental = req.incremental
    defer_code_index = True

    if req.options:
        supplied_options = req.options.model_dump(exclude_unset=True)
        if supplied_options.get("github_token"):
            github_token = supplied_options.get("github_token")
        if supplied_options.get("incremental") is not None:
            incremental = bool(supplied_options.get("incremental"))
        if supplied_options.get("defer_code_index") is not None:
            defer_code_index = bool(supplied_options.get("defer_code_index"))

    # Restrict duplicate checks to active jobs. The active Redis index falls
    # back to a full scan until its operator-run reconciliation is armed.
    active_job = store.find_active_by_repo(req.repo_url)
    if active_job:
        return JSONResponse(
            status_code=409,
            content={
                "job_id": active_job.job_id,
                "status": active_job.status,
                "message": "A job for this repository is already running."
            }
        )

    worker_options = {
        "incremental": incremental,
        "defer_code_index": defer_code_index,
    }
    stored_options = dict(worker_options)
    if github_token:
        try:
            stored_options["github_token_encrypted"] = encrypt_github_token(github_token)
        except TokenEncryptionError as exc:
            logger.error("[Analyze] Per-job GitHub token encryption is unavailable: %s", exc)
            raise HTTPException(
                status_code=503,
                detail="Per-request GitHub token storage is not configured on this server.",
            ) from exc

    try:
        job_id = store.create(req.repo_url, stored_options)
    except BackendUnavailableError as exc:
        logger.error(f"[Analyze] Job store unavailable: {exc}")
        raise HTTPException(
            status_code=503,
            detail="Job storage is temporarily unavailable. Please retry shortly.",
        )

    try:
        enqueue_analysis_job(job_id, req.repo_url, worker_options, executor=_executor, store=store)
    except QueueDispatchError as exc:
        logger.error(f"[Analyze] Queue dispatch failed for job {job_id}: {exc}")
        try:
            store.fail(job_id, f"Queue dispatch failed: {exc}")
        except Exception:
            pass
        raise HTTPException(
            status_code=503,
            detail="Job queue is temporarily unavailable. Please retry shortly.",
        )

    return SubmitResponse(
        job_id=job_id,
        status="queued",
        message=f"Analysis started for {req.repo_url}. Poll GET /jobs/{job_id} to track progress."
    )

@app.get("/jobs/{job_id}", response_model=JobStatusResponse, tags=["Jobs"])
def get_job_status(job_id: str):
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@app.get("/api/jobs/{job_id}")
def get_api_job_status(job_id: str):
    job = store.get(job_id)
    if not job:
        return {"error": "job not found"}
    return {
        "job_id": job.job_id,
        "repo_url": job.repo_url,
        "status": job.status,
        "current_phase": job.current_phase,
        "phases_completed": job.phases_completed,
        "progress_pct": job.progress_pct,
        "explanations_completed": job.explanations_completed,
        "explanations_total": job.explanations_total,
        "explanations_failed": job.explanations_failed,
        "explanation_error": job.explanation_error,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
        "error": job.error,
        "agents": _get_agents_list(job)
    }

@app.get("/jobs/{job_id}/result", response_model=AnalysisResult, tags=["Jobs"])
def get_job_result(job_id: str):
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "failed":
        raise HTTPException(status_code=500, detail=f"Job failed: {job.error}")
    if job.status in ("queued", "running"):
        raise HTTPException(status_code=409, detail="Job is not complete")
    return job.result

@app.get("/api/jobs/{job_id}/result")
def get_api_job_result(job_id: str, sections: Optional[str] = None):
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "failed":
        raise HTTPException(status_code=500, detail=f"Job failed: {job.error}")
    if job.status in ("queued", "running"):
        return JSONResponse(status_code=202, content={"status": job.status, "error": "not ready"})
    if job.result is None:
        return JSONResponse(status_code=202, content={"status": "processing", "error": "not ready"})
    if not sections:
        return job.result

    requested = {section.strip() for section in sections.split(",") if section.strip()}
    unknown = requested - RESULT_FIELDS
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown result section(s): {', '.join(sorted(unknown))}"
        )
    return {key: job.result[key] for key in requested if key in job.result}


@app.post("/jobs/{job_id}/explanations", response_model=FileExplanationResponse, tags=["Jobs"])
@app.post("/api/jobs/{job_id}/explanations", response_model=FileExplanationResponse)
def explain_job_file(job_id: str, request: FileExplanationRequest):
    """Generate one explanation for a file included in a completed analysis."""
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "complete" or not job.result:
        raise HTTPException(status_code=409, detail="Analysis is not complete")

    file_metadata = next(
        (item for item in (job.result.get("analyzed_files") or [])
         if item.get("path") == request.file_path),
        None,
    )
    if file_metadata is None:
        raise HTTPException(status_code=404, detail="File was not included in this analysis")

    try:
        owner, repo_name = parse_github_url(job.repo_url)
        from src.agents.explainability import explain_file_on_demand
        from src.utils.retriever import make_collection_name

        encrypted_token = (job.options or {}).get("github_token_encrypted")
        github_token = decrypt_github_token(encrypted_token) if encrypted_token else None
        explanation, cached = explain_file_on_demand(
            owner=owner,
            repo_name=repo_name,
            branch=job.result.get("branch") or "main",
            file_path=request.file_path,
            file_sha=file_metadata.get("sha") or "",
            language=file_metadata.get("language") or "Unknown",
            collection_name=make_collection_name(owner, repo_name, job_id),
            file_metadata=file_metadata,
            github_token=github_token or os.getenv("GITHUB_TOKEN"),
        )
    except RuntimeError as exc:
        status_code = 503 if "NVIDIA_API_KEY" in str(exc) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not generate file explanation: {exc}") from exc

    if not store.update_explanation(job_id, request.file_path, explanation):
        raise HTTPException(status_code=500, detail="Could not save the explanation")
    return FileExplanationResponse(file_path=request.file_path, explanation=explanation, cached=cached)

@app.delete("/jobs/{job_id}", tags=["Jobs"])
@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == "running":
        raise HTTPException(
            status_code=409,
            detail="This analysis is already running and cannot be safely cancelled. You can delete it after it finishes.",
        )

    if job.status == "queued":
        from src.api.queue import cancel_analysis_job
        try:
            cancelled = cancel_analysis_job(job_id, store=store)
        except QueueDispatchError as exc:
            raise HTTPException(
                status_code=503,
                detail="The queued analysis could not be cancelled because the queue is unavailable.",
            ) from exc
        if not cancelled:
            raise HTTPException(
                status_code=409,
                detail="The analysis has started and cannot be safely cancelled.",
            )

    # Attempt to clean up the ChromaDB collection associated with this job
    try:
        if job.status in ("complete", "failed"):
            from src.utils.retriever import make_collection_name, DEFAULT_CHROMA_DB_PATH
            import chromadb

            owner, repo = parse_github_url(job.repo_url)
            collection_name = make_collection_name(owner, repo, job_id)

            client = chromadb.PersistentClient(path=DEFAULT_CHROMA_DB_PATH)
            client.delete_collection(name=collection_name)
            print(f"Cleaned up Chroma collection '{collection_name}' for deleted job {job_id}")
    except Exception as exc:
        print(f"Non-fatal: could not delete Chroma collection for job {job_id}: {exc}")

    deleted = store.delete(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Job not found")
    from fastapi.responses import Response
    return Response(status_code=204)

@app.get("/jobs", response_model=JobListResponse, tags=["Jobs"])
@app.get("/api/jobs")
def list_jobs():
    jobs = store.list_all()
    jobs_sorted = sorted(jobs, key=lambda j: j.created_at, reverse=True)
    summaries = [
        JobSummary(
            job_id=j.job_id,
            repo_url=j.repo_url,
            status=j.status,
            progress_pct=j.progress_pct,
            created_at=j.created_at,
            completed_at=j.completed_at
        )
        for j in jobs_sorted
    ]
    return JobListResponse(total=len(summaries), jobs=summaries)

@app.get("/health", response_model=HealthResponse, tags=["Info"])
@app.head("/health", tags=["Info"])
@app.get("/api/health")
@app.head("/api/health")
def health():
    stats = get_queue_stats(store)
    degraded = bool(stats.get("store_degraded"))
    return HealthResponse(
        status="degraded" if degraded else "ok",
        version=VERSION,
        active_jobs=store.active_count(),
        redis_configured=stats.get("redis_configured"),
        redis_connected=stats.get("redis_connected"),
        queue_mode=stats.get("mode"),
        queue_depth=stats.get("queue_depth")
    )

@app.get("/")
@app.head("/")
def root():
    return {
        "name":    "Project Gnosis — Code Archaeology Agent",
        "version": VERSION,
        "endpoints": {
            "POST /analyze":              "Submit a repo for analysis",
            "GET  /jobs/{job_id}":        "Poll job status",
            "GET  /jobs/{job_id}/result": "Fetch analysis result",
            "DELETE /jobs/{job_id}":      "Delete a job",
            "GET  /jobs":                 "List all jobs",
            "GET  /health":               "Health check",
            "GET  /docs":                 "Interactive API docs (Swagger UI)"
        }
    }

# Production: serve built frontend after all API routes
# app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")
