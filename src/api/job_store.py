"""
In-memory job store with thread-safe reads and writes.

All job state lives here. The store is a module-level singleton:
importing this module gives you the shared instance.

WHY NOT A DATABASE:
v1 is a single-server development tool. An SQLite or Redis store
adds operational overhead (migrations, connection pooling, startup deps)
that is not justified until there are concurrent users and the requirement
to persist jobs across server restarts. The in-memory store is correct
for the demo use case and upgrading is a 1-file change.

THREAD SAFETY:
Pipeline tasks run in a thread pool (not the async event loop).
Multiple tasks could theoretically write to the store simultaneously.
threading.Lock prevents concurrent writes from corrupting state.
Reads do not acquire the lock — in CPython, dict reads are atomic
at the GIL level, and we accept the risk of slightly stale status
reads in exchange for zero lock contention on the polling path.
"""
import uuid
import threading
from datetime import datetime, timezone
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Job:
    """
    Mutable job record. All mutations go through JobStore methods
    that hold the lock. Direct attribute reads are allowed.
    """
    __slots__ = (
        "job_id", "repo_url", "options",
        "status", "current_phase", "phases_completed",
        "progress_pct", "created_at", "completed_at",
        "error", "result"
    )

    def __init__(self, job_id: str, repo_url: str, options: dict):
        self.job_id           = job_id
        self.repo_url         = repo_url
        self.options          = options
        self.status           = "queued"
        self.current_phase    = None
        self.phases_completed = []
        self.progress_pct     = 0
        self.created_at       = _now_iso()
        self.completed_at     = None
        self.error            = None
        self.result           = None   # set on completion


class JobStore:
    """
    Thread-safe in-memory store for all pipeline jobs.
    """

    def __init__(self):
        self._jobs: dict = {}
        self._lock = threading.Lock()

    # ----------------------------------------------------------------
    # Write operations (acquire lock)
    # ----------------------------------------------------------------

    def create(self, repo_url: str, options: dict) -> str:
        job_id = str(uuid.uuid4())
        job    = Job(job_id, repo_url, options)
        with self._lock:
            self._jobs[job_id] = job
        return job_id

    def start(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = "running"

    def update_phase(self, job_id: str, phase: str, progress_pct: int) -> None:
        """
        Called before an agent starts.
        Sets current_phase so the status endpoint shows what is running.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.current_phase = phase
                job.progress_pct  = progress_pct

    def complete_phase(self, job_id: str, phase: str) -> None:
        """
        Called after an agent returns successfully.
        Appends phase to phases_completed.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job and phase not in job.phases_completed:
                job.phases_completed.append(phase)

    def finish(self, job_id: str, result: dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status        = "complete"
                job.current_phase = None
                job.progress_pct  = 100
                job.completed_at  = _now_iso()
                job.result        = result

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status        = "failed"
                job.current_phase = None
                job.completed_at  = _now_iso()
                job.error         = error

    def delete(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self._jobs:
                del self._jobs[job_id]
                return True
            return False

    # ----------------------------------------------------------------
    # Read operations (no lock — see module docstring)
    # ----------------------------------------------------------------

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list_all(self) -> list:
        return list(self._jobs.values())

    def active_count(self) -> int:
        return sum(
            1 for j in self._jobs.values()
            if j.status in ("queued", "running")
        )


# Module-level singleton — imported by main.py and pipeline_runner.py
store = JobStore()  