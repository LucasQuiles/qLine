# hooks/tests/test_precompact_sentinel.py
"""Tests for the SessionStart capsule sentinel."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestEvaluateCapsule:
    def test_flags_rot_when_expected_producer_missing(self):
        from precompact_sentinel_lib import evaluate_capsule, EXPECTED_PRODUCERS
        cap = {"_producers_ok": ["preserve"], "_producers_failed": ["git"],
               "_empty": False, "_ms": 10}
        alerts = evaluate_capsule(cap)
        classes = {a["reason_class"] for a in alerts}
        assert "precompact_producer_rot" in classes
        rot = next(a for a in alerts if a["reason_class"] == "precompact_producer_rot")
        assert "git" in rot["context"]["failed"]

    def test_flags_empty_capsule(self):
        from precompact_sentinel_lib import evaluate_capsule
        alerts = evaluate_capsule({"_producers_ok": [], "_producers_failed": [],
                                   "_empty": True, "_ms": 4})
        assert any(a["reason_class"] == "precompact_capsule_empty" for a in alerts)

    def test_clean_capsule_no_alerts(self):
        from precompact_sentinel_lib import evaluate_capsule, EXPECTED_PRODUCERS
        cap = {"_producers_ok": list(EXPECTED_PRODUCERS), "_producers_failed": [],
               "_empty": False, "_ms": 10}
        assert evaluate_capsule(cap) == []

    def test_no_capsule_is_silent(self):
        from precompact_sentinel_lib import evaluate_capsule
        assert evaluate_capsule(None) == []

    def test_non_dict_capsule_never_raises(self):
        # A corrupted capsule (e.g. a JSON array) must degrade to [], not raise.
        from precompact_sentinel_lib import evaluate_capsule
        assert evaluate_capsule([1, 2, 3]) == []
        assert evaluate_capsule("garbage") == []

    def test_malformed_failed_field_does_not_iterate_chars(self):
        # _producers_failed as a string must NOT become ['g','i','t'].
        from precompact_sentinel_lib import evaluate_capsule
        alerts = evaluate_capsule({"_producers_failed": "git", "_empty": False})
        # string is not a list -> treated as no structural failures
        assert all(a["reason_class"] != "precompact_producer_rot" for a in alerts)
