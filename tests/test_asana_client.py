import json
from unittest.mock import patch, MagicMock

import pytest

from asana_client import AsanaClient, MAX_RETRIES, PROJECT_DETAIL_FIELDS, USER_DETAIL_FIELDS


def _mock_response(status_code=200, json_data=None, headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400 and status_code != 429:
        from requests.exceptions import HTTPError
        resp.raise_for_status.side_effect = HTTPError(response=resp)
    return resp


@pytest.fixture
def client():
    return AsanaClient(token="test-token")


class TestAuth:
    def test_bearer_token_in_headers(self, client):
        assert client.session.headers["Authorization"] == "Bearer test-token"

    def test_base_url(self, client):
        assert client.base_url == "https://app.asana.com/api/1.0"


class TestRequest:
    @patch.object(AsanaClient, "_request")
    def test_get_users_params(self, mock_request, client):
        mock_request.return_value = {"data": [], "next_page": None}
        list(client.get_users(workspace_gid="ws123"))
        mock_request.assert_called_once_with(
            "users",
            params={"workspace": "ws123", "opt_fields": "gid,name,email", "limit": 100},
        )

    @patch.object(AsanaClient, "_request")
    def test_get_projects_params(self, mock_request, client):
        mock_request.return_value = {"data": [], "next_page": None}
        list(client.get_projects(workspace_gid="ws123"))
        mock_request.assert_called_once_with(
            "projects",
            params={
                "workspace": "ws123",
                "opt_fields": "gid,name,archived,created_at,modified_at",
                "limit": 100,
            },
        )


class TestRateLimiting:
    @patch("asana_client.time.sleep")
    def test_retries_on_429_then_succeeds(self, mock_sleep, client):
        rate_limited = _mock_response(status_code=429, headers={"Retry-After": "5"})
        success = _mock_response(json_data={"data": [{"gid": "1", "name": "Alice"}]})

        with patch.object(client.session, "get", side_effect=[rate_limited, success]):
            result = client._request("users")

        assert result == {"data": [{"gid": "1", "name": "Alice"}]}
        mock_sleep.assert_called_once_with(5)

    @patch("asana_client.time.sleep")
    def test_uses_retry_after_header_value(self, mock_sleep, client):
        rate_limited = _mock_response(status_code=429, headers={"Retry-After": "42"})
        success = _mock_response(json_data={"data": []})

        with patch.object(client.session, "get", side_effect=[rate_limited, success]):
            client._request("users")

        mock_sleep.assert_called_once_with(42)

    @patch("asana_client.time.sleep")
    def test_defaults_retry_after_to_30_when_header_missing(self, mock_sleep, client):
        rate_limited = _mock_response(status_code=429, headers={})
        success = _mock_response(json_data={"data": []})

        with patch.object(client.session, "get", side_effect=[rate_limited, success]):
            client._request("users")

        mock_sleep.assert_called_once_with(30)

    @patch("asana_client.time.sleep")
    def test_multiple_429s_before_success(self, mock_sleep, client):
        rate_limited = _mock_response(status_code=429, headers={"Retry-After": "1"})
        success = _mock_response(json_data={"data": [{"gid": "1"}]})

        with patch.object(client.session, "get", side_effect=[rate_limited, rate_limited, rate_limited, success]):
            result = client._request("users")

        assert result == {"data": [{"gid": "1"}]}
        assert mock_sleep.call_count == 3

    @patch("asana_client.time.sleep")
    def test_raises_after_max_retries_exhausted(self, mock_sleep, client):
        rate_limited = _mock_response(status_code=429, headers={"Retry-After": "1"})
        responses = [rate_limited] * MAX_RETRIES

        with patch.object(client.session, "get", side_effect=responses):
            with pytest.raises(RuntimeError, match="Rate limit exceeded after"):
                client._request("users")

        assert mock_sleep.call_count == MAX_RETRIES

    def test_non_429_error_raises_immediately(self, client):
        error_resp = _mock_response(status_code=500)

        with patch.object(client.session, "get", return_value=error_resp):
            with pytest.raises(Exception):
                client._request("users")


class TestPagination:
    @patch.object(AsanaClient, "_request")
    def test_single_page(self, mock_request, client):
        mock_request.return_value = {
            "data": [{"gid": "1"}, {"gid": "2"}],
            "next_page": None,
        }
        results = list(client._paginate("users"))
        assert results == [{"gid": "1"}, {"gid": "2"}]
        assert mock_request.call_count == 1

    @patch.object(AsanaClient, "_request")
    def test_multiple_pages(self, mock_request, client):
        mock_request.side_effect = [
            {"data": [{"gid": "1"}, {"gid": "2"}], "next_page": {"offset": "abc123"}},
            {"data": [{"gid": "3"}], "next_page": None},
        ]
        results = list(client._paginate("users"))
        assert results == [{"gid": "1"}, {"gid": "2"}, {"gid": "3"}]
        assert mock_request.call_count == 2

        # Verify offset was passed on second call
        second_call_params = mock_request.call_args_list[1][1]["params"]
        assert second_call_params["offset"] == "abc123"

    @patch.object(AsanaClient, "_request")
    def test_empty_response(self, mock_request, client):
        mock_request.return_value = {"data": [], "next_page": None}
        results = list(client._paginate("users"))
        assert results == []

    @patch.object(AsanaClient, "_request")
    def test_three_pages(self, mock_request, client):
        mock_request.side_effect = [
            {"data": [{"gid": str(i)} for i in range(100)], "next_page": {"offset": "page2"}},
            {"data": [{"gid": str(i)} for i in range(100, 200)], "next_page": {"offset": "page3"}},
            {"data": [{"gid": "200"}], "next_page": None},
        ]
        results = list(client._paginate("users"))
        assert len(results) == 201

    @patch.object(AsanaClient, "_request")
    def test_default_page_size(self, mock_request, client):
        mock_request.return_value = {"data": [], "next_page": None}
        list(client._paginate("users"))
        params = mock_request.call_args[1]["params"]
        assert params["limit"] == 100


class TestGetUsers:
    @patch.object(AsanaClient, "_request")
    def test_returns_user_records(self, mock_request, client):
        mock_request.return_value = {
            "data": [
                {"gid": "1", "name": "Alice", "email": "alice@test.com"},
                {"gid": "2", "name": "Bob", "email": "bob@test.com"},
            ],
            "next_page": None,
        }
        users = list(client.get_users(workspace_gid="ws1"))
        assert len(users) == 2
        assert users[0]["email"] == "alice@test.com"
        assert users[1]["name"] == "Bob"


class TestGetProjects:
    @patch.object(AsanaClient, "_request")
    def test_returns_project_records(self, mock_request, client):
        mock_request.return_value = {
            "data": [
                {"gid": "10", "name": "Project A", "archived": False},
                {"gid": "20", "name": "Project B", "archived": True},
            ],
            "next_page": None,
        }
        projects = list(client.get_projects(workspace_gid="ws1"))
        assert len(projects) == 2
        assert projects[0]["name"] == "Project A"
        assert projects[1]["archived"] is True


class TestGetUserDetail:
    @patch.object(AsanaClient, "_request")
    def test_returns_full_user(self, mock_request, client):
        mock_request.return_value = {
            "data": {
                "gid": "1",
                "name": "Alice",
                "email": "alice@test.com",
                "photo": {"image_128x128": "https://example.com/photo.png"},
            },
        }
        detail = client.get_user_detail(user_gid="1")
        assert detail["gid"] == "1"
        assert detail["email"] == "alice@test.com"
        mock_request.assert_called_once_with(
            "users/1", params={"opt_fields": USER_DETAIL_FIELDS},
        )


class TestGetUserDetailsConcurrent:
    @patch.object(AsanaClient, "_request")
    def test_fetches_all_users(self, mock_request, client):
        mock_request.side_effect = lambda endpoint, **kwargs: {
            "data": {"gid": endpoint.split("/")[1], "name": f"User {endpoint}"}
        }
        results = client.get_user_details_concurrent(user_gids=["1", "2", "3"])
        assert len(results) == 3
        assert results[0]["gid"] == "1"
        assert results[2]["gid"] == "3"

    @patch.object(AsanaClient, "_request")
    def test_preserves_input_order(self, mock_request, client):
        mock_request.side_effect = lambda endpoint, **kwargs: {
            "data": {"gid": endpoint.split("/")[1]}
        }
        gids = ["5", "3", "1", "4", "2"]
        results = client.get_user_details_concurrent(user_gids=gids)
        assert [r["gid"] for r in results] == gids

    @patch.object(AsanaClient, "_request")
    def test_empty_list(self, mock_request, client):
        results = client.get_user_details_concurrent(user_gids=[])
        assert results == []
        mock_request.assert_not_called()


class TestGetProjectDetail:
    @patch.object(AsanaClient, "_request")
    def test_returns_full_project(self, mock_request, client):
        mock_request.return_value = {
            "data": {
                "gid": "10",
                "name": "Project A",
                "notes": "Description here",
                "owner": {"gid": "1", "name": "Alice"},
            },
        }
        detail = client.get_project_detail(project_gid="10")
        assert detail["gid"] == "10"
        assert detail["notes"] == "Description here"
        mock_request.assert_called_once_with(
            "projects/10", params={"opt_fields": PROJECT_DETAIL_FIELDS},
        )

    @patch.object(AsanaClient, "_request")
    def test_calls_correct_endpoint(self, mock_request, client):
        mock_request.return_value = {"data": {"gid": "99"}}
        client.get_project_detail(project_gid="99")
        mock_request.assert_called_once_with(
            "projects/99", params={"opt_fields": PROJECT_DETAIL_FIELDS},
        )


class TestGetProjectDetailsConcurrent:
    @patch.object(AsanaClient, "_request")
    def test_fetches_all_projects(self, mock_request, client):
        mock_request.side_effect = lambda endpoint, **kwargs: {
            "data": {"gid": endpoint.split("/")[1], "name": f"Project {endpoint}"}
        }
        results = client.get_project_details_concurrent(project_gids=["10", "20", "30"])
        assert len(results) == 3
        assert results[0]["gid"] == "10"
        assert results[1]["gid"] == "20"
        assert results[2]["gid"] == "30"

    @patch.object(AsanaClient, "_request")
    def test_preserves_input_order(self, mock_request, client):
        mock_request.side_effect = lambda endpoint, **kwargs: {
            "data": {"gid": endpoint.split("/")[1]}
        }
        gids = ["5", "3", "1", "4", "2"]
        results = client.get_project_details_concurrent(project_gids=gids)
        assert [r["gid"] for r in results] == gids

    @patch.object(AsanaClient, "_request")
    def test_empty_list(self, mock_request, client):
        results = client.get_project_details_concurrent(project_gids=[])
        assert results == []
        mock_request.assert_not_called()


class TestConcurrencySemaphore:
    def test_semaphore_limits_concurrent_gets(self):
        client = AsanaClient(token="test-token", max_concurrent_gets=2)
        assert client._get_semaphore._value == 2

    def test_default_semaphore_value(self):
        client = AsanaClient(token="test-token")
        from asana_client import MAX_CONCURRENT_GETS
        assert client._get_semaphore._value == MAX_CONCURRENT_GETS
