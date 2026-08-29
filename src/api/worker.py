"""
Project Gnosis — Distributed Background Worker.

Consumes and executes repository analysis jobs from the Redis Queue (RQ).
Runs as an independent OS process or dedicated Docker container to ensure CPU/RAM-heavy
tasks (AST parsing, vector embeddings, and LLM calls) never block or crash the FastAPI web server.

Usage:
    python -m src.api.worker
    python src/api/worker.py
"""
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

try:
    __import__("pysqlite3")
    import sys
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass

import os
import logging
from dotenv import load_dotenv
import redis
from rq import Worker, Queue

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [Worker] %(message)s"
)
logger = logging.getLogger("gnosis_worker")

DEFAULT_QUEUE_NAME = "gnosis_jobs"


def start_worker():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    queue_name = os.getenv("RQ_QUEUE_NAME", DEFAULT_QUEUE_NAME)

    logger.info(f"Connecting to Redis at {redis_url}...")
    try:
        conn = redis.Redis.from_url(redis_url)
        conn.ping()
        logger.info("Connected to Redis successfully.")
    except Exception as exc:
        logger.critical(f"Could not connect to Redis at {redis_url}: {exc}")
        sys.exit(1)

    queues = [Queue(queue_name, connection=conn)]
    logger.info(f"Starting RQ Worker on queue: '{queue_name}'")
    logger.info("Ready for archaeology analysis jobs. Press Ctrl+C to terminate.")

    worker = Worker(queues, connection=conn)
    worker.work()


if __name__ == "__main__":
    start_worker()
