"""Submission rate limiting shared across API workers when Redis is enabled."""
import hashlib
import logging
import os
import threading
import time
from typing import Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

DEFAULT_ANALYZE_RATE_LIMIT = 30
DEFAULT_ANALYZE_RATE_WINDOW_SECONDS = 60
_local_lock = threading.Lock()
_local_counters: dict[tuple[str, int], int] = {}


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
        if value > 0:
            return value
    except (TypeError, ValueError):
        pass
    logger.warning("Invalid %s=%r; using default %s", name, raw, default)
    return default


def check_analyze_rate_limit(client_ip: Optional[str], redis_client=None) -> None:
    """Allow a configured number of submissions per client IP and fixed window."""
    limit = _positive_int("ANALYZE_RATE_LIMIT", DEFAULT_ANALYZE_RATE_LIMIT)
    window = _positive_int(
        "ANALYZE_RATE_WINDOW_SECONDS", DEFAULT_ANALYZE_RATE_WINDOW_SECONDS
    )
    now = int(time.time())
    window_id = now // window
    identity = hashlib.sha256((client_ip or "unknown").encode("utf-8")).hexdigest()[:24]
    key = f"gnosis:rate:analyze:{window_id}:{identity}"

    if redis_client is not None:
        try:
            count = int(redis_client.incr(key))
            if count == 1:
                redis_client.expire(key, window + 1)
        except Exception as exc:
            logger.error("Submission rate-limit store is unavailable: %s", exc)
            raise HTTPException(
                status_code=503,
                detail="Submission protection is temporarily unavailable. Please retry shortly.",
            ) from exc
    else:
        with _local_lock:
            stale = [entry for entry in _local_counters if entry[1] < window_id - 1]
            for entry in stale:
                _local_counters.pop(entry, None)
            if len(_local_counters) >= 10000 and (identity, window_id) not in _local_counters:
                _local_counters.clear()
            local_key = (identity, window_id)
            count = _local_counters.get(local_key, 0) + 1
            _local_counters[local_key] = count

    if count > limit:
        retry_after = max(1, (window_id + 1) * window - now)
        raise HTTPException(
            status_code=429,
            detail="Too many repository analyses submitted. Please retry after the current rate-limit window.",
            headers={"Retry-After": str(retry_after)},
        )


def reset_local_rate_limits() -> None:
    """Clear in-process counters; primarily used by isolated API tests."""
    with _local_lock:
        _local_counters.clear()
