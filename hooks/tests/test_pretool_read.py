"""Tests for enrich-pretool-read hook (context window protection)."""
import importlib.util
import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_mod_path = os.path.join(os.path.dirname(__file__), "..", "enrich-pretool-read.py")
_spec = importlib.util.spec_from_file_location("enrich_pretool_read", _mod_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


# =============================================================================
# get_line_count tests
# =============================================================================

class TestGetLineCount:
    def test_returns_count_for_existing_file(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("line1\nline2\nline3\n")
        assert _mod.get_line_count(str(f)) == 3

    def test_returns_none_for_nonexistent_file(self):
        assert _mod.get_line_count("/nonexistent/path/file.py") is None

    def test_returns_zero_for_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        assert _mod.get_line_count(str(f)) == 0

    @patch("subprocess.run")
    def test_returns_none_on_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="wc", timeout=5)
        assert _mod.get_line_count("/some/file.py") is None


# =============================================================================
# Small file skip tests
# =============================================================================

class TestSmallFileSkip:
    """Files <= threshold should be skipped."""

    def test_threshold_boundary(self):
        """Threshold lines exactly should not trigger enrichment."""
        assert _mod._LINES_THRESHOLD == 200

    def test_above_threshold_qualifies(self):
        """501 lines should qualify."""
        assert 501 > _mod._LINES_THRESHOLD


# =============================================================================
# extract_head_tail tests
# =============================================================================

class TestExtractHeadTail:
    def test_small_file_returns_full(self, tmp_path):
        f = tmp_path / "small.py"
        content = "\n".join(f"line {i}" for i in range(100))
        f.write_text(content)
        result = _mod.extract_head_tail(str(f))
        assert result == content

    def test_large_file_returns_head_tail(self, tmp_path):
        f = tmp_path / "large.py"
        lines = [f"line {i}\n" for i in range(1000)]
        f.write_text("".join(lines))
        result = _mod.extract_head_tail(str(f), head=200, tail=200)
        assert result is not None
        assert "line 0" in result
        assert "line 999" in result
        assert "lines omitted" in result

    def test_nonexistent_file_returns_none(self):
        assert _mod.extract_head_tail("/nonexistent/file.py") is None

    def test_empty_file_returns_none(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        assert _mod.extract_head_tail(str(f)) is None

    def test_exact_boundary_no_omission(self, tmp_path):
        """File with exactly head+tail lines should not show omission."""
        f = tmp_path / "boundary.py"
        lines = [f"line {i}\n" for i in range(400)]
        f.write_text("".join(lines))
        result = _mod.extract_head_tail(str(f), head=200, tail=200)
        assert result is not None
        assert "omitted" not in result


# =============================================================================
# call_brick (via brick_common) tests — mocked at the brick_common level
# =============================================================================

class TestCallBrick:
    @patch("brick_common.urllib.request.urlopen")
    def test_returns_summary_on_success(self, mock_urlopen):
        response_data = {
            "tree": {"root": {"content": "This file contains 3 classes..."}}
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from brick_common import call_brick
        summary, reason = call_brick("content", "test-key", intent_key="extract_structure", intent_note="test")
        assert summary == "This file contains 3 classes..."
        assert reason is None

    @patch("brick_common.urllib.request.urlopen")
    def test_returns_none_on_timeout(self, mock_urlopen):
        import socket
        mock_urlopen.side_effect = socket.timeout("timed out")
        from brick_common import call_brick
        summary, reason = call_brick("content", "key", intent_key="extract_structure", intent_note="test")
        assert summary is None
        assert reason == "timeout"

    @patch("brick_common.urllib.request.urlopen")
    def test_returns_none_on_empty_content(self, mock_urlopen):
        response_data = {"tree": {"root": {"content": ""}}}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from brick_common import call_brick
        summary, reason = call_brick("content", "key", intent_key="extract_structure", intent_note="test")
        assert summary is None
        assert reason == "empty_response"

    @patch("brick_common.urllib.request.urlopen")
    def test_returns_none_on_malformed_json(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from brick_common import call_brick
        summary, reason = call_brick("content", "key", intent_key="extract_structure", intent_note="test")
        assert summary is None
        assert reason == "unknown_error"
