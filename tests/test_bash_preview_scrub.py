"""Registered secrets must not reach this hook's stored text, and a failed check must drop it."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / "hooks"
SECRET = "wn_" + "wh_" + "ab" * 32


def load(monkeypatch, guards_dir):
    monkeypatch.setenv("CLAUDE_GUARDS_HOOKS_DIR", str(guards_dir))
    sys.path.insert(0, str(HOOKS))
    monkeypatch.delitem(sys.modules, "secret_policy", raising=False)
    spec = importlib.util.spec_from_file_location("hook_under_test", HOOKS / "obs-posttool-bash.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_failed_check_returns_none_so_text_is_dropped(monkeypatch, tmp_path):
    (tmp_path / "secret_policy.py").write_text("raise RuntimeError('broken')\n")
    assert load(monkeypatch, tmp_path)._scrub_secrets(f"x {SECRET}") is None


def test_registered_secret_is_replaced(monkeypatch, tmp_path):
    (tmp_path / "secret_policy.py").write_text(
        "import re, types\n"
        "def load_policy():\n"
        "    return types.SimpleNamespace(runtime_patterns=[re.compile('wn_[a-z]+_[a-f0-9]+')])\n"
        "def redact_text(text, patterns):\n"
        "    return patterns[0].sub('[R]', text)\n"
    )
    assert load(monkeypatch, tmp_path)._scrub_secrets(f"x {SECRET} y") == "x [R] y"


def test_empty_text_stays_empty(monkeypatch, tmp_path):
    assert load(monkeypatch, tmp_path)._scrub_secrets("") == ""
