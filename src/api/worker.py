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


import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class WorkerHealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "worker_active", "service": "gnosis-worker"}')

    def log_message(self, format, *args):
        # Silence HTTP access logs to keep worker output clean
        pass


def _start_health_server(port: int):
    try:
        server = HTTPServer(("0.0.0.0", port), WorkerHealthHandler)
        logger.info(f"[Worker Health] Listening on port {port} for platform health checks.")
        server.serve_forever()
    except Exception as exc:
        logger.warning(f"[Worker Health] Could not start health server on port {port}: {exc}")


def start_worker():
    # If a PORT is specified (e.g. Render Web Service), bind a lightweight health server
    port_env = os.getenv("PORT")
    if port_env:
        try:
            port = int(port_env)
            health_thread = threading.Thread(target=_start_health_server, args=(port,), daemon=True)
            health_thread.start()
        except ValueError:
            pass

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

