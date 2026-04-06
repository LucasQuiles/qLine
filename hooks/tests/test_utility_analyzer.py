"""Tests for brick_utility_analyzer — verifiable utility metrics."""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from brick_utility_analyzer import (
    compute_context_protection,
    compute_quality_gate,
    compute_session_continuity,
)


def write_jsonl(path: Path, entries: list[dict]) -> None:
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


class TestContextProtection:
    def test_enriched_file_fewer_rereads(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        metrics = tmp_path / "metrics.jsonl"

        write_jsonl(ledger, [
            {"session_id": "s1", "tool": "Read", "file_path": "/big.py", "read_count": 1, "enriched": True, "ts": "2026-04-06T01:00:00"},
            {"session_id": "s1", "tool": "Edit", "file_path": "/big.py", "ts": "2026-04-06T01:00:10"},
        ])
        write_jsonl(metrics, [
            {"hook": "read", "session_id": "s1", "file_path": "/big.py", "action": "enriched", "lines_changed": 500, "ts": "2026-04-06T01:00:00"},
        ])

        result = compute_context_protection(ledger, metrics)
        assert result["enriched_avg_reads"] == 1.0
        assert result["enriched_file_count"] >= 1

    def test_unenriched_file_more_rereads(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        metrics = tmp_path / "metrics.jsonl"

        write_jsonl(ledger, [
            {"session_id": "s1", "tool": "Read", "file_path": "/big.py", "read_count": 1, "enriched": False, "ts": "2026-04-06T01:00:00"},
            {"session_id": "s1", "tool": "Read", "file_path": "/big.py", "read_count": 2, "enriched": False, "ts": "2026-04-06T01:01:00"},
            {"session_id": "s1", "tool": "Read", "file_path": "/big.py", "read_count": 3, "enriched": False, "ts": "2026-04-06T01:02:00"},
        ])
        write_jsonl(metrics, [
            {"hook": "read", "session_id": "s1", "file_path": "/big.py", "action": "skipped", "reason": "circuit_breaker", "lines_changed": 500, "ts": "2026-04-06T01:00:00"},
        ])

        result = compute_context_protection(ledger, metrics)
        assert result["unenriched_avg_reads"] == 3.0

    def test_empty_data_returns_zeroes(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        metrics = tmp_path / "metrics.jsonl"
        ledger.write_text("")
        metrics.write_text("")
        result = compute_context_protection(ledger, metrics)
        assert result["enriched_avg_reads"] == 0.0
        assert result["unenriched_avg_reads"] == 0.0


class TestQualityGate:
    def test_enriched_write_with_followup(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        metrics = tmp_path / "metrics.jsonl"

        write_jsonl(metrics, [
            {"hook": "write", "session_id": "s1", "file_path": "/app.py", "action": "enriched",
             "enrichment_id": "eid1", "findings_preview": "Missing null check", "ts": "2026-04-06T01:00:00"},
        ])
        write_jsonl(ledger, [
            {"session_id": "s1", "tool": "Write", "file_path": "/app.py", "ts": "2026-04-06T01:00:00"},
            {"session_id": "s1", "tool": "Edit", "file_path": "/app.py", "ts": "2026-04-06T01:00:30"},
        ])

        result = compute_quality_gate(ledger, metrics)
        assert result["enriched_followup_rate"] > 0.0

    def test_unenriched_write_no_followup(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        metrics = tmp_path / "metrics.jsonl"

        write_jsonl(metrics, [
            {"hook": "write", "session_id": "s1", "file_path": "/app.py", "action": "skipped",
             "reason": "circuit_open", "ts": "2026-04-06T01:00:00"},
        ])
        write_jsonl(ledger, [
            {"session_id": "s1", "tool": "Write", "file_path": "/app.py", "ts": "2026-04-06T01:00:00"},
            {"session_id": "s1", "tool": "Read", "file_path": "/other.py", "ts": "2026-04-06T01:00:30"},
        ])

        result = compute_quality_gate(ledger, metrics)
        assert result["unenriched_followup_rate"] == 0.0

    def test_empty_data(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        metrics = tmp_path / "metrics.jsonl"
        ledger.write_text("")
        metrics.write_text("")
        result = compute_quality_gate(ledger, metrics)
        assert result["enriched_followup_rate"] == 0.0


class TestSessionContinuity:
    def test_enriched_session_error_rate(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        metrics = tmp_path / "metrics.jsonl"

        write_jsonl(metrics, [
            {"hook": "session_start", "session_id": "s1", "action": "enriched", "ts": "2026-04-06T01:00:00"},
        ])
        bash_entries = []
        for i in range(10):
            bash_entries.append({
                "session_id": "s1", "tool": "Bash", "exit_code": 1 if i == 0 else 0,
                "ts": f"2026-04-06T01:0{i}:00",
            })
        write_jsonl(ledger, bash_entries)

        result = compute_session_continuity(ledger, metrics)
        assert result["enriched_error_rate"] == 0.1
        assert result["enriched_session_count"] == 1

    def test_empty_data(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        metrics = tmp_path / "metrics.jsonl"
        ledger.write_text("")
        metrics.write_text("")
        result = compute_session_continuity(ledger, metrics)
        assert result["enriched_error_rate"] == 0.0
