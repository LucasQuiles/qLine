# hooks/tests/test_precompact_producers.py
"""Tests for the five PreCompact producers."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

HOOKS_DIR = os.path.join(os.path.dirname(__file__), "..")


class TestPreserveProducer:
    def test_formats_open_tasks_matching_legacy_format(self, monkeypatch):
        import precompact_producers as P
        monkeypatch.setattr(P, "iter_open_tasks",
                            lambda sid: [({"id": "10", "subject": "do x", "status": "pending"}, "f")])
        monkeypatch.setattr(P, "find_latest_plan", lambda: "2026-06-19-thing.md")
        section = P.produce_preserve({"session_id": "s"})
        assert section["open_tasks"].startswith("Open tasks (1):")
        assert "[pending] #10: do x" in section["open_tasks"]
        assert section["active_plan"] == "2026-06-19-thing.md"

    def test_returns_none_when_nothing(self, monkeypatch):
        import precompact_producers as P
        monkeypatch.setattr(P, "iter_open_tasks", lambda sid: [])
        monkeypatch.setattr(P, "find_latest_plan", lambda: None)
        assert P.produce_preserve({"session_id": "s"}) is None


class TestFailuresProducer:
    # Failures come from `tool.failed` obs events (the action-ledger has NO exit
    # status). Success events are NOT in that stream, so v1 reports distinct
    # failed commands this session, deduped by command_hash. Informational.
    def test_reports_distinct_failed_commands(self, monkeypatch):
        import precompact_producers as P
        fails = [
            {"event": "tool.failed", "command_preview": "ruff check", "command_hash": "a1"},
            {"event": "tool.failed", "command_preview": "ruff check", "command_hash": "a1"},
            {"event": "tool.failed", "command_preview": "pytest -q", "command_hash": "b2"},
        ]
        monkeypatch.setattr(P, "read_session_failed_commands", lambda sid: fails)
        section = P.produce_failures({"session_id": "s"})
        assert section["unresolved_failures"] == ["ruff check", "pytest -q"]  # deduped

    def test_none_when_no_failures(self, monkeypatch):
        import precompact_producers as P
        monkeypatch.setattr(P, "read_session_failed_commands", lambda sid: [])
        assert P.produce_failures({"session_id": "s"}) is None

    def test_redacts_secrets_and_truncates_preview(self, monkeypatch):
        import precompact_producers as P
        fails = [
            {"event": "tool.failed",
             "command_preview": 'curl -H "Authorization: Bearer sk-abcdEFGH12345678" https://x',
             "command_hash": "c3"},
            {"event": "tool.failed",
             "command_preview": "psql --password=SuperSecret123 -c 'select 1'",
             "command_hash": "d4"},
        ]
        monkeypatch.setattr(P, "read_session_failed_commands", lambda sid: fails)
        out = P.produce_failures({"session_id": "s"})["unresolved_failures"]
        joined = " ".join(out)
        assert "sk-abcdEFGH12345678" not in joined
        assert "SuperSecret123" not in joined
        assert "<redacted>" in joined
        # signal preserved: the program name survives redaction
        assert "curl" in joined and "psql" in joined

    def test_preview_is_length_capped(self, monkeypatch):
        import precompact_producers as P
        from precompact_producers import _PREVIEW_MAX_CHARS
        fails = [{"event": "tool.failed", "command_preview": "echo " + "a" * 500,
                  "command_hash": "e5"}]
        monkeypatch.setattr(P, "read_session_failed_commands", lambda sid: fails)
        out = P.produce_failures({"session_id": "s"})["unresolved_failures"]
        assert len(out[0]) <= _PREVIEW_MAX_CHARS


class TestStatsProducer:
    def test_counts_tools(self, monkeypatch):
        import precompact_producers as P
        actions = [{"tool": "Bash"}, {"tool": "Bash"}, {"tool": "Read"}]
        monkeypatch.setattr(P, "read_session_actions", lambda sid, **k: actions)
        section = P.produce_stats({"session_id": "s"})
        assert section["session_stats"]["Bash"] == 2
        assert section["session_stats"]["Read"] == 1


class TestHandoffProducer:
    def test_reads_note(self, monkeypatch):
        import precompact_producers as P
        monkeypatch.setattr(P, "read_note", lambda sid: "next: wire tests")
        assert P.produce_handoff({"session_id": "s"})["handoff_note"] == "next: wire tests"

    def test_none_when_no_note(self, monkeypatch):
        import precompact_producers as P
        monkeypatch.setattr(P, "read_note", lambda sid: None)
        assert P.produce_handoff({"session_id": "s"}) is None


class TestCLIDispatcher:
    def test_cli_emits_json_section_on_stdout(self):
        # stats over an empty session -> None -> CLI prints "null"
        payload = json.dumps({"session_id": "no-such-session-xyz"})
        proc = subprocess.run(
            [sys.executable, os.path.join(HOOKS_DIR, "precompact_producers.py"),
             "stats", "--json-out"],
            input=payload, capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode == 0
        # Valid JSON (either null or an object)
        json.loads(proc.stdout.strip() or "null")

    def test_cli_unknown_producer_exits_nonzero(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(HOOKS_DIR, "precompact_producers.py"),
             "bogus", "--json-out"],
            input="{}", capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode != 0
