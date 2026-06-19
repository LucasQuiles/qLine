# hooks/tests/test_precompact_ledger.py
"""Tests for the bounded action-ledger tail reader."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _write_ledger(path, records):
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


class TestReadSessionActions:
    def test_returns_only_matching_session(self, tmp_path):
        from precompact_ledger import read_session_actions
        p = tmp_path / "ledger.jsonl"
        _write_ledger(p, [
            {"session_id": "A", "tool": "Bash", "command": "ls", "ts": "1"},
            {"session_id": "B", "tool": "Read", "file_path": "x", "ts": "2"},
            {"session_id": "A", "tool": "Edit", "file_path": "y", "ts": "3"},
        ])
        actions = read_session_actions("A", ledger_path=str(p))
        assert len(actions) == 2
        assert {a["tool"] for a in actions} == {"Bash", "Edit"}

    def test_bounded_scan_skips_old_records_beyond_byte_budget(self, tmp_path):
        from precompact_ledger import read_session_actions
        p = tmp_path / "ledger.jsonl"
        old = [{"session_id": "OLD", "tool": "Bash", "command": "x" * 200, "ts": str(i)}
               for i in range(20000)]
        recent = [{"session_id": "NEW", "tool": "Edit", "file_path": "z", "ts": "late"}]
        _write_ledger(p, old + recent)
        actions = read_session_actions("NEW", ledger_path=str(p), max_bytes=64 * 1024)
        assert len(actions) == 1  # found in the tail
        assert actions[0]["tool"] == "Edit"

    def test_large_file_completes_under_deadline(self, tmp_path):
        from precompact_ledger import read_session_actions
        from hook_utils import Deadline
        p = tmp_path / "ledger.jsonl"
        big = [{"session_id": "S", "tool": "Bash", "command": "y" * 300, "ts": str(i)}
               for i in range(100000)]
        _write_ledger(p, big)  # ~30 MB
        t0 = time.monotonic()
        actions = read_session_actions("S", ledger_path=str(p),
                                       max_bytes=2 * 1024 * 1024, deadline=Deadline(3.0))
        assert (time.monotonic() - t0) < 3.0
        assert len(actions) > 0  # got the tail of session S

    def test_missing_file_returns_empty(self, tmp_path):
        from precompact_ledger import read_session_actions
        assert read_session_actions("A", ledger_path=str(tmp_path / "nope.jsonl")) == []

    def test_skips_malformed_lines(self, tmp_path):
        from precompact_ledger import read_session_actions
        p = tmp_path / "ledger.jsonl"
        with open(p, "w") as f:
            f.write('{"session_id": "A", "tool": "Bash"}\n')
            f.write("not json at all\n")
            f.write('{"session_id": "A", "tool": "Edit"}\n')
        actions = read_session_actions("A", ledger_path=str(p))
        assert len(actions) == 2
