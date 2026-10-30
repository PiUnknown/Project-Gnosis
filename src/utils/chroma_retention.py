"""TTL cleanup for Project Gnosis managed Chroma collections."""
import logging
import os
import time

logger = logging.getLogger(__name__)
DEFAULT_CHROMA_COLLECTION_TTL_SECONDS = 7 * 24 * 60 * 60
CHROMA_MANAGED_MARKER = "project-gnosis"


def cleanup_expired_collections(client, now: int | None = None, ttl_seconds: int | None = None) -> int:
    """Delete only tagged Gnosis collections older than the configured TTL.

    Collections created before managed metadata was added are left untouched,
    since their ownership and age cannot be established safely.
    """
    if ttl_seconds is None:
        raw_ttl = os.getenv("CHROMA_COLLECTION_TTL_SECONDS")
        try:
            ttl_seconds = int(raw_ttl) if raw_ttl is not None else DEFAULT_CHROMA_COLLECTION_TTL_SECONDS
        except (TypeError, ValueError):
            logger.warning("Invalid CHROMA_COLLECTION_TTL_SECONDS=%r; using 7 days", raw_ttl)
            ttl_seconds = DEFAULT_CHROMA_COLLECTION_TTL_SECONDS
    if ttl_seconds <= 0:
        return 0

    current_time = int(time.time()) if now is None else int(now)
    removed = 0
    try:
        collections = client.list_collections()
    except Exception as exc:
        logger.warning("Could not list Chroma collections for retention cleanup: %s", exc)
        return 0

    for listed in collections:
        name = getattr(listed, "name", listed if isinstance(listed, str) else None)
        if not isinstance(name, str) or not name.startswith("gnosis_"):
            continue
        try:
            collection = client.get_collection(name=name)
            metadata = collection.metadata or {}
            if metadata.get("gnosis_managed") != CHROMA_MANAGED_MARKER:
                continue
            created_at = int(metadata.get("gnosis_created_at", 0))
            if created_at <= 0 or current_time - created_at < ttl_seconds:
                continue
            client.delete_collection(name=name)
            removed += 1
        except Exception as exc:
            logger.warning("Could not clean up expired Chroma collection %s: %s", name, exc)

    if removed:
        logger.info("Removed %s expired Project Gnosis Chroma collection(s)", removed)
    return removed
