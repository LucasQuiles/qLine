#!/usr/bin/env python3
"""Versioned diagnostics and bounded JSONL evidence parsing."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import context_overhead  # noqa: E402
import statusline  # noqa: E402


def _diag_path(root: Path) -> Path:
    return root / "native" / "statusline" / "diagnostics.jsonl"


def test_shared_envelope_counts_only_parse_diagnostics(tmp_path: Path) -> None:
    context_overhead._diag_write_count = 0
    context_overhead._write_parse_diag(
        str(tmp_path), "transcript_tail", "JSONDecodeError: bad", "{bad"
    )
    assert statusline._write_statusline_diag(
        str(tmp_path), "render_latency_write_failed", "PermissionError"
    )

    rows = [json.loads(line) for line in _diag_path(tmp_path).read_text().splitlines()]
    assert {row["schema_version"] for row in rows} == {
        context_overhead.DIAGNOSTIC_SCHEMA_VERSION
    }
    assert {row["producer"] for row in rows} == {"context_overhead", "statusline"}
    assert {row["severity"] for row in rows} == {"warning"}
    assert rows[0]["payload"] == {
        "line_preview": "{bad",
        "source": "transcript_tail",
    }
    assert statusline._count_parse_errors(str(tmp_path)) == 1
    summary = context_overhead.read_diagnostic_summary(str(tmp_path))
    assert summary["counts"] == {
        "render_latency_write_failed": 1,
        "transcript_json_invalid": 1,
    }
    assert summary["malformed"] == 0
    assert summary["unknown_schema"] == 0
    assert stat.S_IMODE(_diag_path(tmp_path).stat().st_mode) == 0o600


def test_legacy_parse_rows_remain_readable_but_other_legacy_rows_do_not_inflate_count(
    tmp_path: Path,
) -> None:
    path = _diag_path(tmp_path)
    path.parent.mkdir(parents=True)
    rows = [
        {"ts": "now", "source": "tail", "error": "bad", "line_preview": "x"},
        {"ts": "now", "event": "render_latency_write", "detail": "OSError"},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    assert statusline._count_parse_errors(str(tmp_path)) == 1
    summary = context_overhead.read_diagnostic_summary(str(tmp_path))
    assert summary["counts"]["transcript_json_invalid"] == 1
    assert summary["legacy"] == 2


def test_malformed_and_unknown_schema_are_classified_not_counted_as_parse_errors(
    tmp_path: Path,
) -> None:
    path = _diag_path(tmp_path)
    path.parent.mkdir(parents=True)
    unknown = {
        "schema_version": "2.0.0",
        "ts": "now",
        "producer": "future",
        "code": "transcript_json_invalid",
        "severity": "warning",
        "detail": "future",
        "payload": {},
    }
    path.write_text("not-json\n" + json.dumps(unknown) + "\n", encoding="utf-8")

    summary = context_overhead.read_diagnostic_summary(str(tmp_path))
    assert summary["malformed"] == 1
    assert summary["unknown_schema"] == 1
    assert summary["counts"] == {}
    assert statusline._count_parse_errors(str(tmp_path)) == 0


def test_diagnostic_writer_enforces_per_invocation_and_file_bounds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    context_overhead._diag_write_count = 0
    monkeypatch.setattr(context_overhead, "DIAGNOSTIC_MAX_PER_INVOCATION", 2)
    assert context_overhead.write_diagnostic(
        str(tmp_path), "test", "first", "info", "one"
    )
    assert context_overhead.write_diagnostic(
        str(tmp_path), "test", "second", "warning", "two"
    )
    assert not context_overhead.write_diagnostic(
        str(tmp_path), "test", "third", "error", "three"
    )
    assert len(_diag_path(tmp_path).read_text().splitlines()) == 2

    context_overhead._diag_write_count = 0
    monkeypatch.setattr(context_overhead, "DIAGNOSTIC_MAX_FILE_BYTES", 1)
    assert not context_overhead.write_diagnostic(
        str(tmp_path), "test", "bounded", "warning", "too large for file"
    )
    assert len(_diag_path(tmp_path).read_text().splitlines()) == 2


def test_diagnostic_writer_checks_the_locked_file_size_before_appending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _diag_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x" * 500)
    before = path.read_bytes()
    context_overhead._diag_write_count = 0
    monkeypatch.setattr(context_overhead, "DIAGNOSTIC_MAX_FILE_BYTES", 512)
    monkeypatch.setattr(context_overhead.os.path, "getsize", lambda _path: 0)

    assert not context_overhead.write_diagnostic(
        str(tmp_path), "test", "bounded", "warning", "must not cross the cap"
    )
    assert path.read_bytes() == before


def test_event_counter_parses_json_instead_of_matching_substrings(tmp_path: Path) -> None:
    ledger = tmp_path / "metadata" / "hook_events.jsonl"
    ledger.parent.mkdir()
    rows = [
        {"event": "prompt.observed", "data": {"text": '\"event\": \"tool.failed\"'}},
        {"event": "bash.executed"},
        {"data": {"event": "nested.only"}},
    ]
    ledger.write_text(
        "".join(json.dumps(row) + "\n" for row in rows) + "{malformed\n",
        encoding="utf-8",
    )
    context_overhead._diag_write_count = 0

    counts = statusline._count_obs_events(str(tmp_path))

    assert counts == {"prompt.observed": 1, "bash.executed": 1}
    summary = context_overhead.read_diagnostic_summary(str(tmp_path))
    assert summary["counts"]["ledger_record_malformed"] == 2


def test_event_counter_reports_an_unreadable_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "metadata" / "hook_events.jsonl"
    ledger.mkdir(parents=True)
    context_overhead._diag_write_count = 0

    assert statusline._count_obs_events(str(tmp_path)) == {}
    summary = context_overhead.read_diagnostic_summary(str(tmp_path))
    assert summary["counts"]["ledger_unreadable"] == 1


def test_reread_counter_parses_json_and_classifies_bad_rows(tmp_path: Path) -> None:
    reads = tmp_path / "custom" / "reads.jsonl"
    reads.parent.mkdir()
    rows = [
        {"is_reread": True},
        {"is_reread": False, "note": '\"is_reread\": true'},
        {"note": "missing boolean"},
    ]
    reads.write_text(
        "".join(json.dumps(row) + "\n" for row in rows) + "{bad\n",
        encoding="utf-8",
    )
    context_overhead._diag_write_count = 0

    assert statusline._count_rereads(str(tmp_path)) == (2, 1)
    summary = context_overhead.read_diagnostic_summary(str(tmp_path))
    assert summary["counts"]["read_record_malformed"] == 2


def test_runtime_diagnostic_summary_is_deduplicated_and_detail_is_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(statusline, "_RUNTIME_DIAGNOSTICS", {})
    monkeypatch.setattr(statusline, "NO_COLOR", True)
    statusline._record_runtime_diagnostic("cache_read_invalid", "JSONDecodeError")
    statusline._record_runtime_diagnostic("cache_read_invalid", "another instance")

    compact = statusline.render_degraded({}, statusline.DEFAULT_THEME)
    assert compact is not None and "diag 1" in compact
    assert "cache_read_invalid" not in compact

    monkeypatch.setenv("QLINE_DIAGNOSTICS_VERBOSE", "1")
    verbose = statusline.render_degraded({}, statusline.DEFAULT_THEME)
    assert verbose is not None and "cache_read_invalid" in verbose
    assert "JSONDecodeError" not in verbose


def test_invalid_cache_and_unknown_diagnostic_schema_become_visible_reason_codes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(statusline, "_RUNTIME_DIAGNOSTICS", {})
    cache = tmp_path / "cache.json"
    cache.write_text("{bad", encoding="utf-8")
    monkeypatch.setattr(statusline, "CACHE_PATH", str(cache))

    assert statusline.load_cache() == {}
    assert "cache_read_invalid" in statusline._RUNTIME_DIAGNOSTICS

    path = _diag_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"schema_version": "9.0.0", "code": "future"}) + "\n",
        encoding="utf-8",
    )
    assert statusline._count_parse_errors(str(tmp_path)) == 0
    assert "diagnostic_schema_unknown" in statusline._RUNTIME_DIAGNOSTICS
