"""
Project Gnosis — FastAPI Application

Endpoints:
  POST   /analyze              Submit a repo URL for analysis
  GET    /jobs/{job_id}        Get job status and progress
  GET    /jobs/{job_id}/result Get the analysis result (when complete)
  DELETE /jobs/{job_id}        Delete a job (queued, complete, or failed)
  GET    /jobs                 List all jobs
  GET    /health               Health check
  GET    /                     API info

Background task threading:
  Pipeline tasks are CPU/IO bound and run synchronously. FastAPI's
  BackgroundTasks runs the task in the same process after the response
  is sent. For v1 (single-server, development tool), this is acceptable.
  v2: use Celery + Redis for multi-worker task queues.
"""
import os
import concurrent.futures
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.models import (
    AnalyzeRequest,
    SubmitResponse,
    JobStatusResponse,
    JobSummary,
    JobListResponse,
    AnalysisResult,
    HealthResponse,
    ErrorResponse,
    PHASE_PROGRESS
)
from src.api.job_store import store
from src.api import pipeline_runner

VERSION = "0.1.0"

# Thread pool for running blocking pipeline tasks.
# max_workers=2: allows 2 concurrent analyses without overwhelming
# the machine. One analysis already uses significant CPU and RAM.
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup/shutdown context manager.
    Shuts down the thread pool cleanly when the server stops.
    wait=False: does not block shutdown waiting for in-progress jobs.
    Running jobs are interrupted. This is acceptable for v1.
    """
    yield
    _executor.shutdown(wait=False)


app = FastAPI(
    title="Project Gnosis — Code Archaeology Agent",
    description=(
        "Submit a GitHub repository URL and receive a complete "
        "architectural map, tech debt report, and onboarding document."
    ),
    version=VERSION,
    lifespan=lifespan
)

# CORS: allow all origins in development.
# Restrict to specific frontend origin in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# -----------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------

@app.get("/", tags=["Info"])
async def root():
    """API info and available endpoints."""
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


@app.get("/health", response_model=HealthResponse, tags=["Info"])
async def health():
    """Health check. Returns 200 if the API is up."""
    return HealthResponse(
        status="ok",
        version=VERSION,
        active_jobs=store.active_count()
    )


@app.post("/analyze", response_model=SubmitResponse, status_code=202, tags=["Analysis"])
async def analyze(request: AnalyzeRequest):
    """
    Submit a GitHub repository for analysis.

    Returns a job_id immediately. The pipeline runs in the background.
    Poll GET /jobs/{job_id} to track progress.
    Fetch GET /jobs/{job_id}/result when status is 'complete'.

    Status codes:
      202 Accepted  — job created and queued
      422           — invalid request (bad URL, invalid options)
    """
    options = {
        "max_explanations": request.options.max_explanations,
        "skip_llm":         request.options.skip_llm,
        "github_token":     request.options.github_token
    }
    job_id = store.create(request.repo_url, options)

    # Submit to thread pool.
    # _executor.submit() is non-blocking: returns a Future immediately.
    # The pipeline runs in a worker thread; the response is returned
    # to the client before the pipeline starts.
    _executor.submit(pipeline_runner.run, job_id, request.repo_url, options)

    return SubmitResponse(
        job_id=job_id,
        status="queued",
        message=(
            f"Analysis started for {request.repo_url}. "
            f"Poll GET /jobs/{job_id} to track progress."
        )
    )


@app.get("/jobs/{job_id}", response_model=JobStatusResponse, tags=["Jobs"])
async def get_job_status(job_id: str):
    """
    Get the current status and progress of a job.

    Status values:
      queued   — waiting to start (thread pool may be full)
      running  — pipeline is executing; current_phase shows which agent
      complete — all agents finished; fetch result at /jobs/{job_id}/result
      failed   — pipeline raised an unhandled exception; error field has details

    Poll this endpoint every 3-5 seconds. progress_pct goes from 0 to 100.
    """
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    return JobStatusResponse(
        job_id=job.job_id,
        repo_url=job.repo_url,
        status=job.status,
        current_phase=job.current_phase,
        phases_completed=job.phases_completed,
        progress_pct=job.progress_pct,
        created_at=job.created_at,
        completed_at=job.completed_at,
        error=job.error
    )


@app.get("/jobs/{job_id}/result", response_model=AnalysisResult, tags=["Jobs"])
async def get_job_result(job_id: str):
    """
    Fetch the full analysis result for a completed job.

    Returns 404 if the job does not exist.
    Returns 409 if the job exists but has not completed.
    Returns 500 if the job failed (check /jobs/{job_id} for error details).

    The result includes:
      - onboarding_doc: the full Markdown onboarding document
      - summary: file counts, language breakdown, risk distribution
      - complexity_report: CRITICAL and HIGH risk files with reasons
      - graph_summary: top files by in-degree, reading order
      - explanations: LLM-generated explanations per file
    """
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if job.status == "failed":
        raise HTTPException(
            status_code=500,
            detail=f"Job failed: {job.error}. "
                   f"Check GET /jobs/{job_id} for details."
        )

    if job.status in ("queued", "running"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Job is {job.status} ({job.progress_pct}% complete). "
                f"Poll GET /jobs/{job_id} and retry when status is 'complete'."
            )
        )

    if not job.result:
        raise HTTPException(
            status_code=500,
            detail="Job is marked complete but result is missing. This is a bug."
        )

    return AnalysisResult(**job.result)


@app.delete("/jobs/{job_id}", tags=["Jobs"])
async def delete_job(job_id: str):
    """
    Delete a job from the store.

    Jobs in 'running' status can be deleted from the store but the
    background thread will continue running until it finishes.
    This is a known limitation of the in-memory/thread-pool approach.
    The result will be written to a job that no longer exists in the store
    and will be silently discarded.

    Returns 204 No Content on success.
    Returns 404 if the job does not exist.
    """
    deleted = store.delete(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    return JSONResponse(status_code=204, content=None)


@app.get("/jobs", response_model=JobListResponse, tags=["Jobs"])
async def list_jobs():
    """
    List all jobs in the store.

    Returns lightweight summaries (no result payload).
    Ordered by creation time descending (newest first).
    """
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


# -----------------------------------------------------------------------
# Exception handlers
# -----------------------------------------------------------------------

@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    """
    Catch-all for any exception not caught by route handlers.
    Returns a consistent JSON error format instead of a 500 HTML page.
    """
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal server error",
            detail=str(exc)
        ).model_dump()
    )