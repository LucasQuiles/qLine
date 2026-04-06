"""Tests for brick_common shared utilities."""
import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from brick_common import (
    get_brick_api_key,
    call_brick,
    generate_enrichment_id,
    build_enrichment_context,
    make_ssl_context,
)


class TestGetBrickApiKey:
    def test_from_env(self):
        with patch.dict(os.environ, {"BRICK_API_KEY": "test-key-123"}):
            assert get_brick_api_key() == "test-key-123"

    def test_from_keyring(self):
        with patch.dict(os.environ, {}, clear=False):
            env = {k: v for k, v in os.environ.items() if k != "BRICK_API_KEY"}
            with patch.dict(os.environ, env, clear=True):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stdout="keyring-key\n")
                    assert get_brick_api_key() == "keyring-key"

    def test_returns_none_when_unavailable(self):
        with patch.dict(os.environ, {}, clear=False):
            env = {k: v for k, v in os.environ.items() if k != "BRICK_API_KEY"}
            with patch.dict(os.environ, env, clear=True):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=1, stdout="")
                    assert get_brick_api_key() is None


class TestCallBrick:
    @patch("urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        response_data = {"tree": {"root": {"content": "Analysis complete."}}}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        summary, reason = call_brick("code here", "key", intent_key="flag_risks")
        assert summary == "Analysis complete."
        assert reason is None

    @patch("urllib.request.urlopen")
    def test_timeout(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("timed out")
        summary, reason = call_brick("code", "key")
        assert summary is None
        assert reason == "timeout"

    @patch("urllib.request.urlopen")
    def test_http_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://x", code=422, msg="", hdrs={}, fp=None
        )
        summary, reason = call_brick("code", "key")
        assert summary is None
        assert reason == "http_422"

    @patch("urllib.request.urlopen")
    def test_empty_response(self, mock_urlopen):
        response_data = {"tree": {"root": {"content": ""}}}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        summary, reason = call_brick("code", "key")
        assert summary is None
        assert reason == "empty_response"


class TestGenerateEnrichmentId:
    def test_length(self):
        eid = generate_enrichment_id()
        assert len(eid) == 12

    def test_unique(self):
        ids = {generate_enrichment_id() for _ in range(100)}
        assert len(ids) == 100


class TestBuildEnrichmentContext:
    def test_read_context(self):
        ctx = build_enrichment_context(
            "Read", "/src/app.py", "3 classes found", "abc123",
            extra_info="500 lines",
        )
        assert "\U0001f9f1 Brick enriched Read:" in ctx
        assert "/src/app.py" in ctx
        assert "500 lines" in ctx
        assert "enrichment_id=abc123" in ctx
        assert "3 classes found" in ctx

    def test_write_context(self):
        ctx = build_enrichment_context(
            "Write", "/src/app.py", "Missing null check", "def456",
        )
        assert "\U0001f9f1 Brick enriched Write:" in ctx
        assert "enrichment_id=def456" in ctx

    def test_commit_context_no_file(self):
        ctx = build_enrichment_context(
            "Commit", "", "Use feat: prefix", "ghi789",
        )
        assert "\U0001f9f1 Brick enriched Commit:" in ctx
        assert "enrichment_id=ghi789" in ctx

    def test_pr_context(self):
        ctx = build_enrichment_context(
            "PR", "", "Add summary section", "jkl012",
        )
        assert "\U0001f9f1 Brick enriched PR:" in ctx


class TestMakeSslContext:
    def test_creates_context(self):
        ctx = make_ssl_context()
        assert ctx.check_hostname is False
