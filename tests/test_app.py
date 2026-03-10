import os
from unittest.mock import patch

import pytest


@pytest.fixture
def flask_client():
    # Prevent start_scheduler from running on import
    with patch.dict(os.environ, {"ASANA_TOKEN": "test", "ASANA_WORKSPACE_GID": "ws1"}), \
         patch("app.start_scheduler"):
        import importlib
        import app as app_module
        importlib.reload(app_module)
        app_module.app.config["TESTING"] = True
        with app_module.app.test_client() as client:
            yield client


class TestHealthEndpoint:
    def test_returns_ok(self, flask_client):
        resp = flask_client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "ok"}


class TestStatusEndpoint:
    def test_returns_sync_state(self, flask_client):
        resp = flask_client.get("/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "running" in data
        assert "last_sync" in data
        assert "users_count" in data
        assert "projects_count" in data
        assert "last_error" in data
