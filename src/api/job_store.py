"""
Unified job store supporting Redis (production/distributed) and In-Memory (development/fallback).

All job state lives here. The store is a module-level singleton:
importing this module gives you the shared instance.

STORAGE MODES:
1. Redis Backend:
   When REDIS_URL is provided in the environment (or injected via connect_redis),
   job state is stored in Redis. This enables horizontal scaling across multiple
   FastAPI web instances and dedicated background RQ workers, as well as state
   persistence across container restarts.

2. In-Memory Backend (Fallback):
   When REDIS_URL is not set (or Redis is unreachable), JobStore seamlessly falls
   back to thread-safe local memory storage for zero-dependency local testing.
"""
import os
import json
import uuid
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Job:
    """
    Job record representing the pipeline lifecycle and results.
    """
    __slots__ = (
        "job_id", "repo_url", "options",
        "status", "current_phase", "phases_completed",
        "progress_pct", "created_at", "completed_at",
        "error", "result"
    )

    def __init__(
        self,
        job_id: str,
        repo_url: str,
        options: Optional[dict] = None,
        status: str = "queued",
        current_phase: Optional[str] = None,
        phases_completed: Optional[list] = None,
        progress_pct: int = 0,
        created_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        error: Optional[str] = None,
        result: Optional[dict] = None
    ):
        self.job_id           = job_id
        self.repo_url         = repo_url
        self.options          = options or {}
        self.status           = status
        self.current_phase    = current_phase
        self.phases_completed = phases_completed if phases_completed is not None else []
        self.progress_pct     = progress_pct
        self.created_at       = created_at or _now_iso()
        self.completed_at     = completed_at
        self.error            = error
        self.result           = result   # set on completion

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "repo_url": self.repo_url,
            "options": self.options,
            "status": self.status,
            "current_phase": self.current_phase,
            "phases_completed": self.phases_completed,
            "progress_pct": self.progress_pct,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "result": self.result
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        return cls(
            job_id=data["job_id"],
            repo_url=data["repo_url"],
            options=data.get("options", {}),
            status=data.get("status", "queued"),
            current_phase=data.get("current_phase"),
            phases_completed=data.get("phases_completed", []),
            progress_pct=data.get("progress_pct", 0),
            created_at=data.get("created_at"),
            completed_at=data.get("completed_at"),
            error=data.get("error"),
            result=data.get("result")
        )


class JobStore:
    """
    Unified job store supporting Redis with automatic In-Memory fallback.
    """
    REDIS_KEY_PREFIX = "gnosis:job:"
    REDIS_INDEX_KEY = "gnosis:jobs"

    def __init__(self, redis_url: Optional[str] = None):
        self._lock = threading.Lock()
        self._memory_jobs: Dict[str, Job] = {}
        self._redis_client = None
        self._backend = "memory"

        url = redis_url or os.getenv("REDIS_URL")
        if url:
            self._init_redis(url)

    def _init_redis(self, url: str) -> bool:
        try:
            import redis
            client = redis.Redis.from_url(url, decode_responses=True)
            client.ping()
            self._redis_client = client
            self._backend = "redis"
            logger.info(f"[JobStore] Connected to Redis at {url}")
            return True
        except Exception as exc:
            logger.warning(f"[JobStore] Failed to connect to Redis ({exc}). Falling back to in-memory store.")
            self._redis_client = None
            self._backend = "memory"
            return False

    def connect_redis(self, client) -> None:
        """Inject a Redis or FakeRedis client instance directly."""
        self._redis_client = client
        self._backend = "redis" if client else "memory"

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def is_redis(self) -> bool:
        return self._backend == "redis" and self._redis_client is not None

    def _job_key(self, job_id: str) -> str:
        return f"{self.REDIS_KEY_PREFIX}{job_id}"

    # ----------------------------------------------------------------
    # Write operations
    # ----------------------------------------------------------------

    def create(self, repo_url: str, options: dict, job_id: Optional[str] = None) -> str:
        job_id = job_id or str(uuid.uuid4())
        job = Job(job_id, repo_url, options)

        if self.is_redis:
            try:
                raw_json = json.dumps(job.to_dict())
                pipe = self._redis_client.pipeline()
                pipe.set(self._job_key(job_id), raw_json)
                pipe.sadd(self.REDIS_INDEX_KEY, job_id)
                pipe.execute()
                return job_id
            except Exception as exc:
                logger.error(f"[JobStore] Redis create failed ({exc}), falling back to memory.")

        with self._lock:
            self._memory_jobs[job_id] = job
        return job_id

    def start(self, job_id: str) -> None:
        if self.is_redis:
            try:
                job = self.get(job_id)
                if job:
                    job.status = "running"
                    self._redis_client.set(self._job_key(job_id), json.dumps(job.to_dict()))
                return
            except Exception as exc:
                logger.error(f"[JobStore] Redis start failed ({exc}).")

        with self._lock:
            job = self._memory_jobs.get(job_id)
            if job:
                job.status = "running"

    def update_phase(self, job_id: str, phase: str, progress_pct: int) -> None:
        if self.is_redis:
            try:
                job = self.get(job_id)
                if job:
                    job.current_phase = phase
                    job.progress_pct = progress_pct
                    self._redis_client.set(self._job_key(job_id), json.dumps(job.to_dict()))
                return
            except Exception as exc:
                logger.error(f"[JobStore] Redis update_phase failed ({exc}).")

        with self._lock:
            job = self._memory_jobs.get(job_id)
            if job:
                job.current_phase = phase
                job.progress_pct = progress_pct

    def complete_phase(self, job_id: str, phase: str) -> None:
        if self.is_redis:
            try:
                job = self.get(job_id)
                if job and phase not in job.phases_completed:
                    job.phases_completed.append(phase)
                    self._redis_client.set(self._job_key(job_id), json.dumps(job.to_dict()))
                return
            except Exception as exc:
                logger.error(f"[JobStore] Redis complete_phase failed ({exc}).")

        with self._lock:
            job = self._memory_jobs.get(job_id)
            if job and phase not in job.phases_completed:
                job.phases_completed.append(phase)

    def finish(self, job_id: str, result: dict) -> None:
        if self.is_redis:
            try:
                job = self.get(job_id)
                if job:
                    job.status = "complete"
                    job.current_phase = None
                    job.progress_pct = 100
                    job.completed_at = _now_iso()
                    job.result = result
                    # Optional TTL can be set on complete jobs via environment
                    ttl = int(os.getenv("JOB_TTL_SECONDS", 0))
                    raw_json = json.dumps(job.to_dict())
                    if ttl > 0:
                        self._redis_client.setex(self._job_key(job_id), ttl, raw_json)
                    else:
                        self._redis_client.set(self._job_key(job_id), raw_json)
                return
            except Exception as exc:
                logger.error(f"[JobStore] Redis finish failed ({exc}).")

        with self._lock:
            job = self._memory_jobs.get(job_id)
            if job:
                job.status = "complete"
                job.current_phase = None
                job.progress_pct = 100
                job.completed_at = _now_iso()
                job.result = result

    def fail(self, job_id: str, error: str) -> None:
        if self.is_redis:
            try:
                job = self.get(job_id)
                if job:
                    job.status = "failed"
                    job.current_phase = None
                    job.completed_at = _now_iso()
                    job.error = error
                    self._redis_client.set(self._job_key(job_id), json.dumps(job.to_dict()))
                return
            except Exception as exc:
                logger.error(f"[JobStore] Redis fail failed ({exc}).")

        with self._lock:
            job = self._memory_jobs.get(job_id)
            if job:
                job.status = "failed"
                job.current_phase = None
                job.completed_at = _now_iso()
                job.error = error

    def delete(self, job_id: str) -> bool:
        if self.is_redis:
            try:
                pipe = self._redis_client.pipeline()
                pipe.delete(self._job_key(job_id))
                pipe.srem(self.REDIS_INDEX_KEY, job_id)
                res = pipe.execute()
                return bool(res[0] > 0 or res[1] > 0)
            except Exception as exc:
                logger.error(f"[JobStore] Redis delete failed ({exc}).")

        with self._lock:
            if job_id in self._memory_jobs:
                del self._memory_jobs[job_id]
                return True
            return False

    def clear(self) -> None:
        if self.is_redis:
            try:
                job_ids = self._redis_client.smembers(self.REDIS_INDEX_KEY)
                if job_ids:
                    keys = [self._job_key(jid) for jid in job_ids]
                    keys.append(self.REDIS_INDEX_KEY)
                    self._redis_client.delete(*keys)
                else:
                    self._redis_client.delete(self.REDIS_INDEX_KEY)
            except Exception as exc:
                logger.error(f"[JobStore] Redis clear failed ({exc}).")

        with self._lock:
            self._memory_jobs.clear()

    # ----------------------------------------------------------------
    # Read operations
    # ----------------------------------------------------------------

    def get(self, job_id: str) -> Optional[Job]:
        if self.is_redis:
            try:
                raw_json = self._redis_client.get(self._job_key(job_id))
                if raw_json:
                    data = json.loads(raw_json)
                    return Job.from_dict(data)
                return None
            except Exception as exc:
                logger.error(f"[JobStore] Redis get failed ({exc}).")

        return self._memory_jobs.get(job_id)

    def list_all(self) -> List[Job]:
        if self.is_redis:
            try:
                job_ids = list(self._redis_client.smembers(self.REDIS_INDEX_KEY))
                if not job_ids:
                    return []
                keys = [self._job_key(jid) for jid in job_ids]
                raw_items = self._redis_client.mget(keys)
                jobs = []
                for item in raw_items:
                    if item:
                        try:
                            jobs.append(Job.from_dict(json.loads(item)))
                        except Exception:
                            pass
                return jobs
            except Exception as exc:
                logger.error(f"[JobStore] Redis list_all failed ({exc}).")

        return list(self._memory_jobs.values())

    def active_count(self) -> int:
        return sum(
            1 for j in self.list_all()
            if j.status in ("queued", "running")
        )


# Module-level singleton — imported by main.py, queue.py, pipeline_runner.py, and worker.py
store = JobStore()