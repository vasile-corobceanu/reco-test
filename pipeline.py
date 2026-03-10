import json
import os
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from asana_client import AsanaClient

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "asana"))


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

        users = list(client.get_users(workspace_gid=workspace_gid))
        user_gids = [u["gid"] for u in users]
        users_count = len(user_gids)
        user_details_dir = OUTPUT_DIR / "user_details"
        user_details_dir.mkdir(parents=True, exist_ok=True)
        user_details = client.get_user_details_concurrent(user_gids=user_gids)
        for detail in user_details:
            path = user_details_dir / f"{detail['gid']}.json"
            with open(path, "w") as f:
                json.dump(detail, f, indent=2)
        logger.info(f"Wrote {users_count} user details to {user_details_dir}/")

        projects = list(client.get_projects(workspace_gid=workspace_gid))
        project_gids = [p["gid"] for p in projects]
        projects_count = len(project_gids)
        details_dir = OUTPUT_DIR / "project_details"
        details_dir.mkdir(parents=True, exist_ok=True)
        details = client.get_project_details_concurrent(project_gids=project_gids)
        for detail in details:
            path = details_dir / f"{detail['gid']}.json"
            with open(path, "w") as f:
                json.dump(detail, f, indent=2)
        logger.info(f"Wrote {projects_count} project details to {details_dir}/")

        elapsed = time.monotonic() - start
        logger.info(f"Sync finished in {elapsed:.1f}s — {users_count} users, {projects_count} projects")
        sync_state.finish(users=users_count, projects=projects_count)

    except Exception as e:
        logger.exception("Sync failed")
        sync_state.finish(users=users_count, projects=projects_count, error=str(e))