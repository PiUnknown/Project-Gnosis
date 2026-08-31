# ============================================================
# COPY THIS FILE TO: src/api/main.py
# (replaces or merges with your existing FastAPI app)
# ============================================================

import uuid
import threading
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Adjust these imports to match your actual module paths
from src.state import ArchaeonState
from src.orchestrator import run_pipeline   # or wherever your pipeline runner lives


app = FastAPI(title="Project Gnosis API", version="1.0.4")

# ── CORS (dev only — Vite runs on 5173) ─────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory job store ──────────────────────────────────────────────────────
# Maps job_id → { status, agents, result, error }
# For production, replace with Redis or a database.
jobs: dict = {}

AGENT_IDS   = ["01", "02", "03", "04", "05", "06", "07"]
AGENT_NAMES = [
    "INGESTION",
    "AST PARSER",
    "DEPENDENCY GRAPH",
    "COMPLEXITY SCORER",
    "CODE RAG",
    "EXPLAINABILITY",
    "DOC GENERATOR",
]


# ── Request / Response models ────────────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    repo_url: str
    max_explanations: int = 20
    skip_llm: bool = False


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    """Submit a repo for analysis. Returns job_id immediately."""
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "running",
        "agents": [
            {"id": AGENT_IDS[i], "name": AGENT_NAMES[i], "status": "queued"}
            for i in range(7)
        ],
        "result": None,
        "error": None,
    }
    # Mark first agent as running immediately so the UI shows activity
    jobs[job_id]["agents"][0]["status"] = "running"

    thread = threading.Thread(
        target=_run_pipeline_thread,
        args=(job_id, req),
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    """Poll for pipeline progress. Frontend calls this every 1.5s."""
    return jobs.get(job_id, {"error": "job not found"})


@app.get("/api/jobs/{job_id}/result")
def get_result(job_id: str):
    """Fetch the full result once status === 'complete'."""
    job = jobs.get(job_id)
    if not job:
        return {"error": "job not found"}
    if job["status"] != "complete":
        return {"error": "not ready", "status": job["status"]}
    return job["result"]


# ── Pipeline runner (background thread) ──────────────────────────────────────

def _run_pipeline_thread(job_id: str, req: AnalyzeRequest):
    """
    Calls your existing run_pipeline() and updates job state as each
    agent completes. Zero changes to your agent code required.
    """
    def on_agent_complete(agent_index: int):
        """Called by run_pipeline after each agent finishes."""
        jobs[job_id]["agents"][agent_index]["status"] = "complete"
        if agent_index + 1 < 7:
            jobs[job_id]["agents"][agent_index + 1]["status"] = "running"

    try:
        state = ArchaeonState(repo_url=req.repo_url)

        # Pass the callback — see orchestrator_patch.py for the 5-line change
        run_pipeline(state, on_agent_complete=on_agent_complete)

        jobs[job_id]["status"] = "complete"
        jobs[job_id]["result"] = _serialize_state(state)

    except Exception as exc:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(exc)
        # Mark any running agent as failed
        for agent in jobs[job_id]["agents"]:
            if agent["status"] == "running":
                agent["status"] = "failed"


def _serialize_state(state: ArchaeonState) -> dict:
    """
    Converts ArchaeonState into the JSON shape the React frontend expects.
    Matches the AnalysisResult interface in App.tsx exactly.
    """
    try:
        import networkx as nx
    except ImportError:
        nx = None

    # ── Dependency table rows ─────────────────────────────────────────────
    dep_rows = []
    if state.dependency_graph and nx:
        for node in state.dependency_graph.nodes():
            scores = state.complexity_scores.get(node, {})
            dep_rows.append({
                "file": Path(node).name,
                "path": node,
                "imported_by": state.dependency_graph.in_degree(node),
                "imports": state.dependency_graph.out_degree(node),
                "risk": scores.get("risk_level", "LOW"),
            })
        dep_rows.sort(key=lambda r: r["imported_by"], reverse=True)

    # ── Complexity table rows ─────────────────────────────────────────────
    complexity_rows = []
    for path, scores in (state.complexity_scores or {}).items():
        flags = []
        if scores.get("parse_error"):
            flags.append("⚠ PARSE ERROR")
        if path in [str(n) for cycle in (state.circular_deps or []) for n in cycle]:
            flags.append("↻ CYCLE")
        complexity_rows.append({
            "file": Path(path).name,
            "path": path,
            "risk": scores.get("risk_level", "LOW"),
            "avg_cc": round(scores.get("avg_complexity", 0), 1),
            "max_cc": scores.get("max_complexity", 0),
            "worst_fn": scores.get("worst_function", ""),
            "coupling": scores.get("coupling", 0),
            "flags": flags,
        })
        # Sort CRITICAL first
        _order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        complexity_rows.sort(key=lambda r: _order.get(r["risk"], 4))

    # ── Stats ─────────────────────────────────────────────────────────────
    total_files = len(state.file_manifest or [])
    total_functions = sum(
        len(v.get("functions", []))
        for v in (state.symbol_tables or {}).values()
    )
    total_classes = sum(
        len(v.get("classes", []))
        for v in (state.symbol_tables or {}).values()
    )
    import_edges = (
        state.dependency_graph.number_of_edges()
        if state.dependency_graph and nx
        else 0
    )

    # ── Risk distribution ─────────────────────────────────────────────────
    risk_dist: dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for scores in (state.complexity_scores or {}).values():
        level = scores.get("risk_level", "LOW")
        risk_dist[level] = risk_dist.get(level, 0) + 1

    # ── Topological reading order ─────────────────────────────────────────
    reading_order = []
    if state.dependency_graph and nx:
        try:
            reading_order = list(nx.topological_sort(state.dependency_graph))
        except nx.NetworkXUnfeasible:
            reading_order = list(state.dependency_graph.nodes())
    reading_order = reading_order[:15]  # first 15 files

    return {
        "summary": {
            "repo_url": state.repo_url,
            "total_files": total_files,
            "total_functions": total_functions,
            "total_classes": total_classes,
            "import_edges": import_edges,
            "circular_cycles": len(state.circular_deps or []),
            "explained": len(state.explanations or {}),
            "risk_distribution": risk_dist,
        },
        "onboarding_doc": state.final_doc or "",
        "agent_context": getattr(state, "agent_context", getattr(state, "agent_context_md", "")) or "",
        "dependency_rows": dep_rows[:10],
        "reading_order": reading_order,
        "complexity_rows": complexity_rows,
        "explanations": state.explanations or {},
        "complexity_report_json": state.complexity_report_json or "{}",
        "circular_deps": [list(c) for c in (state.circular_deps or [])],
    }


# ── Production: serve built frontend ─────────────────────────────────────────
# After running `cd frontend && npm run build`, uncomment this line.
# It must come AFTER all /api routes so API routes take priority.
#
# app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")
