import json
from pathlib import Path
from unittest.mock import patch, MagicMock


from pipeline import run_sync, SyncState




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
        mock_client.get_user_details_concurrent.return_value = [
            {"gid": "1", "name": "Alice", "email": "a@test.com", "photo": None},
        ]
        mock_client.get_projects.return_value = iter([
            {"gid": "10", "name": "Proj", "archived": False},
        ])
        mock_client.get_project_details_concurrent.return_value = [
            {"gid": "10", "name": "Proj", "notes": "Full details"},
        ]
        mock_client_cls.return_value = mock_client

        with patch("pipeline.OUTPUT_DIR", tmp_path):
            from pipeline import sync_state
            # Reset state between tests
            sync_state.running = False
            run_sync(token="tok", workspace_gid="ws")

        assert not (tmp_path / "users").exists()
        assert (tmp_path / "user_details" / "1.json").exists()
        assert not (tmp_path / "projects").exists()
        assert (tmp_path / "project_details" / "10.json").exists()

        user_detail = json.loads((tmp_path / "user_details" / "1.json").read_text())
        assert user_detail["photo"] is None

        project_detail = json.loads((tmp_path / "project_details" / "10.json").read_text())
        assert project_detail["notes"] == "Full details"

        mock_client.get_user_details_concurrent.assert_called_once_with(user_gids=["1"])
        mock_client.get_project_details_concurrent.assert_called_once_with(project_gids=["10"])

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
