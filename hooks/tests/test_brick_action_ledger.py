"""Tests for brick_action_ledger — action logging and mark_enriched matching."""

import json
import os
import tempfile

import pytest

# Ensure hooks dir is importable
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import brick_action_ledger as bal


@pytest.fixture()
def ledger_file(tmp_path, monkeypatch):
    """Create a temp ledger file and patch LEDGER_PATH."""
    path = tmp_path / "action-ledger.jsonl"
    monkeypatch.setattr(bal, "LEDGER_PATH", path)
    return path


def _write_entries(ledger_file, entries):
    """Write ledger entries as JSONL."""
    with open(ledger_file, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


class TestMarkEnriched:
    """Tests for mark_enriched() matching precision."""

    def test_match_by_action_id_exact(self, ledger_file):
        """action_id match updates exactly one entry."""
        entries = [
            {"v": 1, "action_id": "aaa111", "session_id": "s1", "tool": "Bash", "enriched": False},
            {"v": 1, "action_id": "bbb222", "session_id": "s1", "tool": "Bash", "enriched": False},
            {"v": 1, "action_id": "ccc333", "session_id": "s1", "tool": "Read", "enriched": False},
        ]
        _write_entries(ledger_file, entries)

        updated = bal.mark_enriched(session_id="s1", tool="Bash", action_id="bbb222", trace_id="t1")

        assert updated == 1
        lines = [json.loads(l) for l in ledger_file.read_text().splitlines() if l.strip()]
        assert lines[0]["enriched"] is False  # aaa111 untouched
        assert lines[1]["enriched"] is True   # bbb222 matched
        assert lines[1]["trace_id"] == "t1"
        assert lines[2]["enriched"] is False  # ccc333 untouched

    def test_fallback_session_tool_when_no_action_id(self, ledger_file):
        """Without action_id, falls back to session_id + tool (matches multiple)."""
        entries = [
            {"v": 1, "action_id": "aaa111", "session_id": "s1", "tool": "Bash", "enriched": False},
            {"v": 1, "action_id": "bbb222", "session_id": "s1", "tool": "Bash", "enriched": False},
            {"v": 1, "action_id": "ccc333", "session_id": "s2", "tool": "Bash", "enriched": False},
        ]
        _write_entries(ledger_file, entries)

        updated = bal.mark_enriched(session_id="s1", tool="Bash")

        assert updated == 2  # Both s1/Bash entries matched
        lines = [json.loads(l) for l in ledger_file.read_text().splitlines() if l.strip()]
        assert lines[0]["enriched"] is True
        assert lines[1]["enriched"] is True
        assert lines[2]["enriched"] is False  # Different session

    def test_action_id_no_match(self, ledger_file):
        """action_id that doesn't exist returns 0 updates."""
        entries = [
            {"v": 1, "action_id": "aaa111", "session_id": "s1", "tool": "Bash", "enriched": False},
        ]
        _write_entries(ledger_file, entries)

        updated = bal.mark_enriched(session_id="s1", tool="Bash", action_id="zzz999")

        assert updated == 0
        lines = [json.loads(l) for l in ledger_file.read_text().splitlines() if l.strip()]
        assert lines[0]["enriched"] is False

    def test_already_enriched_skipped(self, ledger_file):
        """Already enriched entries are not re-matched."""
        entries = [
            {"v": 1, "action_id": "aaa111", "session_id": "s1", "tool": "Bash", "enriched": True},
            {"v": 1, "action_id": "bbb222", "session_id": "s1", "tool": "Bash", "enriched": False},
        ]
        _write_entries(ledger_file, entries)

        updated = bal.mark_enriched(session_id="s1", tool="Bash", action_id="aaa111")

        assert updated == 0  # Already enriched

    def test_empty_ledger(self, ledger_file):
        """No file returns 0."""
        updated = bal.mark_enriched(session_id="s1", tool="Bash", action_id="aaa111")
        assert updated == 0

    def test_trace_id_stored(self, ledger_file):
        """trace_id is written into matched entries."""
        entries = [
            {"v": 1, "action_id": "aaa111", "session_id": "s1", "tool": "Bash", "enriched": False},
        ]
        _write_entries(ledger_file, entries)

        bal.mark_enriched(session_id="s1", tool="Bash", action_id="aaa111", trace_id="tr-abc")

        lines = [json.loads(l) for l in ledger_file.read_text().splitlines() if l.strip()]
        assert lines[0]["trace_id"] == "tr-abc"


class TestLogAction:
    """Tests for log_action()."""

    def test_log_creates_entry(self, ledger_file):
        aid = bal.log_action(session_id="s1", tool="Read", file_path="/tmp/foo.py", action_id="x123")
        assert aid == "x123"
        lines = [json.loads(l) for l in ledger_file.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        assert lines[0]["action_id"] == "x123"
        assert lines[0]["tool"] == "Read"

    def test_log_generates_id_when_missing(self, ledger_file):
        aid = bal.log_action(session_id="s1", tool="Edit")
        assert len(aid) == 12  # UUID[:12]


class TestDeriveActionId:
    """Tests for derive_action_id()."""

    def test_deterministic(self):
        data = {"session_id": "s1", "tool_name": "Bash", "tool_use_id": "tu_123"}
        id1 = bal.derive_action_id(data)
        id2 = bal.derive_action_id(data)
        assert id1 == id2
        assert len(id1) == 12

    def test_different_tool_use_id_different_result(self):
        d1 = {"session_id": "s1", "tool_name": "Bash", "tool_use_id": "tu_123"}
        d2 = {"session_id": "s1", "tool_name": "Bash", "tool_use_id": "tu_456"}
        assert bal.derive_action_id(d1) != bal.derive_action_id(d2)

    def test_fallback_without_tool_use_id(self):
        data = {"session_id": "s1", "tool_name": "Read", "tool_input": {"file_path": "/tmp/x.py"}}
        aid = bal.derive_action_id(data)
        assert len(aid) == 12
