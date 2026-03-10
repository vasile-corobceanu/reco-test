import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pipeline import _write_individual_files, run_sync, SyncState


@pytest.fixture
def output_dir(tmp_path):
    return tmp_path / "asana"


class TestWriteIndividualFiles:
    def test_creates_one_file_per_item(self, output_dir):
        items = iter([
            {"gid": "100", "name": "Alice"},
            {"gid": "200", "name": "Bob"},
        ])
        count = _write_individual_files(output_dir / "users", items)

        assert count == 2
        assert (output_dir / "users" / "100.json").exists()
        assert (output_dir / "users" / "200.json").exists()

    def test_file_content_is_valid_json(self, output_dir):
        items = iter([{"gid": "42", "name": "Test", "email": "test@x.com"}])
        _write_individual_files(output_dir / "users", items)

        content = json.loads((output_dir / "users" / "42.json").read_text())
        assert content == {"gid": "42", "name": "Test", "email": "test@x.com"}

    def test_overwrites_existing_files(self, output_dir):
        _write_individual_files(output_dir / "users", iter([{"gid": "1", "name": "Old"}]))
        _write_individual_files(output_dir / "users", iter([{"gid": "1", "name": "New"}]))

        content = json.loads((output_dir / "users" / "1.json").read_text())
        assert content["name"] == "New"

    def test_empty_items(self, output_dir):
        count = _write_individual_files(output_dir / "users", iter([]))
        assert count == 0
        assert (output_dir / "users").exists()

    def test_creates_directories(self, output_dir):
        deep_path = output_dir / "nested" / "deep" / "users"
        _write_individual_files(deep_path, iter([{"gid": "1", "name": "X"}]))
        assert (deep_path / "1.json").exists()


class TestSyncState:
    def test_initial_state(self):
        state = SyncState()
        d = state.to_dict()
        assert d["running"] is False
        assert d["last_sync"] is None
        assert d["last_error"] is None

    def test_start_returns_true_first_time(self):
        state = SyncState()
        assert state.start() is True
        assert state.to_dict()["running"] is True

    def test_start_returns_false_when_already_running(self):
        state = SyncState()
        state.start()
        assert state.start() is False

    def test_finish_sets_state(self):
        state = SyncState()
        state.start()
        state.finish(users=10, projects=5)

        d = state.to_dict()
        assert d["running"] is False
        assert d["users_count"] == 10
        assert d["projects_count"] == 5
        assert d["last_sync"] is not None
        assert d["last_error"] is None

    def test_finish_with_error(self):
        state = SyncState()
        state.start()
        state.finish(users=0, projects=0, error="connection timeout")

        d = state.to_dict()
        assert d["last_error"] == "connection timeout"


class TestRunSync:
    @patch("pipeline.AsanaClient")
    @patch("pipeline.OUTPUT_DIR", new_callable=lambda: lambda: Path("/tmp"))
    def test_writes_users_and_projects(self, mock_output, mock_client_cls, tmp_path):
        mock_client = MagicMock()
        mock_client.get_users.return_value = iter([
            {"gid": "1", "name": "Alice", "email": "a@test.com"},
        ])
        mock_client.get_projects.return_value = iter([
            {"gid": "10", "name": "Proj", "archived": False},
        ])
        mock_client_cls.return_value = mock_client

        with patch("pipeline.OUTPUT_DIR", tmp_path):
            from pipeline import sync_state
            # Reset state between tests
            sync_state.running = False
            run_sync(token="tok", workspace_gid="ws")

        assert (tmp_path / "users" / "1.json").exists()
        assert (tmp_path / "projects" / "10.json").exists()

        state = sync_state.to_dict()
        assert state["users_count"] == 1
        assert state["projects_count"] == 1
        assert state["last_error"] is None

    @patch("pipeline.AsanaClient")
    def test_skips_when_already_running(self, mock_client_cls, tmp_path):
        from pipeline import sync_state
        sync_state.running = False
        sync_state.start()  # mark as running

        with patch("pipeline.OUTPUT_DIR", tmp_path):
            run_sync(token="tok", workspace_gid="ws")

        mock_client_cls.assert_not_called()
        # Clean up
        sync_state.running = False

    @patch("pipeline.AsanaClient")
    def test_handles_api_error(self, mock_client_cls, tmp_path):
        mock_client = MagicMock()
        mock_client.get_users.side_effect = RuntimeError("Rate limit exceeded")
        mock_client_cls.return_value = mock_client

        from pipeline import sync_state
        sync_state.running = False

        with patch("pipeline.OUTPUT_DIR", tmp_path):
            run_sync(token="tok", workspace_gid="ws")

        state = sync_state.to_dict()
        assert "Rate limit exceeded" in state["last_error"]
        assert state["running"] is False
