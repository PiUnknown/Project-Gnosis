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

import os
import uuid
import concurrent.futures
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from src.api import pipeline_runner
from src.api.job_store import store
from src.api.queue import enqueue_analysis_job, get_queue_stats, _local_executor
from src.utils.github_api import parse_github_url, fetch_repo_metadata, fetch_file_tree
from src.utils.filters import should_include_file
from src.api.models import (
    PHASE_PROGRESS,
    JobStatusResponse,
    JobSummary,
    JobListResponse,
    AnalysisResult,
    HealthResponse,
    SubmitResponse
)

VERSION = "1.0.5"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Local fallback executor instance (referenced in test fixtures)
_executor = _local_executor

AGENT_PHASE_MAP = [
    ("01", "INGESTION", "ingestion"),
    ("02", "AST PARSER", "ast_parser"),
    ("03", "DEPENDENCY GRAPH", "dependency_graph"),
    ("04", "COMPLEXITY SCORER", "complexity_scorer"),
    ("05", "CODE RAG", "code_rag"),
    ("06", "EXPLAINABILITY", "explainability"),
    ("07", "DOC GENERATOR", "doc_generator")
]

class UnifiedAnalyzeRequest(BaseModel):
    repo_url: str
    max_explanations: int = 20
    skip_llm: bool = False
    options: Optional[dict] = None

    @field_validator("max_explanations")
    @classmethod
    def validate_max_explanations(cls, v: int) -> int:
        if v < 0:
            raise ValueError("max_explanations must be >= 0")
        if v > 100:
            raise ValueError("max_explanations cannot exceed 100")
        return v

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("repo_url cannot be empty")
        if "github.com" not in v:
            raise ValueError("URL must contain 'github.com'")
        parts = v.replace("https://", "").replace("http://", "").split("/")
        if len(parts) < 3:
            raise ValueError("URL must be in format https://github.com/owner/repo")
        return v

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
def analyze(req: UnifiedAnalyzeRequest):
    # Extract options
    max_explanations = req.max_explanations
    skip_llm = req.skip_llm
    github_token = None
    if req.options:
        opt_max = req.options.get("max_explanations")
        if opt_max is not None:
            if opt_max < 0 or opt_max > 100:
                raise HTTPException(status_code=422, detail="max_explanations validation error")
            max_explanations = opt_max
        opt_skip = req.options.get("skip_llm")
        if opt_skip is not None:
            skip_llm = opt_skip
        github_token = req.options.get("github_token")

    # Deduplication check
    for job in store.list_all():
        if (job.repo_url == req.repo_url 
                and job.status in ("queued", "running")):
            return JSONResponse(
                status_code=409,
                content={
                    "job_id": job.job_id,
                    "status": job.status,
                    "message": "A job for this repository is already running."
                }
            )

    # Validate file count before enqueuing a job
    try:
        owner, repo_name = parse_github_url(req.repo_url)
        metadata = fetch_repo_metadata(owner, repo_name, github_token)
        default_branch = metadata.get("default_branch", "main")
        tree_entries = fetch_file_tree(owner, repo_name, default_branch, github_token)
        filtered_files = [
            entry for entry in tree_entries 
            if should_include_file(entry["path"], entry.get("size", 0))
        ]
        
        max_sampled = int(os.getenv("MAX_SAMPLED_ANALYSIS_FILES", 3000))
        if len(filtered_files) > max_sampled:
            raise HTTPException(
                status_code=400,
                detail=f"Repository exceeds the maximum file limit of {max_sampled} files (found {len(filtered_files)}). Analysis rejected."
            )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(
            status_code=400,
            detail=f"Failed to validate repository size: {exc}"
        )

    options = {
        "max_explanations": max_explanations,
        "skip_llm": skip_llm,
        "github_token": github_token
    }
    job_id = store.create(req.repo_url, options)
    enqueue_analysis_job(job_id, req.repo_url, options, executor=_executor)

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
def get_api_job_result(job_id: str):
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "failed":
        raise HTTPException(status_code=500, detail=f"Job failed: {job.error}")
    if job.status in ("queued", "running"):
        return JSONResponse(status_code=202, content={"status": job.status, "error": "not ready"})
    if job.result is None:
        return JSONResponse(status_code=202, content={"status": "processing", "error": "not ready"})
    return job.result

@app.delete("/jobs/{job_id}", tags=["Jobs"])
@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Attempt to clean up the ChromaDB collection associated with this job
    try:
        from src.utils.github_api import parse_github_url
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
@app.get("/api/health")
def health():
    stats = get_queue_stats()
    return HealthResponse(
        status="ok",
        version=VERSION,
        active_jobs=store.active_count(),
        redis_connected=stats.get("redis_connected"),
        queue_mode=stats.get("mode"),
        queue_depth=stats.get("queue_depth")
    )

@app.get("/")
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