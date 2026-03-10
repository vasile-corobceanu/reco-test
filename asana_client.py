import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Generator

import requests

logger = logging.getLogger(__name__)

# Asana rate limits:
# - Free: 150 req/min, Paid: 1500 req/min
# - Concurrent GETs: 50, Concurrent writes: 15
# - 429 response includes Retry-After header (seconds)
# - Rejected requests still count against quota

MAX_RETRIES = 5
MAX_CONCURRENT_GETS = 50
DEFAULT_PAGE_SIZE = 100  # Asana max is 100

USER_DETAIL_FIELDS = ",".join([
    "gid", "resource_type", "name", "email", "photo",
    "workspaces.name",
    # custom_fields
    "custom_fields.name",
    "custom_fields.type",
    "custom_fields.enum_options.name",
    "custom_fields.enum_options.enabled",
    "custom_fields.enum_options.color",
    "custom_fields.enabled",
    "custom_fields.representation_type",
    "custom_fields.id_prefix",
    "custom_fields.input_restrictions",
    "custom_fields.is_formula_field",
    "custom_fields.date_value",
    "custom_fields.enum_value.name",
    "custom_fields.enum_value.enabled",
    "custom_fields.enum_value.color",
    "custom_fields.multi_enum_values.name",
    "custom_fields.multi_enum_values.enabled",
    "custom_fields.multi_enum_values.color",
    "custom_fields.number_value",
    "custom_fields.text_value",
    "custom_fields.display_value",
])

PROJECT_DETAIL_FIELDS = ",".join([
    # Top-level scalar fields
    "gid", "resource_type", "name", "archived", "color", "icon",
    "created_at", "modified_at", "due_date", "due_on", "start_on",
    "notes", "html_notes", "public", "privacy_setting",
    "default_view", "default_access_level",
    "minimum_access_level_for_customization",
    "minimum_access_level_for_sharing",
    "completed", "completed_at", "permalink_url",
    # Nested object sub-fields
    "completed_by.name",
    "owner.name",
    "team.name",
    "workspace.name",
    "followers.name",
    "members.name",
    "project_brief",
    "created_from_template.name",
    # current_status
    "current_status.title",
    "current_status.text",
    "current_status.html_text",
    "current_status.color",
    "current_status.author.name",
    "current_status.created_at",
    "current_status.created_by.name",
    "current_status.modified_at",
    # current_status_update
    "current_status_update.title",
    "current_status_update.resource_subtype",
    # custom_fields
    "custom_fields.name",
    "custom_fields.type",
    "custom_fields.enum_options.name",
    "custom_fields.enum_options.enabled",
    "custom_fields.enum_options.color",
    "custom_fields.enabled",
    "custom_fields.representation_type",
    "custom_fields.id_prefix",
    "custom_fields.input_restrictions",
    "custom_fields.is_formula_field",
    "custom_fields.date_value",
    "custom_fields.enum_value.name",
    "custom_fields.enum_value.enabled",
    "custom_fields.enum_value.color",
    "custom_fields.multi_enum_values.name",
    "custom_fields.multi_enum_values.enabled",
    "custom_fields.multi_enum_values.color",
    "custom_fields.number_value",
    "custom_fields.text_value",
    "custom_fields.display_value",
    # custom_field_settings
    "custom_field_settings.is_important",
    "custom_field_settings.project.name",
    "custom_field_settings.parent.name",
    "custom_field_settings.custom_field.name",
    "custom_field_settings.custom_field.type",
    "custom_field_settings.custom_field.enum_options.name",
    "custom_field_settings.custom_field.enum_options.enabled",
    "custom_field_settings.custom_field.enum_options.color",
    "custom_field_settings.custom_field.enabled",
    "custom_field_settings.custom_field.representation_type",
    "custom_field_settings.custom_field.id_prefix",
    "custom_field_settings.custom_field.input_restrictions",
    "custom_field_settings.custom_field.is_formula_field",
    "custom_field_settings.custom_field.date_value",
    "custom_field_settings.custom_field.enum_value.name",
    "custom_field_settings.custom_field.enum_value.enabled",
    "custom_field_settings.custom_field.enum_value.color",
    "custom_field_settings.custom_field.multi_enum_values.name",
    "custom_field_settings.custom_field.multi_enum_values.enabled",
    "custom_field_settings.custom_field.multi_enum_values.color",
    "custom_field_settings.custom_field.number_value",
    "custom_field_settings.custom_field.text_value",
    "custom_field_settings.custom_field.display_value",
    "custom_field_settings.custom_field.description",
    "custom_field_settings.custom_field.precision",
    "custom_field_settings.custom_field.format",
    "custom_field_settings.custom_field.currency_code",
    "custom_field_settings.custom_field.custom_label",
    "custom_field_settings.custom_field.custom_label_position",
    "custom_field_settings.custom_field.is_global_to_workspace",
    "custom_field_settings.custom_field.has_notifications_enabled",
    "custom_field_settings.custom_field.asana_created_field",
    "custom_field_settings.custom_field.is_value_read_only",
    "custom_field_settings.custom_field.created_by.name",
    "custom_field_settings.custom_field.people_value.name",
    "custom_field_settings.custom_field.reference_value.name",
    "custom_field_settings.custom_field.privacy_setting",
    "custom_field_settings.custom_field.default_access_level",
    "custom_field_settings.custom_field.resource_subtype",
])


class AsanaClient:
    def __init__(self, token: str, max_concurrent_gets: int = MAX_CONCURRENT_GETS):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        self.base_url = "https://app.asana.com/api/1.0"
        self._get_semaphore = threading.Semaphore(max_concurrent_gets)

    def _request(self, endpoint: str, params: dict = None) -> dict:
        """Single GET request with retry on 429. Respects concurrent GET limit."""
        url = f"{self.base_url}/{endpoint}"
        for attempt in range(MAX_RETRIES):
            self._get_semaphore.acquire()
            try:
                resp = self.session.get(url, params=params)
            finally:
                self._get_semaphore.release()
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

    def get_user_detail(self, user_gid: str) -> dict:
        """GET /users/<gid> with explicit opt_fields for full user record."""
        body = self._request(
            f"users/{user_gid}",
            params={"opt_fields": USER_DETAIL_FIELDS},
        )
        return body["data"]

    def get_user_details_concurrent(self, user_gids: list[str]) -> list[dict]:
        """Fetch full details for multiple users concurrently."""
        results = {}
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_GETS) as executor:
            futures = {
                executor.submit(self.get_user_detail, user_gid=gid): gid
                for gid in user_gids
            }
            for future in as_completed(futures):
                gid = futures[future]
                results[gid] = future.result()
        return [results[gid] for gid in user_gids]

    def get_project_detail(self, project_gid: str) -> dict:
        """GET /projects/<gid> with explicit opt_fields for full project record."""
        body = self._request(
            f"projects/{project_gid}",
            params={"opt_fields": PROJECT_DETAIL_FIELDS},
        )
        return body["data"]

    def get_project_details_concurrent(self, project_gids: list[str]) -> list[dict]:
        """Fetch full details for multiple projects concurrently."""
        results = {}
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_GETS) as executor:
            futures = {
                executor.submit(self.get_project_detail, project_gid=gid): gid
                for gid in project_gids
            }
            for future in as_completed(futures):
                gid = futures[future]
                results[gid] = future.result()
        # Preserve input order
        return [results[gid] for gid in project_gids]
