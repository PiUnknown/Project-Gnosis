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

# WATCH/MULTI retry budget for contended transitions. Exhaustion is handled
# explicitly (log + no mutation, or raise for migration), never by silently
# falling through to the in-memory store.
WATCH_MAX_ATTEMPTS = 5

# Completed/failed records expire after this many seconds by default so the
# Redis keyspace (and the Upstash command budget) stays bounded. Set
# JOB_TTL_SECONDS=0 to keep records forever.
DEFAULT_JOB_TTL_SECONDS = 86400

# Reserved member used only by the operator-run migration to mark the active
# index as initialized. It is never added by create/start or by health reads.
ACTIVE_INDEX_SENTINEL = "__gnosis_active_index_v1__"

_TERMINAL_STATUSES = ("complete", "failed")

try:
    from redis.exceptions import WatchError as _WatchError
except Exception:  # pragma: no cover - redis is an install-time dependency
    class _WatchError(Exception):  # type: ignore[no-redef]
        """Fallback when redis is unavailable (memory-only imports)."""


class ActiveIndexReconcileError(RuntimeError):
    """Raised when the active-index reconciliation cannot complete safely."""


class BackendUnavailableError(RuntimeError):
    """Raised when the configured Redis backend cannot persist a write.

    Never silently fall through to the in-memory store: that would make the
    API report a different backend's state than the queue workers read.
    """


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
        "error", "result", "explanations_completed", "explanations_total",
        "explanations_failed", "explanation_error"
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
        result: Optional[dict] = None,
        explanations_completed: int = 0,
        explanations_total: int = 0,
        explanations_failed: int = 0,
        explanation_error: Optional[str] = None
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
        self.explanations_completed = max(0, int(explanations_completed or 0))
        self.explanations_total = max(0, int(explanations_total or 0))
        self.explanations_failed = max(0, int(explanations_failed or 0))
        self.explanation_error = explanation_error

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
            "result": self.result,
            "explanations_completed": self.explanations_completed,
            "explanations_total": self.explanations_total,
            "explanations_failed": self.explanations_failed,
            "explanation_error": self.explanation_error
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
            result=data.get("result"),
            explanations_completed=data.get("explanations_completed", 0),
            explanations_total=data.get("explanations_total", 0),
            explanations_failed=data.get("explanations_failed", 0),
            explanation_error=data.get("explanation_error")
        )


class JobStore:
    """
    Unified job store supporting Redis with automatic In-Memory fallback.
    """
    REDIS_KEY_PREFIX = "gnosis:job:"
    REDIS_INDEX_KEY = "gnosis:jobs"
    REDIS_ACTIVE_KEY = "gnosis:jobs:active"

    def __init__(self, redis_url: Optional[str] = None):
        self._lock = threading.Lock()
        self._memory_jobs: Dict[str, Job] = {}
        self._redis_client = None
        self._backend = "memory"
        self._redis_configured = False

        url = redis_url or os.getenv("REDIS_URL")
        if url:
            self._redis_configured = True
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
        if client:
            self._redis_configured = True

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def is_redis(self) -> bool:
        return self._backend == "redis" and self._redis_client is not None

    @property
    def redis_client(self):
        """The shared Redis client, or None when the backend is in-memory."""
        return self._redis_client if self.is_redis else None

    @property
    def redis_configured(self) -> bool:
        """True when a Redis URL (or client) was configured for this store."""
        return self._redis_configured

    @property
    def degraded(self) -> bool:
        """True when Redis was configured but the store fell back to memory."""
        return self._redis_configured and not self.is_redis

    def _job_key(self, job_id: str) -> str:
        return f"{self.REDIS_KEY_PREFIX}{job_id}"

    @staticmethod
    def _job_ttl_seconds() -> int:
        """TTL applied to terminal job records (0 disables expiry)."""
        raw = (os.getenv("JOB_TTL_SECONDS") or "").strip()
        if not raw:
            return DEFAULT_JOB_TTL_SECONDS
        try:
            return max(0, int(raw))
        except ValueError:
            logger.warning(
                f"[JobStore] Invalid JOB_TTL_SECONDS={raw!r}; "
                f"using default {DEFAULT_JOB_TTL_SECONDS}s."
            )
            return DEFAULT_JOB_TTL_SECONDS

    # ----------------------------------------------------------------
    # Write operations
    # ----------------------------------------------------------------

    def create(self, repo_url: str, options: dict, job_id: Optional[str] = None) -> str:
        job_id = job_id or str(uuid.uuid4())
        if job_id == ACTIVE_INDEX_SENTINEL:
            raise ValueError("reserved job_id")
        job = Job(job_id, repo_url, options)

        if self.is_redis:
            try:
                raw_json = json.dumps(job.to_dict())
                pipe = self._redis_client.pipeline()
                pipe.set(self._job_key(job_id), raw_json)
                pipe.sadd(self.REDIS_INDEX_KEY, job_id)
                pipe.sadd(self.REDIS_ACTIVE_KEY, job_id)
                pipe.execute()
                return job_id
            except Exception as exc:
                # Never fall through to memory while the queue may still be
                # dispatching against Redis: the job the worker updates would
                # not be the job the API later polls.
                logger.error(f"[JobStore] Redis create failed ({exc}).")
                raise BackendUnavailableError(
                    f"could not persist job {job_id} to Redis: {exc}"
                ) from exc

        with self._lock:
            self._memory_jobs[job_id] = job
        return job_id

    def start(self, job_id: str) -> None:
        if self.is_redis:
            if job_id == ACTIVE_INDEX_SENTINEL:
                logger.error("[JobStore] Refusing to start reserved active-index sentinel id.")
                return

            key = self._job_key(job_id)
            for _ in range(WATCH_MAX_ATTEMPTS):
                pipe = None
                try:
                    pipe = self._redis_client.pipeline()
                    pipe.watch(key, self.REDIS_INDEX_KEY)
                    raw_json = pipe.get(key)
                    indexed = pipe.sismember(self.REDIS_INDEX_KEY, job_id)
                    if raw_json is None or not indexed:
                        # The record was deleted (or removed from the index)
                        # between the caller's read and this write. Never
                        # recreate it and never re-add it to the active set.
                        pipe.unwatch()
                        return

                    job = Job.from_dict(json.loads(raw_json))
                    job.status = "running"
                    pipe.multi()
                    pipe.set(key, json.dumps(job.to_dict()))
                    pipe.sadd(self.REDIS_ACTIVE_KEY, job_id)
                    pipe.execute()
                    return
                except _WatchError:
                    continue
                except Exception as exc:
                    # Do not fall through to the memory store: that would
                    # silently report a different backend's state.
                    logger.error(f"[JobStore] Redis start failed ({exc}); record left unchanged.")
                    return
                finally:
                    if pipe is not None:
                        try:
                            pipe.reset()
                        except Exception:
                            pass

            logger.error(
                f"[JobStore] Redis start aborted for job {job_id} after "
                f"{WATCH_MAX_ATTEMPTS} contention retries; record left unchanged."
            )
            return

        with self._lock:
            job = self._memory_jobs.get(job_id)
            if job:
                job.status = "running"

    def _mutate_redis_job(self, job_id: str, mutator, operation: str) -> bool:
        """Atomically mutate a non-terminal job record, or leave it untouched.

        Missing and terminal records are never rewritten. Returns True when a
        write was committed. Contention is retried a bounded number of times.
        Exhaustion and Redis errors are logged and return False; this path never
        falls back to the in-memory store.
        """
        key = self._job_key(job_id)
        for _ in range(WATCH_MAX_ATTEMPTS):
            pipe = None
            try:
                pipe = self._redis_client.pipeline()
                pipe.watch(key)
                raw_json = pipe.get(key)
                if raw_json is None:
                    pipe.unwatch()
                    return False

                job = Job.from_dict(json.loads(raw_json))
                if job.status in _TERMINAL_STATUSES:
                    pipe.unwatch()
                    return False

                if mutator(job) is False:
                    pipe.unwatch()
                    return False

                pipe.multi()
                pipe.set(key, json.dumps(job.to_dict()))
                pipe.execute()
                return True
            except _WatchError:
                continue
            except Exception as exc:
                logger.error(f"[JobStore] Redis {operation} failed ({exc}); record left unchanged.")
                return False
            finally:
                if pipe is not None:
                    try:
                        pipe.reset()
                    except Exception:
                        pass

        logger.error(
            f"[JobStore] Redis {operation} aborted for job {job_id} after "
            f"{WATCH_MAX_ATTEMPTS} contention retries; record left unchanged."
        )
        return False

    def update_phase(self, job_id: str, phase: str, progress_pct: int) -> None:
        if self.is_redis:
            def mutate(job: Job) -> bool:
                job.current_phase = phase
                job.progress_pct = progress_pct
                return True

            self._mutate_redis_job(job_id, mutate, "update_phase")
            return

        with self._lock:
            job = self._memory_jobs.get(job_id)
            if job:
                job.current_phase = phase
                job.progress_pct = progress_pct

    def complete_phase(self, job_id: str, phase: str) -> None:
        if self.is_redis:
            def mutate(job: Job) -> bool:
                if phase in job.phases_completed:
                    return False
                job.phases_completed.append(phase)
                return True

            self._mutate_redis_job(job_id, mutate, "complete_phase")
            return

        with self._lock:
            job = self._memory_jobs.get(job_id)
            if job and phase not in job.phases_completed:
                job.phases_completed.append(phase)

    def finish(self, job_id: str, result: dict) -> None:
        if self.is_redis:
            active_member = None if job_id == ACTIVE_INDEX_SENTINEL else job_id
            try:
                job = self.get(job_id)
                if job:
                    job.status = "complete"
                    job.current_phase = None
                    job.progress_pct = 100
                    job.completed_at = _now_iso()
                    job.result = result
                    job.options.pop("github_token_encrypted", None)
                    job.options.pop("github_token", None)
                    # Terminal records expire so the index cannot grow forever.
                    ttl = self._job_ttl_seconds()
                    raw_json = json.dumps(job.to_dict())
                    pipe = self._redis_client.pipeline()
                    if ttl > 0:
                        # Same expiry semantics as before; SET ... EX avoids a
                        # deprecated setex wrapper in current client versions.
                        pipe.set(self._job_key(job_id), raw_json, ex=ttl)
                    else:
                        pipe.set(self._job_key(job_id), raw_json)
                    if active_member is not None:
                        pipe.srem(self.REDIS_ACTIVE_KEY, active_member)
                    pipe.execute()
                elif active_member is not None:
                    # Record vanished (TTL/eviction/delete): drop any stale
                    # active membership instead of leaving an overcount.
                    self._redis_client.srem(self.REDIS_ACTIVE_KEY, active_member)
                return
            except Exception as exc:
                # Do not fall through to the memory store: the Redis record is
                # the only one the queue/worker path can see.
                logger.error(f"[JobStore] Redis finish failed ({exc}); record left unchanged.")
                return

        with self._lock:
            job = self._memory_jobs.get(job_id)
            if job:
                job.status = "complete"
                job.current_phase = None
                job.progress_pct = 100
                job.completed_at = _now_iso()
                job.result = result
                job.options.pop("github_token_encrypted", None)
                job.options.pop("github_token", None)

    def fail(self, job_id: str, error: str) -> None:
        if self.is_redis:
            active_member = None if job_id == ACTIVE_INDEX_SENTINEL else job_id
            try:
                job = self.get(job_id)
                if job:
                    job.status = "failed"
                    job.current_phase = None
                    job.completed_at = _now_iso()
                    job.error = error
                    job.options.pop("github_token_encrypted", None)
                    job.options.pop("github_token", None)
                    ttl = self._job_ttl_seconds()
                    pipe = self._redis_client.pipeline()
                    if ttl > 0:
                        pipe.set(self._job_key(job_id), json.dumps(job.to_dict()), ex=ttl)
                    else:
                        pipe.set(self._job_key(job_id), json.dumps(job.to_dict()))
                    if active_member is not None:
                        pipe.srem(self.REDIS_ACTIVE_KEY, active_member)
                    pipe.execute()
                elif active_member is not None:
                    self._redis_client.srem(self.REDIS_ACTIVE_KEY, active_member)
                return
            except Exception as exc:
                logger.error(f"[JobStore] Redis fail failed ({exc}); record left unchanged.")
                return

        with self._lock:
            job = self._memory_jobs.get(job_id)
            if job:
                job.status = "failed"
                job.current_phase = None
                job.completed_at = _now_iso()
                job.error = error
                job.options.pop("github_token_encrypted", None)
                job.options.pop("github_token", None)

    def delete(self, job_id: str) -> bool:
        if self.is_redis:
            try:
                pipe = self._redis_client.pipeline()
                pipe.delete(self._job_key(job_id))
                pipe.srem(self.REDIS_INDEX_KEY, job_id)
                if job_id != ACTIVE_INDEX_SENTINEL:
                    pipe.srem(self.REDIS_ACTIVE_KEY, job_id)
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
                    keys.append(self.REDIS_ACTIVE_KEY)
                    self._redis_client.delete(*keys)
                else:
                    # Deleting the active set also removes the init sentinel:
                    # after a clear the fast path is uninitialized until a
                    # fresh reconciliation is armed.
                    self._redis_client.delete(self.REDIS_INDEX_KEY, self.REDIS_ACTIVE_KEY)
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

    def _prune_stale_ids(self, job_ids: List[str]) -> None:
        """Drop expired/missing ids from the index and active sets (best effort)."""
        removable = [jid for jid in job_ids if jid != ACTIVE_INDEX_SENTINEL]
        if not removable:
            return
        try:
            pipe = self._redis_client.pipeline()
            pipe.srem(self.REDIS_INDEX_KEY, *removable)
            pipe.srem(self.REDIS_ACTIVE_KEY, *removable)
            pipe.execute()
        except Exception as exc:
            logger.warning(f"[JobStore] Could not prune stale job ids ({exc}).")

    def list_all(self) -> List[Job]:
        if self.is_redis:
            try:
                job_ids = list(self._redis_client.smembers(self.REDIS_INDEX_KEY))
                if not job_ids:
                    return []
                keys = [self._job_key(jid) for jid in job_ids]
                raw_items = self._redis_client.mget(keys)
                jobs = []
                stale_ids = []
                for job_id, item in zip(job_ids, raw_items):
                    if not item:
                        # Expired (JOB_TTL_SECONDS) or removed: stop paying
                        # for its index membership on every read.
                        stale_ids.append(job_id)
                        continue
                    try:
                        jobs.append(Job.from_dict(json.loads(item)))
                    except Exception:
                        pass
                if stale_ids:
                    self._prune_stale_ids(stale_ids)
                return jobs
            except Exception as exc:
                logger.error(f"[JobStore] Redis list_all failed ({exc}).")

        return list(self._memory_jobs.values())

    @staticmethod
    def _canonical_repo_url(repo_url: str) -> str:
        value = (repo_url or "").strip().rstrip("/").lower()
        if value.endswith(".git"):
            value = value[:-4]
        return value

    def find_active_by_repo(self, repo_url: str) -> Optional[Job]:
        """Find an active job without deserializing completed job results.

        The Redis active set is only authoritative after its migration sentinel
        has been armed. Before that point, retain the legacy scan so a deploy
        cannot miss an older active job and enqueue a duplicate.
        """
        target = self._canonical_repo_url(repo_url)

        if self.is_redis:
            try:
                pipe = self._redis_client.pipeline()
                pipe.sismember(self.REDIS_ACTIVE_KEY, ACTIVE_INDEX_SENTINEL)
                pipe.smembers(self.REDIS_ACTIVE_KEY)
                armed, members = pipe.execute()

                if not armed:
                    return next(
                        (
                            job for job in self.list_all()
                            if job.status in ("queued", "running")
                            and self._canonical_repo_url(job.repo_url) == target
                        ),
                        None,
                    )

                job_ids = [
                    member for member in members
                    if member != ACTIVE_INDEX_SENTINEL
                ]
                if not job_ids:
                    return None

                raw_items = self._redis_client.mget(
                    [self._job_key(job_id) for job_id in job_ids]
                )
                for raw_json in raw_items:
                    if not raw_json:
                        continue
                    try:
                        job = Job.from_dict(json.loads(raw_json))
                    except Exception:
                        continue
                    if (
                        job.status in ("queued", "running")
                        and self._canonical_repo_url(job.repo_url) == target
                    ):
                        return job
                return None
            except Exception as exc:
                logger.error(
                    f"[JobStore] Redis active repo lookup failed ({exc}); "
                    "trying legacy lookup."
                )
                try:
                    return next(
                        (
                            job for job in self.list_all()
                            if job.status in ("queued", "running")
                            and self._canonical_repo_url(job.repo_url) == target
                        ),
                        None,
                    )
                except Exception as legacy_exc:
                    logger.error(
                        f"[JobStore] Legacy active repo lookup failed ({legacy_exc})."
                    )
                    return None

        with self._lock:
            return next(
                (
                    job for job in self._memory_jobs.values()
                    if job.status in ("queued", "running")
                    and self._canonical_repo_url(job.repo_url) == target
                ),
                None,
            )

    def update_explanation_progress(self, job_id: str, completed: int, total: int) -> None:
        completed = max(0, int(completed))
        total = max(0, int(total))
        completed = min(completed, total) if total else 0

        if self.is_redis:
            def mutate(job: Job) -> bool:
                job.explanations_completed = completed
                job.explanations_total = total
                return True

            self._mutate_redis_job(job_id, mutate, "update_explanation_progress")
            return

        with self._lock:
            job = self._memory_jobs.get(job_id)
            if job:
                job.explanations_completed = completed
                job.explanations_total = total

    def set_explanation_outcome(
        self,
        job_id: str,
        completed: int,
        total: int,
        failed: int,
        error: Optional[str],
    ) -> None:
        """
        Persist the final explainability result for a job.

        Written after the agent finishes because the failure count is only
        known then. Without it, a job whose explanations all failed still
        reports `explanations_completed == explanations_total`.
        """
        completed = max(0, int(completed or 0))
        total = max(0, int(total or 0))
        failed = max(0, int(failed or 0))

        if self.is_redis:
            def mutate(job: Job) -> bool:
                job.explanations_completed = completed
                job.explanations_total = total
                job.explanations_failed = failed
                job.explanation_error = error
                return True

            self._mutate_redis_job(job_id, mutate, "set_explanation_outcome")
            return

        with self._lock:
            job = self._memory_jobs.get(job_id)
            if job:
                job.explanations_completed = completed
                job.explanations_total = total
                job.explanations_failed = failed
                job.explanation_error = error

    def _legacy_active_count(self) -> int:
        """Exact pre-index implementation; used until the fast path is armed."""
        return sum(
            1 for j in self.list_all()
            if j.status in ("queued", "running")
        )

    def active_count(self) -> int:
        if self.is_redis:
            try:
                # One atomic read: sentinel presence and cardinality must be
                # observed together. The sentinel is a member of the set, so
                # set eviction cannot leave an "armed" marker behind.
                pipe = self._redis_client.pipeline()
                pipe.sismember(self.REDIS_ACTIVE_KEY, ACTIVE_INDEX_SENTINEL)
                pipe.scard(self.REDIS_ACTIVE_KEY)
                armed, cardinality = pipe.execute()
                if armed:
                    return max(0, int(cardinality) - 1)
                # Missing/evicted/never-armed index: fall back to the legacy
                # full read. Never write here (no runtime backfill).
                return self._legacy_active_count()
            except Exception as exc:
                logger.error(f"[JobStore] Redis active_count failed ({exc}); trying legacy path.")
                try:
                    return self._legacy_active_count()
                except Exception as legacy_exc:
                    logger.error(
                        f"[JobStore] Redis legacy active_count failed ({legacy_exc})."
                    )
                # Preserve the original in-memory fallback when both Redis
                # read paths fail.

        return sum(
            1 for j in self._memory_jobs.values()
            if j.status in ("queued", "running")
        )

    # ----------------------------------------------------------------
    # Active-index reconciliation (operator-run; never on the health path)
    # ----------------------------------------------------------------

    def _sscan_members(self, key: str, batch_size: int):
        cursor = 0
        while True:
            cursor, batch = self._redis_client.sscan(key, cursor=cursor, count=batch_size)
            for member in batch:
                yield member
            if int(cursor) == 0:
                return

    def _reconcile_active_member(self, job_id: str) -> bool:
        """Atomically validate the record and index before changing membership.

        Returns True when the job is active. Raises ActiveIndexReconcileError
        after bounded contention or on any Redis error so a failed pass cannot
        be mistaken for a successful one. The sentinel is never touched.
        """
        if not self.is_redis:
            raise ActiveIndexReconcileError("active-index reconciliation requires the Redis backend")
        if job_id == ACTIVE_INDEX_SENTINEL:
            return True

        key = self._job_key(job_id)
        for _ in range(WATCH_MAX_ATTEMPTS):
            pipe = None
            try:
                pipe = self._redis_client.pipeline()
                pipe.watch(key, self.REDIS_INDEX_KEY)
                raw_json = pipe.get(key)
                indexed = pipe.sismember(self.REDIS_INDEX_KEY, job_id)

                is_active = False
                if raw_json is not None and indexed:
                    try:
                        job = Job.from_dict(json.loads(raw_json))
                    except Exception:
                        job = None
                    if job is not None:
                        is_active = job.status in ("queued", "running")

                pipe.multi()
                if is_active:
                    pipe.sadd(self.REDIS_ACTIVE_KEY, job_id)
                else:
                    pipe.srem(self.REDIS_ACTIVE_KEY, job_id)
                pipe.execute()
                return is_active
            except _WatchError:
                continue
            except Exception as exc:
                raise ActiveIndexReconcileError(
                    f"reconciliation failed for job {job_id}: {exc}"
                ) from exc
            finally:
                if pipe is not None:
                    try:
                        pipe.reset()
                    except Exception:
                        pass

        raise ActiveIndexReconcileError(
            f"reconciliation contention for job {job_id} after "
            f"{WATCH_MAX_ATTEMPTS} attempts"
        )

    def rebuild_active_index(self, batch_size: int = 500, arm: bool = False) -> Dict[str, int]:
        """Converge the active set against live records and index membership.

        This is a per-job atomic reconciliation, not a snapshot/RENAME: writes
        that happen between steps are either seen by a later step or already
        maintained by their own transition. It never removes the sentinel.
        `arm=True` adds the sentinel only after both scans complete cleanly.
        """
        if not self.is_redis:
            raise ActiveIndexReconcileError("active-index reconciliation requires the Redis backend")
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")

        stats = {
            "index_scanned": 0,
            "active_scanned": 0,
            "reconciled": 0,
            "armed": 0,
        }

        for job_id in self._sscan_members(self.REDIS_INDEX_KEY, batch_size):
            stats["index_scanned"] += 1
            self._reconcile_active_member(job_id)
            stats["reconciled"] += 1

        for member in self._sscan_members(self.REDIS_ACTIVE_KEY, batch_size):
            if member == ACTIVE_INDEX_SENTINEL:
                continue
            stats["active_scanned"] += 1
            self._reconcile_active_member(member)
            stats["reconciled"] += 1

        if arm:
            # Only the operator-run migration reaches this line. A normal
            # create/start can never mark a partial index as initialized.
            self._redis_client.sadd(self.REDIS_ACTIVE_KEY, ACTIVE_INDEX_SENTINEL)
            stats["armed"] = 1
        else:
            stats["armed"] = int(
                bool(self._redis_client.sismember(self.REDIS_ACTIVE_KEY, ACTIVE_INDEX_SENTINEL))
            )

        return stats


# Module-level singleton — imported by main.py, queue.py, pipeline_runner.py, and worker.py
store = JobStore()
