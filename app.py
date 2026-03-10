import os
import sys
import signal
import logging

from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

from pipeline import run_sync, sync_state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

TOKEN = os.environ.get("ASANA_TOKEN", "")
WORKSPACE_GID = os.environ.get("ASANA_WORKSPACE_GID", "")
SYNC_INTERVAL = os.environ.get("SYNC_INTERVAL", "5m")

INTERVALS = {
    "30s": {"seconds": 30},
    "5m": {"minutes": 5},
}

_scheduler: BackgroundScheduler | None = None


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/status")
def status():
    return jsonify(sync_state.to_dict())


@app.get("/trigger")
def trigger():
    """Manual trigger for testing."""
    run_sync(token=TOKEN, workspace_gid=WORKSPACE_GID)
    return jsonify(sync_state.to_dict())


def _shutdown_scheduler(signum, frame):
    global _scheduler
    if _scheduler:
        logger.info("Shutting down scheduler...")
        _scheduler.shutdown(wait=False)
    raise SystemExit(0)


def start_scheduler():
    global _scheduler

    if not TOKEN or not WORKSPACE_GID:
        raise RuntimeError("Set ASANA_TOKEN and ASANA_WORKSPACE_GID env vars")

    interval_kwargs = INTERVALS.get(SYNC_INTERVAL)
    if not interval_kwargs:
        raise ValueError(f"SYNC_INTERVAL must be one of {list(INTERVALS.keys())}, got '{SYNC_INTERVAL}'")

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        run_sync,
        trigger="interval",
        kwargs={"token": TOKEN, "workspace_gid": WORKSPACE_GID},
        **interval_kwargs,
        id="asana_sync",
        max_instances=1,
    )
    _scheduler.start()
    logger.info(f"Scheduler started with interval={SYNC_INTERVAL}")

    signal.signal(signal.SIGTERM, _shutdown_scheduler)
    signal.signal(signal.SIGINT, _shutdown_scheduler)

    # Run once immediately on startup
    run_sync(token=TOKEN, workspace_gid=WORKSPACE_GID)


# Gunicorn calls this via `--preload` or post_fork; for `__main__` it's called directly
start_scheduler()


if __name__ == "__main__":
    app.run(port=5001)