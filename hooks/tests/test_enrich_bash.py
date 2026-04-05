"""Tests for enrich-posttool-bash spool hook functions."""
import importlib.util
import json
import os
import sys

import pytest

# Import the hyphenated module via importlib
_hook_path = os.path.join(os.path.dirname(__file__), "..", "enrich-posttool-bash.py")
_spec = importlib.util.spec_from_file_location("enrich_posttool_bash", _hook_path)
_mod = importlib.util.module_from_spec(_spec)

# Patch sys.path so hook_utils is importable during module load
sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_spec.loader.exec_module(_mod)

estimate_tokens = _mod.estimate_tokens
should_spool_bash = _mod.should_spool_bash
should_spool_agent = _mod.should_spool_agent
write_spool_entry = _mod.write_spool_entry


# --- estimate_tokens ---

class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens("") == 0

    def test_known_length(self):
        assert estimate_tokens("a" * 400) == 100


# --- should_spool_bash ---

class TestShouldSpoolBash:
    def test_large_triggers(self):
        # 8001 tokens = 32004 chars
        assert should_spool_bash("x" * 32_004) is True

    def test_small_skips(self):
        assert should_spool_bash("short output") is False

    def test_boundary_at_8k_tokens(self):
        # Exactly 8000 tokens = 32000 chars → NOT > 8000, so False
        assert should_spool_bash("x" * 32_000) is False
        # 8001 tokens = 32004 chars → True
        assert should_spool_bash("x" * 32_004) is True


# --- should_spool_agent ---

class TestShouldSpoolAgent:
    def test_large_triggers(self):
        # 4001 tokens = 16004 chars
        assert should_spool_agent("x" * 16_004, failed=False) is True

    def test_small_skips(self):
        assert should_spool_agent("small", failed=False) is False

    def test_failed_always_triggers(self):
        assert should_spool_agent("", failed=True) is True
        assert should_spool_agent("tiny", failed=True) is True

    def test_boundary_at_4k_tokens(self):
        # Exactly 4000 tokens = 16000 chars → NOT > 4000, so False
        assert should_spool_agent("x" * 16_000, failed=False) is False
        # 4001 tokens = 16004 chars → True
        assert should_spool_agent("x" * 16_004, failed=False) is True


# --- write_spool_entry ---

class TestWriteSpoolEntry:
    def test_creates_files(self, tmp_path):
        spool_root = str(tmp_path / "spool")
        write_spool_entry(spool_root, "Bash", "hello world", "sess-1", "trace-abc")

        # Check pending JSON
        pending_path = os.path.join(spool_root, "pending", "trace-abc.json")
        assert os.path.exists(pending_path)
        entry = json.loads(open(pending_path).read())
        assert entry["tool"] == "Bash"
        assert entry["session_id"] == "sess-1"
        assert entry["trace_id"] == "trace-abc"
        assert entry["retry_count"] == 0
        assert "timestamp" in entry

        # Check raw file
        raw_path = os.path.join(spool_root, "trace-abc.raw")
        assert os.path.exists(raw_path)
        assert open(raw_path).read() == "hello world"

        # Verify output_path in entry points to raw
        assert entry["output_path"] == raw_path

    def test_creates_directories(self, tmp_path):
        spool_root = str(tmp_path / "deep" / "nested" / "spool")
        write_spool_entry(spool_root, "Agent", "data", "s2", "t2")
        assert os.path.exists(os.path.join(spool_root, "pending", "t2.json"))
        assert os.path.exists(os.path.join(spool_root, "t2.raw"))
