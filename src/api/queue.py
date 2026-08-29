"""
Task Queue management for Project Gnosis.

Handles job enqueuing to Redis Queue (RQ) for distributed execution across worker
processes, with graceful fallback to a local thread pool executor when Redis is not configured.
"""
import os
import logging
import concurrent.futures
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Fallback in-process thread pool executor for local/testing mode
_local_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

DEFAULT_QUEUE_NAME = "gnosis_jobs"
DEFAULT_JOB_TIMEOUT = 1800  # 30 minutes


def get_redis_connection():
    """
    Returns a Redis connection instance if REDIS_URL is configured and reachable.
    """
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
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
    """
    conn = connection or get_redis_connection()
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
    executor: Optional[concurrent.futures.Executor] = None
) -> Tuple[bool, str]:
    """
    Enqueues an analysis job for execution.

    If Redis and RQ are configured, enqueues the job to the distributed RQ queue.
    Otherwise, submits the job to the thread pool executor.

    Returns:
        (is_distributed: bool, dispatch_mode: str)
    """
    from src.api import pipeline_runner

    conn = get_redis_connection()
    if conn is not None:
        try:
            q = get_rq_queue(conn)
            if q is not None:
                timeout = int(os.getenv("JOB_TIMEOUT_SECONDS", DEFAULT_JOB_TIMEOUT))
                rq_job = q.enqueue(
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
            logger.error(f"[Queue] Failed to enqueue to RQ ({exc}). Falling back to threadpool.")

    # Fallback to threadpool execution
    exec_target = executor if executor is not None else _local_executor
    logger.info(f"[Queue] Dispatching job {job_id} to ThreadPoolExecutor")
    exec_target.submit(pipeline_runner.run, job_id, repo_url, options)
    return False, "local_threadpool"


def get_queue_stats() -> dict:
    """
    Returns queue metadata and depth for health checks and monitoring.
    """
    conn = get_redis_connection()
    if conn is None:
        return {
            "mode": "local_threadpool",
            "redis_connected": False,
            "queue_depth": 0
        }
    try:
        q = get_rq_queue(conn)
        return {
            "mode": "rq_distributed",
            "redis_connected": True,
            "queue_name": q.name if q else DEFAULT_QUEUE_NAME,
            "queue_depth": len(q) if q else 0
        }
    except Exception as exc:
        return {
            "mode": "error",
            "redis_connected": False,
            "error": str(exc),
            "queue_depth": 0
        }
