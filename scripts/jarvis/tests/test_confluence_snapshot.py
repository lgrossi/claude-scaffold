"""Tests for confluence-snapshot.py"""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Load the script as a module
spec = importlib.util.spec_from_file_location(
    "confluence_snapshot",
    Path(__file__).parent.parent / "confluence-snapshot.py",
)
mod = importlib.util.module_from_spec(spec)


def _load_module():
    """Reload module with mocked env vars."""
    with patch.dict("os.environ", {
        "CONFLUENCE_URL": "https://test.atlassian.net",
        "CONFLUENCE_USERNAME": "user@test.com",
        "CONFLUENCE_API_TOKEN": "fake-token",
    }):
        spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _module():
    _load_module()


def _make_page(page_id: str, title: str, space_key: str = "ENG", version: int = 1) -> dict:
    return {
        "id": page_id,
        "title": title,
        "spaceId": "space-1",
        "_links": {"webui": f"/spaces/{space_key}/pages/{page_id}/{title.replace(' ', '+')}"},
        "version": {"number": version, "createdAt": "2026-03-09T10:00:00.000Z"},
    }


def _make_comment(comment_id: str, page_id: str, resolved: bool = False) -> dict:
    return {
        "id": comment_id,
        "status": "resolved" if resolved else "current",
        "pageId": page_id,
        "body": {"storage": {"value": "A comment"}},
        "version": {"createdAt": "2026-03-09T12:00:00.000Z"},
    }


class TestBuildSnapshot:
    """Tests for the core snapshot-building logic."""

    def test_empty_pages(self, tmp_path):
        """No pages owned or watched produces empty snapshot."""
        mock_get = MagicMock()
        mock_get.return_value = _mock_response({"results": [], "size": 0})

        with patch("requests.Session") as MockSession:
            session = MockSession.return_value
            session.get = mock_get

            result = mod.build_snapshot(
                base_url="https://test.atlassian.net",
                auth=("user@test.com", "fake-token"),
            )

        assert result["source"] == "confluence"
        assert result["summary"]["my_pages"] == 0
        assert result["summary"]["watched_pages"] == 0
        assert result["summary"]["unresolved_comments"] == 0

    def test_my_pages_collected(self, tmp_path):
        """Owned pages are collected with metadata."""
        pages = [_make_page("1", "Design Doc"), _make_page("2", "RFC")]

        def mock_get(url, **kwargs):
            if "/wiki/api/v2/pages" in url:
                return _mock_response({"results": pages, "size": 2})
            if "/wiki/rest/api/user/watches/content" in url:
                return _mock_response({"results": [], "size": 0})
            if "/wiki/api/v2/footer-comments" in url:
                return _mock_response({"results": [], "size": 0})
            return _mock_response({"results": []})

        with patch("requests.Session") as MockSession:
            session = MockSession.return_value
            session.get = mock_get

            result = mod.build_snapshot(
                base_url="https://test.atlassian.net",
                auth=("user@test.com", "fake-token"),
            )

        assert result["summary"]["my_pages"] == 2
        assert len(result["items"]["my_pages"]) == 2
        assert result["items"]["my_pages"][0]["title"] == "Design Doc"

    def test_watched_pages_collected(self):
        """Watched pages are collected separately from owned pages."""
        watched = [_make_page("3", "Team Roadmap")]

        def mock_get(url, **kwargs):
            if "/wiki/api/v2/pages" in url:
                return _mock_response({"results": [], "size": 0})
            if "/wiki/rest/api/user/watches/content" in url:
                return _mock_response({"results": watched, "size": 1})
            if "/wiki/api/v2/footer-comments" in url:
                return _mock_response({"results": [], "size": 0})
            return _mock_response({"results": []})

        with patch("requests.Session") as MockSession:
            session = MockSession.return_value
            session.get = mock_get

            result = mod.build_snapshot(
                base_url="https://test.atlassian.net",
                auth=("user@test.com", "fake-token"),
            )

        assert result["summary"]["watched_pages"] == 1
        assert result["items"]["watched_pages"][0]["title"] == "Team Roadmap"

    def test_unresolved_comments_filtered(self):
        """Only unresolved (non-resolved) comments are counted."""
        pages = [_make_page("1", "Doc")]
        comments = [
            _make_comment("c1", "1", resolved=False),
            _make_comment("c2", "1", resolved=True),
            _make_comment("c3", "1", resolved=False),
        ]

        def mock_get(url, **kwargs):
            if "/wiki/api/v2/pages" in url:
                return _mock_response({"results": pages, "size": 1})
            if "/wiki/rest/api/user/watches/content" in url:
                return _mock_response({"results": [], "size": 0})
            if "/wiki/api/v2/footer-comments" in url:
                return _mock_response({"results": comments, "size": 3})
            return _mock_response({"results": []})

        with patch("requests.Session") as MockSession:
            session = MockSession.return_value
            session.get = mock_get

            result = mod.build_snapshot(
                base_url="https://test.atlassian.net",
                auth=("user@test.com", "fake-token"),
            )

        assert result["summary"]["unresolved_comments"] == 2

    def test_deduplication_of_watched_and_owned(self):
        """Pages that are both owned and watched appear only in my_pages."""
        page = _make_page("1", "Shared Doc")

        def mock_get(url, **kwargs):
            if "/wiki/api/v2/pages" in url:
                return _mock_response({"results": [page], "size": 1})
            if "/wiki/rest/api/user/watches/content" in url:
                return _mock_response({"results": [page], "size": 1})
            if "/wiki/api/v2/footer-comments" in url:
                return _mock_response({"results": [], "size": 0})
            return _mock_response({"results": []})

        with patch("requests.Session") as MockSession:
            session = MockSession.return_value
            session.get = mock_get

            result = mod.build_snapshot(
                base_url="https://test.atlassian.net",
                auth=("user@test.com", "fake-token"),
            )

        assert result["summary"]["my_pages"] == 1
        assert result["summary"]["watched_pages"] == 0


class TestMain:
    """Tests for the main() entry point."""

    def test_writes_output_file(self, tmp_path):
        """main() writes a date-stamped JSON file to SENSORS_DIR."""
        with patch.object(mod, "SENSORS_DIR", tmp_path), \
             patch.dict("os.environ", {
                 "CONFLUENCE_URL": "https://test.atlassian.net",
                 "CONFLUENCE_USERNAME": "user@test.com",
                 "CONFLUENCE_API_TOKEN": "fake-token",
             }), \
             patch.object(mod, "build_snapshot", return_value={
                 "date": "2026-03-10",
                 "source": "confluence",
                 "summary": {"my_pages": 0, "watched_pages": 0, "unresolved_comments": 0},
                 "items": {"my_pages": [], "watched_pages": [], "unresolved_comments": []},
             }):
            mod.main()

        files = list(tmp_path.glob("confluence-*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["source"] == "confluence"

    def test_exits_on_missing_env(self, tmp_path):
        """main() exits with error when env vars are missing."""
        with patch.object(mod, "SENSORS_DIR", tmp_path), \
             patch.dict("os.environ", {}, clear=True), \
             pytest.raises(SystemExit):
            # Remove env vars to trigger validation
            with patch.dict("os.environ", {
                "CONFLUENCE_URL": "",
                "CONFLUENCE_USERNAME": "",
                "CONFLUENCE_API_TOKEN": "",
            }):
                mod.main()


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp
