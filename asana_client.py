import time
import logging
from typing import Generator

import requests

logger = logging.getLogger(__name__)

# Asana rate limits:
# - Free: 150 req/min, Paid: 1500 req/min
# - Concurrent GETs: 50
# - 429 response includes Retry-After header (seconds)
# - Rejected requests still count against quota

MAX_RETRIES = 5
DEFAULT_PAGE_SIZE = 100  # Asana max is 100


class AsanaClient:
    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        self.base_url = "https://app.asana.com/api/1.0"

    def _request(self, endpoint: str, params: dict = None) -> dict:
        """Single GET request with retry on 429."""
        url = f"{self.base_url}/{endpoint}"
        for attempt in range(MAX_RETRIES):
            resp = self.session.get(url, params=params)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 30))
                logger.warning(f"Rate limited. Retry-After: {retry_after}s (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(retry_after)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"Rate limit exceeded after {MAX_RETRIES} retries for {endpoint}")

    def _paginate(self, endpoint: str, params: dict = None) -> Generator[dict, None, None]:
        """Yields individual resource dicts, handling pagination automatically."""
        params = dict(params or {})
        params.setdefault("limit", DEFAULT_PAGE_SIZE)

        while True:
            body = self._request(endpoint, params=params)
            for item in body.get("data", []):
                yield item
            next_page = body.get("next_page")
            if not next_page or not next_page.get("offset"):
                break
            params["offset"] = next_page["offset"]

    def get_users(self, workspace_gid: str) -> Generator[dict, None, None]:
        """GET /users?workspace=<gid>&opt_fields=gid,name,email"""
        yield from self._paginate(
            "users",
            params={"workspace": workspace_gid, "opt_fields": "gid,name,email"},
        )

    def get_projects(self, workspace_gid: str) -> Generator[dict, None, None]:
        """GET /projects?workspace=<gid>&opt_fields=gid,name,archived,created_at,modified_at"""
        yield from self._paginate(
            "projects",
            params={
                "workspace": workspace_gid,
                "opt_fields": "gid,name,archived,created_at,modified_at",
            },
        )
