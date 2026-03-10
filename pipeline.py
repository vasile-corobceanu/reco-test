import json
import os
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from asana_client import AsanaClient

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "data"))


class SyncState:
    """Thread-safe state shared between the pipeline and the status endpoint."""

    def __init__(self):
        self._lock = threading.Lock()
        self.running = False
        self.last_sync: str | None = None
        self.last_error: str | None = None
        self.users_count = 0
        self.projects_count = 0

    def start(self):
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.last_error = None
            return True

    def finish(self, users: int, projects: int, error: str | None = None):
        with self._lock:
            self.running = False
            self.last_sync = datetime.now(timezone.utc).isoformat()
            self.users_count = users
            self.projects_count = projects
            self.last_error = error

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "last_sync": self.last_sync,
                "last_error": self.last_error,
                "users_count": self.users_count,
                "projects_count": self.projects_count,
            }


sync_state = SyncState()


def _write_ndjson(path: Path, items: Generator[dict, None, None]) -> int:
    """Write items as NDJSON — one JSON object per line. Returns count."""
    count = 0
    with open(path, "w") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")
            count += 1
    return count


def run_sync(token: str, workspace_gid: str):
    """Full extraction pipeline. Skips if a previous run is still active."""
    if not sync_state.start():
        logger.warning("Sync already running, skipping this cycle")
        return

    logger.info("Sync started")
    start = time.monotonic()
    users_count = 0
    projects_count = 0

    try:
        client = AsanaClient(token=token)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        # Extract users
        users_path = OUTPUT_DIR / f"users_{ts}.ndjson"
        users_count = _write_ndjson(users_path, client.get_users(workspace_gid=workspace_gid))
        logger.info(f"Wrote {users_count} users to {users_path}")

        # Extract projects
        projects_path = OUTPUT_DIR / f"projects_{ts}.ndjson"
        projects_count = _write_ndjson(projects_path, client.get_projects(workspace_gid=workspace_gid))
        logger.info(f"Wrote {projects_count} projects to {projects_path}")

        elapsed = time.monotonic() - start
        logger.info(f"Sync finished in {elapsed:.1f}s — {users_count} users, {projects_count} projects")
        sync_state.finish(users=users_count, projects=projects_count)

    except Exception as e:
        logger.exception("Sync failed")
        sync_state.finish(users=users_count, projects=projects_count, error=str(e))