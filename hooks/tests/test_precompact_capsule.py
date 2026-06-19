# hooks/tests/test_precompact_capsule.py
"""Tests for the PreCompact capsule schema + merge/envelope."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestMergeCapsule:
    def test_merges_sections_and_records_ok(self):
        from precompact_capsule import merge_capsule, CAPSULE_SCHEMA_VERSION
        results = {
            "preserve": {"open_tasks": "Open tasks (1):\n  [pending] #1: x"},
            "git": {"git_state": [{"repo": "qLine", "dirty": 2, "unpushed": 0}]},
        }
        cap = merge_capsule(results, failed=["stats"], elapsed_ms=120)
        assert cap["schema_version"] == CAPSULE_SCHEMA_VERSION
        assert cap["open_tasks"].startswith("Open tasks")
        assert cap["git_state"][0]["repo"] == "qLine"
        assert sorted(cap["_producers_ok"]) == ["git", "preserve"]
        assert cap["_producers_failed"] == ["stats"]
        assert cap["_empty"] is False
        assert cap["_ms"] == 120

    def test_empty_when_all_sections_blank(self):
        from precompact_capsule import merge_capsule
        cap = merge_capsule({"preserve": None, "stats": {}}, failed=[], elapsed_ms=5)
        assert cap["_empty"] is True
        assert cap["_producers_ok"] == []  # producers that returned nothing are not "ok"

    def test_producer_returning_none_is_not_ok_not_failed(self):
        from precompact_capsule import merge_capsule
        cap = merge_capsule({"handoff": None}, failed=[], elapsed_ms=1)
        assert "handoff" not in cap["_producers_ok"]
        assert cap["_producers_failed"] == []

    def test_render_systemmessage_includes_present_sections_only(self):
        from precompact_capsule import render_systemmessage
        cap = {
            "schema_version": 1,
            "open_tasks": "Open tasks (1):\n  [pending] #1: x",
            "git_state": [{"repo": "qLine", "dirty": 1, "unpushed": 0}],
            "handoff_note": "Refactoring the parser; next: wire tests.",
            "_producers_ok": ["preserve", "git", "handoff"],
            "_producers_failed": [], "_empty": False, "_ms": 9,
        }
        msg = render_systemmessage(cap)
        assert "[PreCompact capsule]" in msg
        assert "Open tasks" in msg
        assert "qLine" in msg
        assert "Refactoring the parser" in msg

    def test_render_returns_none_when_empty(self):
        from precompact_capsule import render_systemmessage
        assert render_systemmessage({"_empty": True}) is None


class TestCapsuleStore:
    def test_write_then_read_roundtrip(self, tmp_path):
        from precompact_capsule import write_capsule, read_capsule
        cap = {"schema_version": 1, "open_tasks": "x", "_empty": False,
               "_producers_ok": ["preserve"], "_producers_failed": [], "_ms": 3}
        write_capsule("sess-1", cap, base_dir=str(tmp_path))
        assert read_capsule("sess-1", base_dir=str(tmp_path))["open_tasks"] == "x"

    def test_read_absent_returns_none(self, tmp_path):
        from precompact_capsule import read_capsule
        assert read_capsule("nope", base_dir=str(tmp_path)) is None

    def test_session_id_path_is_sanitized(self, tmp_path):
        from precompact_capsule import write_capsule
        import os
        write_capsule("../evil", {"_empty": True}, base_dir=str(tmp_path))
        for dp, _, files in os.walk(str(tmp_path)):
            for fn in files:
                assert os.path.realpath(os.path.join(dp, fn)).startswith(
                    os.path.realpath(str(tmp_path)))
