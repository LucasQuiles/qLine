"""Tests for enrich-posttool-write hook functions."""
import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import will fail until the module exists — that's the TDD red phase.
# We import the helper functions, not the main entry point.


# ---------------------------------------------------------------------------
# Lazy import helper (module created after tests)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _import_module():
    """Import the module under test, available after implementation."""
    global is_code_file, count_lines_changed, should_enrich, CODE_EXTENSIONS
    # Use importlib to avoid caching issues
    import importlib
    mod_path = os.path.join(os.path.dirname(__file__), "..", "enrich-posttool-write.py")
    spec = importlib.util.spec_from_file_location("enrich_posttool_write", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    is_code_file = mod.is_code_file
    count_lines_changed = mod.count_lines_changed
    should_enrich = mod.should_enrich
    CODE_EXTENSIONS = mod.CODE_EXTENSIONS


# ---------------------------------------------------------------------------
# is_code_file tests
# ---------------------------------------------------------------------------

class TestIsCodeFile:
    def test_python(self):
        assert is_code_file("src/main.py") is True

    def test_typescript(self):
        assert is_code_file("app/index.ts") is True

    def test_vue(self):
        assert is_code_file("components/App.vue") is True

    def test_markdown_excluded(self):
        assert is_code_file("README.md") is False

    def test_json_excluded(self):
        assert is_code_file("package.json") is False

    def test_css_excluded(self):
        assert is_code_file("styles/main.css") is False

    def test_no_extension(self):
        assert is_code_file("Makefile") is False

    def test_tsx(self):
        assert is_code_file("components/Button.tsx") is True

    def test_shell(self):
        assert is_code_file("scripts/deploy.sh") is True


# ---------------------------------------------------------------------------
# count_lines_changed tests
# ---------------------------------------------------------------------------

class TestCountLinesChanged:
    def test_write_tool(self):
        data = {
            "tool_name": "Write",
            "tool_input": {
                "content": "line1\nline2\nline3\n",
            },
        }
        assert count_lines_changed(data) == 3

    def test_edit_tool(self):
        data = {
            "tool_name": "Edit",
            "tool_input": {
                "new_string": "a\nb\nc",
            },
        }
        assert count_lines_changed(data) == 3

    def test_multiedit_tool(self):
        data = {
            "tool_name": "MultiEdit",
            "tool_input": {
                "new_string": "x\ny",
            },
        }
        assert count_lines_changed(data) == 2

    def test_unknown_tool_returns_zero(self):
        data = {"tool_name": "Read", "tool_input": {}}
        assert count_lines_changed(data) == 0

    def test_empty_content(self):
        data = {"tool_name": "Write", "tool_input": {"content": ""}}
        assert count_lines_changed(data) == 0


# ---------------------------------------------------------------------------
# should_enrich tests
# ---------------------------------------------------------------------------

class TestShouldEnrich:
    def test_large_code_write(self):
        assert should_enrich("Write", "app.py", 25) is True

    def test_small_change_skipped(self):
        assert should_enrich("Write", "app.py", 10) is False

    def test_threshold_boundary(self):
        assert should_enrich("Write", "app.py", 20) is False
        assert should_enrich("Write", "app.py", 21) is True

    def test_non_code_file_skipped(self):
        assert should_enrich("Write", "data.json", 50) is False

    def test_wrong_tool_skipped(self):
        assert should_enrich("Read", "app.py", 50) is False


# ---------------------------------------------------------------------------
# call_brick (via brick_common) tests — mocked at the brick_common level
# ---------------------------------------------------------------------------

class TestCallBrick:
    @patch("brick_common.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        response_data = {
            "tree": {
                "root": {
                    "content": "No issues found."
                }
            }
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from brick_common import call_brick
        summary, reason = call_brick("some code", "test-key", intent_key="flag_risks", intent_note="test")
        assert summary == "No issues found."
        assert reason is None

    @patch("brick_common.urllib.request.urlopen")
    def test_timeout(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("timed out")
        from brick_common import call_brick
        summary, reason = call_brick("some code", "test-key", intent_key="flag_risks", intent_note="test")
        assert summary is None
        assert reason == "timeout"

    @patch("brick_common.urllib.request.urlopen")
    def test_http_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://example.com", code=500, msg="ISE", hdrs={}, fp=None
        )
        from brick_common import call_brick
        summary, reason = call_brick("some code", "test-key", intent_key="flag_risks", intent_note="test")
        assert summary is None
        assert reason == "http_500"
