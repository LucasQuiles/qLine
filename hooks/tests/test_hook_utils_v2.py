"""Tests for hook_utils v2.0 contract additions."""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestValidateSessionId:
    def test_valid(self):
        from hook_utils import validate_session_id
        assert validate_session_id("abc-123") == "abc-123"

    def test_strips_whitespace(self):
        from hook_utils import validate_session_id
        assert validate_session_id("  hello  ") == "hello"

    def test_rejects_none(self):
        from hook_utils import validate_session_id
        assert validate_session_id(None) is None

    def test_rejects_empty(self):
        from hook_utils import validate_session_id
        assert validate_session_id("") is None

    def test_rejects_whitespace_only(self):
        from hook_utils import validate_session_id
        assert validate_session_id("   ") is None

    def test_rejects_too_long(self):
        from hook_utils import validate_session_id
        assert validate_session_id("x" * 257) is None

    def test_accepts_exactly_256(self):
        from hook_utils import validate_session_id
        assert validate_session_id("x" * 256) == "x" * 256

    def test_rejects_null_bytes(self):
        from hook_utils import validate_session_id
        assert validate_session_id("abc\x00def") is None

    def test_rejects_non_string(self):
        from hook_utils import validate_session_id
        assert validate_session_id(42) is None


class TestValidatePayloadStructure:
    def test_valid(self):
        from hook_utils import validate_payload_structure
        assert validate_payload_structure({"session_id": "s1", "tool_name": "t"}, {"session_id", "tool_name"}) is True

    def test_missing_field(self):
        from hook_utils import validate_payload_structure
        assert validate_payload_structure({"session_id": "s1"}, {"session_id", "tool_name"}) is False

    def test_rejects_non_dict(self):
        from hook_utils import validate_payload_structure
        assert validate_payload_structure("not a dict", {"session_id"}) is False

    def test_empty_required_fields(self):
        from hook_utils import validate_payload_structure
        assert validate_payload_structure({"anything": 1}, set()) is True


class TestDeadline:
    def test_remaining_decreases(self):
        from hook_utils import Deadline
        d = Deadline(1.0)
        r1 = d.remaining()
        time.sleep(0.05)
        assert d.remaining() < r1

    def test_remaining_never_negative(self):
        from hook_utils import Deadline
        d = Deadline(0.0)
        assert d.remaining() == 0.0

    def test_check_raises_when_expired(self):
        from hook_utils import Deadline
        d = Deadline(0.0)
        with pytest.raises(TimeoutError, match="budget exhausted"):
            d.check("test_op")

    def test_check_ok_when_remaining(self):
        from hook_utils import Deadline
        d = Deadline(10.0)
        d.check("should_not_raise")

    def test_not_a_context_manager(self):
        from hook_utils import Deadline
        d = Deadline(1.0)
        assert not hasattr(d, "__enter__")
        assert not hasattr(d, "__exit__")


class TestLogHookEvent:
    def test_writes_jsonl_record(self, tmp_path, monkeypatch):
        import hook_utils as hu
        ledger = tmp_path / "events.jsonl"
        monkeypatch.setattr(hu, "_LEDGER_PATH", str(ledger))
        hu.log_hook_event("my_hook", "SessionStart", "ok", 42.5)
        rec = json.loads(ledger.read_text().strip())
        assert rec["hook"] == "my_hook"
        assert rec["event"] == "SessionStart"
        assert rec["outcome"] == "ok"
        assert rec["duration_ms"] == 42.5
        assert rec["level"] == "info"

    def test_writes_extras(self, tmp_path, monkeypatch):
        import hook_utils as hu
        ledger = tmp_path / "events.jsonl"
        monkeypatch.setattr(hu, "_LEDGER_PATH", str(ledger))
        hu.log_hook_event("h", "e", "ok", 1.0, extras={"key": "val"})
        rec = json.loads(ledger.read_text())
        assert rec["key"] == "val"


class TestSubprocessResourceLimits:
    def test_callable(self):
        from hook_utils import subprocess_resource_limits
        assert callable(subprocess_resource_limits)

    def test_does_not_raise(self):
        from hook_utils import subprocess_resource_limits
        subprocess_resource_limits()


class TestCircuitBreaker:
    def test_closed_by_default(self, tmp_path, monkeypatch):
        import hook_utils as hu
        monkeypatch.setattr(hu, "_CIRCUIT_PATH", str(tmp_path / "cb.json"))
        assert hu.circuit_is_open("pinecone") is False

    def test_opens_after_threshold(self, tmp_path, monkeypatch):
        import hook_utils as hu
        monkeypatch.setattr(hu, "_CIRCUIT_PATH", str(tmp_path / "cb.json"))
        for _ in range(3):
            hu.record_circuit_result("pinecone", False)
        assert hu.circuit_is_open("pinecone") is True

    def test_resets_on_success(self, tmp_path, monkeypatch):
        import hook_utils as hu
        monkeypatch.setattr(hu, "_CIRCUIT_PATH", str(tmp_path / "cb.json"))
        for _ in range(3):
            hu.record_circuit_result("pinecone", False)
        hu.record_circuit_result("pinecone", True)
        assert hu.circuit_is_open("pinecone") is False

    def test_services_independent(self, tmp_path, monkeypatch):
        import hook_utils as hu
        monkeypatch.setattr(hu, "_CIRCUIT_PATH", str(tmp_path / "cb.json"))
        for _ in range(3):
            hu.record_circuit_result("bad", False)
        assert hu.circuit_is_open("bad") is True
        assert hu.circuit_is_open("good") is False


class TestSchemaConstants:
    def test_session_start(self):
        from hook_utils import SCHEMA_SESSION_START
        assert SCHEMA_SESSION_START == {"session_id"}

    def test_pretool_use(self):
        from hook_utils import SCHEMA_PRETOOL_USE
        assert SCHEMA_PRETOOL_USE == {"session_id", "tool_name", "tool_input"}

    def test_posttool_use(self):
        from hook_utils import SCHEMA_POSTTOOL_USE
        assert SCHEMA_POSTTOOL_USE == {"session_id", "tool_name", "tool_input", "tool_response"}

    def test_prompt_submit(self):
        from hook_utils import SCHEMA_PROMPT_SUBMIT
        assert SCHEMA_PROMPT_SUBMIT == {"session_id"}

    def test_session_end(self):
        from hook_utils import SCHEMA_SESSION_END
        assert SCHEMA_SESSION_END == {"session_id"}
