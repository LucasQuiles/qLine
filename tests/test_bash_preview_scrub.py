"""Registered secrets must not reach what these hooks store, and a failed check must drop the text."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / "hooks"
SECRET = "wn_" + "wh_" + "ab" * 32
GOOD_POLICY = (
    "import re, types\n"
    "def load_policy(fail_on_error=False):\n"
    "    assert fail_on_error, 'the fallback pattern set would pass most values'\n"
    "    return types.SimpleNamespace(runtime_patterns=[re.compile('wn_[a-z]+_[a-f0-9]+')])\n"
    "def redact_text(text, patterns):\n"
    "    return patterns[0].sub('[R]', text)\n"
)
BROKEN_POLICY = "raise RuntimeError('broken')\n"


def load(monkeypatch, tmp_path, hook_file: str, policy: str):
    (tmp_path / "secret_policy.py").write_text(policy)
    monkeypatch.setenv("CLAUDE_GUARDS_HOOKS_DIR", str(tmp_path))
    monkeypatch.syspath_prepend(str(HOOKS))
    monkeypatch.delitem(sys.modules, "secret_policy", raising=False)
    spec = importlib.util.spec_from_file_location("hook_under_test", HOOKS / hook_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stored: list[object] = []

    def capture(*args, **kwargs):
        stored.append((args, kwargs))
        return True

    for name in ("append_event", "update_health", "record_error", "_atomic_jsonl_append"):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, capture)
    return module, stored


BASH_EVENT = {
    "tool_name": "Bash",
    "tool_use_id": "t",
    "tool_input": {"command": f"run {SECRET}"},
    "tool_response": {"stdout": f"out {SECRET}", "stderr": f"err {SECRET}"},
}
FAILURE_EVENT = {
    "tool_name": "Bash",
    "tool_use_id": "t",
    "error": f"Exit code 1\n{SECRET}",
    "tool_input": {"command": f"run {SECRET}"},
}


@pytest.mark.parametrize(
    ("hook_file", "event"),
    [("obs-posttool-bash.py", BASH_EVENT), ("obs-posttool-failure.py", FAILURE_EVENT)],
)
def test_stored_text_has_the_secret_replaced(monkeypatch, tmp_path, hook_file, event):
    module, stored = load(monkeypatch, tmp_path, hook_file, GOOD_POLICY)
    module._handle(event, "s", str(tmp_path))
    text = json.dumps(stored, default=str)
    assert stored and SECRET not in text and "[R]" in text


@pytest.mark.parametrize(
    ("hook_file", "event"),
    [("obs-posttool-bash.py", BASH_EVENT), ("obs-posttool-failure.py", FAILURE_EVENT)],
)
def test_failed_check_drops_the_text_and_still_records_the_call(monkeypatch, tmp_path, hook_file, event):
    module, stored = load(monkeypatch, tmp_path, hook_file, BROKEN_POLICY)
    module._handle(event, "s", str(tmp_path))
    text = json.dumps(stored, default=str)
    assert stored and SECRET not in text and "[R]" not in text
