"""Tests for enrich-inject hook functions."""
import importlib.util
import json
import os
import sys

import pytest

# Import the hyphenated module via importlib
_hook_path = os.path.join(os.path.dirname(__file__), "..", "enrich-inject.py")
_spec = importlib.util.spec_from_file_location("enrich_inject", _hook_path)
_mod = importlib.util.module_from_spec(_spec)

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_spec.loader.exec_module(_mod)

find_ready_enrichments = _mod.find_ready_enrichments
format_injection = _mod.format_injection


# --- find_ready_enrichments ---

class TestFindReadyEnrichments:
    def _write_result(self, ready_dir, trace_id, session_id, tool="Bash", findings="ok"):
        os.makedirs(ready_dir, exist_ok=True)
        data = {
            "session_id": session_id,
            "tool": tool,
            "findings": findings,
            "trace_id": trace_id,
        }
        path = os.path.join(ready_dir, f"{trace_id}.result.json")
        with open(path, "w") as f:
            json.dump(data, f)

    def test_finds_matching_session(self, tmp_path):
        spool = str(tmp_path / "spool")
        ready = os.path.join(spool, "ready")
        self._write_result(ready, "t1", "sess-A", findings="found something")

        results = find_ready_enrichments(spool, "sess-A")
        assert len(results) == 1
        assert results[0]["trace_id"] == "t1"
        assert results[0]["findings"] == "found something"

    def test_ignores_other_sessions(self, tmp_path):
        spool = str(tmp_path / "spool")
        ready = os.path.join(spool, "ready")
        self._write_result(ready, "t1", "sess-A")
        self._write_result(ready, "t2", "sess-B")

        results = find_ready_enrichments(spool, "sess-A")
        assert len(results) == 1
        assert results[0]["session_id"] == "sess-A"

    def test_empty_dir_returns_empty(self, tmp_path):
        spool = str(tmp_path / "spool")
        assert find_ready_enrichments(spool, "sess-X") == []

    def test_empty_ready_dir_returns_empty(self, tmp_path):
        spool = str(tmp_path / "spool")
        os.makedirs(os.path.join(spool, "ready"))
        assert find_ready_enrichments(spool, "sess-X") == []


# --- format_injection ---

class TestFormatInjection:
    def test_single_enrichment(self):
        enrichments = [{"tool": "Bash", "findings": "Large output detected"}]
        result = format_injection(enrichments)
        assert result == "[Brick enrichment from prior Bash call] Large output detected"

    def test_multiple_enrichments(self):
        enrichments = [
            {"tool": "Bash", "findings": "First finding"},
            {"tool": "Agent", "findings": "Second finding"},
        ]
        result = format_injection(enrichments)
        assert "[Brick enrichment from prior Bash call] First finding" in result
        assert "[Brick enrichment from prior Agent call] Second finding" in result
        assert "\n\n" in result

    def test_fallback_to_summary(self):
        enrichments = [{"tool": "Agent", "summary": "Fallback summary"}]
        result = format_injection(enrichments)
        assert "Fallback summary" in result

    def test_missing_findings(self):
        enrichments = [{"tool": "Bash"}]
        result = format_injection(enrichments)
        assert "[Brick enrichment from prior Bash call] " in result
