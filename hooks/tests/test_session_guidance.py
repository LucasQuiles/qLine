"""Tests for enrich-session-start hook — session guidance from Pinecone."""
import importlib.util
import json
import os
import sys

import pytest

# Import the hyphenated module via importlib
_hook_path = os.path.join(os.path.dirname(__file__), "..", "enrich-session-start.py")
_spec = importlib.util.spec_from_file_location("enrich_session_start", _hook_path)
_mod = importlib.util.module_from_spec(_spec)

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_spec.loader.exec_module(_mod)

build_query_text = _mod.build_query_text
format_digest_match = _mod.format_digest_match
format_decision_match = _mod.format_decision_match
format_context = _mod.format_context


# --- build_query_text ---


class TestBuildQueryText:
    def test_empty_cwd(self):
        assert build_query_text("") == ""

    def test_home_dir_only(self):
        home = os.path.expanduser("~")
        result = build_query_text(home)
        assert result == ""

    def test_project_path(self):
        result = build_query_text("/home/q/LAB/brick-lab")
        assert "brick-lab" in result
        assert "work in" in result

    def test_deep_project_path(self):
        result = build_query_text("/home/q/LAB/qLine/hooks")
        assert "qLine" in result
        assert "hooks" in result
        assert "work in" in result

    def test_tilde_replacement(self):
        home = os.path.expanduser("~")
        result = build_query_text(f"{home}/LAB/my-project")
        assert "~" in result
        assert home not in result

    def test_single_component(self):
        result = build_query_text("/workspace")
        assert "workspace" in result


# --- format_digest_match ---


class TestFormatDigestMatch:
    def test_full_metadata(self):
        match = {
            "score": 0.85,
            "metadata": {
                "date": "2026-04-01",
                "goal": "Implement circuit breaker",
                "outcome": "completed",
            },
        }
        result = format_digest_match(match)
        assert "2026-04-01" in result
        assert "Implement circuit breaker" in result
        assert "completed" in result

    def test_minimal_metadata(self):
        match = {"score": 0.5, "metadata": {}}
        result = format_digest_match(match)
        assert "unknown" in result

    def test_long_goal_truncated(self):
        match = {
            "score": 0.7,
            "metadata": {"date": "2026-04-02", "goal": "x" * 200},
        }
        result = format_digest_match(match)
        assert len(result) < 200
        assert "..." in result

    def test_fallback_to_text_field(self):
        match = {
            "score": 0.6,
            "metadata": {"date": "2026-04-03", "text": "some text content"},
        }
        result = format_digest_match(match)
        assert "some text content" in result


# --- format_decision_match ---


class TestFormatDecisionMatch:
    def test_full_metadata(self):
        match = {
            "score": 0.9,
            "metadata": {
                "topic": "Error handling",
                "decision": "Use circuit breaker pattern",
                "confidence": "high",
            },
        }
        result = format_decision_match(match)
        assert "Error handling" in result
        assert "Use circuit breaker pattern" in result
        assert "(high)" in result

    def test_minimal_metadata(self):
        match = {"score": 0.5, "metadata": {}}
        result = format_decision_match(match)
        assert "unknown" in result

    def test_topic_only(self):
        match = {"score": 0.6, "metadata": {"topic": "SSL config"}}
        result = format_decision_match(match)
        assert "SSL config" in result

    def test_long_topic_truncated(self):
        match = {
            "score": 0.7,
            "metadata": {"topic": "t" * 100, "decision": "yes"},
        }
        result = format_decision_match(match)
        assert "..." in result


# --- format_context ---


class TestFormatContext:
    def _make_digest(self, score=0.8, date="2026-04-01", goal="Test goal", outcome="done"):
        return {
            "score": score,
            "metadata": {"date": date, "goal": goal, "outcome": outcome},
        }

    def _make_decision(self, score=0.8, topic="Test topic", decision="Use X", confidence="high"):
        return {
            "score": score,
            "metadata": {"topic": topic, "decision": decision, "confidence": confidence},
        }

    def test_empty_results_returns_empty(self):
        result, with_o, without_o = format_context([], [])
        assert result == ""
        assert with_o == 0
        assert without_o == 0

    def test_low_score_results_filtered(self):
        """Results below 0.3 score threshold should be skipped."""
        digests = [self._make_digest(score=0.1)]
        decisions = [self._make_decision(score=0.2)]
        result, _, _ = format_context(digests, decisions)
        assert result == ""

    def test_digests_only(self):
        digests = [
            self._make_digest(date="2026-04-01", goal="Build hooks"),
            self._make_digest(date="2026-04-02", goal="Add tests"),
        ]
        result, with_o, without_o = format_context(digests, [])
        assert "[Brick session context]" in result
        assert "Recent sessions" in result
        assert "Build hooks" in result
        assert "Add tests" in result
        assert "Key decisions" not in result
        assert with_o == 0
        assert without_o == 0

    def test_decisions_only(self):
        decisions = [self._make_decision(topic="Architecture", decision="Use events")]
        result, with_o, without_o = format_context([], decisions)
        assert "[Brick session context]" in result
        assert "Key decisions" in result
        assert "Architecture" in result
        assert "Recent sessions" not in result
        assert without_o == 1  # no ops DB match expected

    def test_both_digests_and_decisions(self):
        digests = [self._make_digest()]
        decisions = [self._make_decision()]
        result, _, _ = format_context(digests, decisions)
        assert "Recent sessions" in result
        assert "Key decisions" in result

    def test_unresolved_items_included(self):
        digests = [
            {
                "score": 0.8,
                "metadata": {
                    "date": "2026-04-01",
                    "goal": "Fix bugs",
                    "outcome": "partial",
                    "unresolved": ["flaky test in CI", "memory leak in worker"],
                },
            }
        ]
        result, _, _ = format_context(digests, [])
        assert "Unresolved from previous sessions" in result
        assert "flaky test in CI" in result
        assert "memory leak in worker" in result

    def test_unresolved_string_wrapped(self):
        """Single string unresolved value should be wrapped as list."""
        digests = [
            {
                "score": 0.8,
                "metadata": {
                    "date": "2026-04-01",
                    "goal": "Work",
                    "unresolved": "single item",
                },
            }
        ]
        result, _, _ = format_context(digests, [])
        assert "single item" in result

    def test_unresolved_capped_at_five(self):
        items = [f"item-{i}" for i in range(10)]
        digests = [
            {
                "score": 0.8,
                "metadata": {"date": "2026-04-01", "goal": "Work", "unresolved": items},
            }
        ]
        result, _, _ = format_context(digests, [])
        assert "item-4" in result
        assert "item-5" not in result

    def test_mixed_scores_filters_correctly(self):
        """Only results above 0.3 should appear."""
        digests = [
            self._make_digest(score=0.9, goal="Relevant"),
            self._make_digest(score=0.1, goal="Irrelevant"),
        ]
        result, _, _ = format_context(digests, [])
        assert "Relevant" in result
        assert "Irrelevant" not in result
