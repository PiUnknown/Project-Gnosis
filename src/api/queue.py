"""
Task Queue management for Project Gnosis.

Handles job enqueuing to Redis Queue (RQ) for distributed execution across worker
processes, with graceful fallback to a local thread pool executor when Redis is not configured.

Backend consistency: a job is dispatched on the same backend that persisted it.
The shared JobStore is the single source of truth — this module never opens its
own Redis connection to decide whether execution should be distributed. A job
stored in Redis is enqueued to RQ; a job stored in degraded/local memory runs in
the in-process thread pool. If a Redis-backed job cannot be enqueued, the error
is surfaced instead of silently running it in a process the API cannot see.
"""
import os
import logging
import concurrent.futures
import threading
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Fallback in-process thread pool executor for local/testing mode
_local_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
_local_futures: dict[str, concurrent.futures.Future] = {}
_local_futures_lock = threading.Lock()

DEFAULT_QUEUE_NAME = "gnosis_jobs"
DEFAULT_JOB_TIMEOUT = 1800  # 30 minutes


class QueueDispatchError(RuntimeError):
    """Raised when a Redis-backed job cannot be dispatched to its RQ queue."""


def _resolve_store(store=None):
    """Return the supplied store or the shared JobStore singleton."""
    if store is not None:
        return store
    from src.api.job_store import store as default_store
    return default_store


def get_redis_connection():
    """
    Returns a Redis connection instance if REDIS_URL is configured and reachable.

    Kept for diagnostics and direct RQ tooling. Job dispatch must not use this
    to decide its backend; it derives that from the shared JobStore instead.
    """
    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if not redis_url or not any(redis_url.startswith(scheme) for scheme in ("redis://", "rediss://", "unix://")):
        return None
    try:
        import redis
        client = redis.Redis.from_url(redis_url)
        client.ping()
        return client
    except Exception as exc:
        logger.warning(f"[Queue] Redis connection failed: {exc}")
        return None


def get_rq_queue(connection=None):
    """
    Returns an RQ Queue instance connected to Redis.

    Without an explicit connection, reuses the JobStore's client so the queue
    and the job records always live on the same Redis instance.
    """
    conn = connection
    if conn is None:
        conn = _resolve_store().redis_client
    if conn is None:
        return None
    try:
        from rq import Queue
        queue_name = os.getenv("RQ_QUEUE_NAME", DEFAULT_QUEUE_NAME)
        return Queue(queue_name, connection=conn)
    except Exception as exc:
        logger.error(f"[Queue] Failed to initialize RQ Queue: {exc}")
        return None


def enqueue_analysis_job(
    job_id: str,
    repo_url: str,
    options: dict,
    executor: Optional[concurrent.futures.Executor] = None,
    store=None
) -> Tuple[bool, str]:
    """
    Enqueues an analysis job for execution.

    Dispatch follows the JobStore's actual backend:
      - Redis store  -> distributed RQ queue on that same client
      - memory store -> in-process thread pool (also used when Redis is
        configured but unreachable, i.e. degraded mode)

    Raises:
        QueueDispatchError: the job is stored in Redis but could not be handed
            to RQ. Callers should fail the request rather than run the job in a
            process that cannot share the persisted state.

    Returns:
        (is_distributed: bool, dispatch_mode: str)
    """
    from src.api import pipeline_runner

    job_store = _resolve_store(store)
    conn = job_store.redis_client

    if conn is not None:
        q = get_rq_queue(conn)
        if q is None:
            raise QueueDispatchError(
                f"RQ queue is unavailable for Redis-backed job {job_id}"
            )
        try:
            timeout = int(os.getenv("JOB_TIMEOUT_SECONDS", DEFAULT_JOB_TIMEOUT))
            q.enqueue(
                pipeline_runner.run,
                job_id,
                repo_url,
                options,
                job_id=job_id,  # Set RQ job_id identifier
                job_timeout=timeout,
                result_ttl=int(os.getenv("JOB_TTL_SECONDS", 86400))
            )
            logger.info(f"[Queue] Enqueued job {job_id} to RQ queue '{q.name}' (timeout={timeout}s)")
            return True, "rq_distributed"
        except Exception as exc:
            logger.error(f"[Queue] Failed to enqueue Redis-backed job {job_id} to RQ: {exc}")
            raise QueueDispatchError(
                f"could not dispatch job {job_id} to the RQ queue: {exc}"
            ) from exc

    # Memory (or degraded) store: the job record only exists in this process,
    # so execute it here as well.
    if job_store.degraded:
        logger.warning(
            f"[Queue] Redis is configured but the job store is degraded to memory; "
            f"dispatching job {job_id} to the in-process thread pool."
        )
    exec_target = executor if executor is not None else _local_executor
    logger.info(f"[Queue] Dispatching job {job_id} to ThreadPoolExecutor")
    try:
        future = exec_target.submit(pipeline_runner.run, job_id, repo_url, options)
    except Exception as exc:
        logger.error("[Queue] Failed to dispatch local job %s: %s", job_id, exc)
        raise QueueDispatchError(f"could not dispatch job {job_id}: {exc}") from exc
    if isinstance(future, concurrent.futures.Future):
        with _local_futures_lock:
            _local_futures[job_id] = future

        def forget_completed(done_future):
            with _local_futures_lock:
                if _local_futures.get(job_id) is done_future:
                    _local_futures.pop(job_id, None)

        future.add_done_callback(forget_completed)
    return False, "local_threadpool"


def cancel_analysis_job(job_id: str, store=None) -> bool:
    """Cancel a job only while it is still waiting to execute.

    Returns False once a local future or RQ job has started. Running pipeline
    work is intentionally not interrupted mid-agent because it may be inside
    a non-cancellable GitHub, embedding, or LLM request.
    """
    job_store = _resolve_store(store)
    if job_store.redis_client is None:
        with _local_futures_lock:
            future = _local_futures.get(job_id)
        if future is None:
            # In-memory records without a tracked future have no queue item
            # that can still execute (for example a stale test fixture).
            return True
        cancelled = future.cancel()
        if cancelled:
            with _local_futures_lock:
                if _local_futures.get(job_id) is future:
                    _local_futures.pop(job_id, None)
        return cancelled

    try:
        from rq.exceptions import NoSuchJobError
        from rq.job import Job as RQJob

        try:
            queued_job = RQJob.fetch(job_id, connection=job_store.redis_client)
        except NoSuchJobError:
            return True

        status = queued_job.get_status(refresh=True)
        status_value = getattr(status, "value", status)
        if status_value not in {"queued", "deferred", "scheduled"}:
            return False
        queued_job.cancel()
        return True
    except QueueDispatchError:
        raise
    except Exception as exc:
        logger.error("[Queue] Failed to cancel queued job %s: %s", job_id, exc)
        raise QueueDispatchError(f"could not cancel job {job_id}: {exc}") from exc


def get_queue_stats(store=None) -> dict:
    """
    Returns queue metadata and depth for health checks and monitoring.

    Derived from the shared JobStore so `queue_mode` cannot disagree with the
    backend that actually holds job records.
    """
    job_store = _resolve_store(store)
    stats = {
        "mode": "local_threadpool",
        "redis_connected": job_store.is_redis,
        "redis_configured": job_store.redis_configured,
        "store_backend": job_store.backend,
        "store_degraded": job_store.degraded,
        "queue_depth": 0,
    }

    if not job_store.is_redis:
        return stats

    try:
        q = get_rq_queue(job_store.redis_client)
        stats.update({
            "mode": "rq_distributed",
            "queue_name": q.name if q else DEFAULT_QUEUE_NAME,
            "queue_depth": len(q) if q else 0,
        })
    except Exception as exc:
        stats.update({
            "mode": "error",
            "error": str(exc),
        })
    return stats
