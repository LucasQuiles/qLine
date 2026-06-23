"""T6: coverage for hook_utils.run_fail_open — the fail-open crash-resistance
wrapper that EVERY obs hook and both enforcement gates run their main() inside.

It had zero coverage despite carrying subtle, load-bearing contracts:
  * a real Exception is caught -> fault logged -> exit 0 (the fail-open promise)
  * SystemExit is NOT caught -> propagates unchanged (this is WHY task-completed-
    gate's sys.exit(2) survives the wrapper and actually blocks)
  * the finally block always records perf timing when a session_id is supplied,
    even when main() crashed
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _read_ledger(path):
    if not os.path.exists(path):
        return []
    return [json.loads(ln) for ln in open(path).read().splitlines() if ln.strip()]


def test_happy_path_returns_without_exit_or_fault(tmp_path, monkeypatch):
    """A clean main() neither raises nor logs a fault (run_fail_open does not
    sys.exit on success — the process ends naturally with code 0)."""
    import hook_utils
    ledger = tmp_path / "faults.jsonl"
    monkeypatch.setattr(hook_utils, "_LEDGER_PATH", str(ledger))
    calls = []
    hook_utils.run_fail_open(lambda: calls.append("ran"), "h", "E")
    assert calls == ["ran"]
    assert _read_ledger(str(ledger)) == []


def test_exception_caught_logs_fault_and_exits_0(tmp_path, monkeypatch):
    import hook_utils
    ledger = tmp_path / "faults.jsonl"
    monkeypatch.setattr(hook_utils, "_LEDGER_PATH", str(ledger))

    def _boom():
        raise ValueError("kaboom")

    with pytest.raises(SystemExit) as ei:
        hook_utils.run_fail_open(_boom, "crashy-hook", "PostToolUse")
    assert ei.value.code == 0  # fail-open: crash still exits 0

    records = _read_ledger(str(ledger))
    faults = [r for r in records if r.get("level") == "fault"]
    assert faults, f"a crash must log a fault record, got {records}"
    assert faults[0]["reason_class"] == "unhandled_exception"
    assert faults[0]["hook"] == "crashy-hook"
    assert "kaboom" in faults[0]["message"]


def test_systemexit_nonzero_propagates_uncaught(tmp_path, monkeypatch):
    """SystemExit(2) from main() must pass through unchanged (not swallowed to 0)
    and must NOT be logged as a fault — this is the contract that lets the strict
    task-completed-gate exit 2 and actually block."""
    import hook_utils
    ledger = tmp_path / "faults.jsonl"
    monkeypatch.setattr(hook_utils, "_LEDGER_PATH", str(ledger))

    with pytest.raises(SystemExit) as ei:
        hook_utils.run_fail_open(lambda: sys.exit(2), "gate", "TaskCompleted")
    assert ei.value.code == 2
    assert _read_ledger(str(ledger)) == [], "SystemExit must not be logged as a fault"


def test_systemexit_zero_propagates(tmp_path, monkeypatch):
    import hook_utils
    ledger = tmp_path / "faults.jsonl"
    monkeypatch.setattr(hook_utils, "_LEDGER_PATH", str(ledger))
    with pytest.raises(SystemExit) as ei:
        hook_utils.run_fail_open(lambda: sys.exit(0), "gate", "SubagentStop")
    assert ei.value.code == 0
    assert _read_ledger(str(ledger)) == []


def test_perf_recorded_only_when_session_id_present(tmp_path, monkeypatch):
    import hook_utils
    perf_calls = []
    monkeypatch.setattr(hook_utils, "_write_hook_perf",
                        lambda sid, h, e, ms: perf_calls.append((sid, h, e, ms)))

    # with session_id -> perf recorded
    hook_utils.run_fail_open(lambda: None, "h", "E", session_id="sess-1")
    assert len(perf_calls) == 1
    sid, h, e, ms = perf_calls[0]
    assert sid == "sess-1" and h == "h" and e == "E"
    assert isinstance(ms, float) and ms >= 0

    # without session_id -> perf not recorded
    perf_calls.clear()
    hook_utils.run_fail_open(lambda: None, "h", "E")
    assert perf_calls == []


def test_finally_records_perf_even_when_main_crashes(tmp_path, monkeypatch):
    """The finally block runs the perf write even when main() raised and the
    wrapper is exiting 0 — timing is recorded for crashed hooks too."""
    import hook_utils
    ledger = tmp_path / "faults.jsonl"
    monkeypatch.setattr(hook_utils, "_LEDGER_PATH", str(ledger))
    perf_calls = []
    monkeypatch.setattr(hook_utils, "_write_hook_perf",
                        lambda *a: perf_calls.append(a))

    def _boom():
        raise RuntimeError("down")

    with pytest.raises(SystemExit) as ei:
        hook_utils.run_fail_open(_boom, "h", "E", session_id="sess-2")
    assert ei.value.code == 0
    assert len(perf_calls) == 1            # finally ran despite the crash
    assert _read_ledger(str(ledger))        # and the fault was still logged
