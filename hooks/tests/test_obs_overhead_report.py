"""T1: characterization coverage for the derived transcript-analytics functions
in obs_utils — extract_usage_full and generate_overhead_report.

These two functions had ZERO test coverage despite feeding the cost/overhead
report (cache-hit-rate, effective-cost-multiplier, cache-busting detection). A
silent regression in this parsing/math corrupts every overhead report with no
test to catch it. These tests pin current documented behavior; they are also
the safety net any future extraction (obs_derived.py) would need before moving
the code.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# --- extract_usage_full -----------------------------------------------------

class TestExtractUsageFull:
    def test_message_path_returns_full_tuple(self):
        from obs_utils import extract_usage_full
        entry = {
            "message": {
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 50},
                "model": "claude-x",
                "requestId": "req-1",
                "id": "msg-1",
            }
        }
        usage, model, request_id, entry_id = extract_usage_full(entry)
        assert usage == {"input_tokens": 50}
        assert model == "claude-x"
        assert request_id == "req-1"
        assert entry_id == "msg-1"

    def test_message_path_skipped_when_stop_reason_none(self):
        """Streaming stubs (stop_reason is None) must NOT yield message usage —
        the function falls through. With no toolUseResult, result is all-None."""
        from obs_utils import extract_usage_full
        entry = {
            "message": {
                "stop_reason": None,
                "usage": {"input_tokens": 999},
                "model": "claude-x",
            }
        }
        assert extract_usage_full(entry) == (None, None, None, None)

    def test_message_request_id_falls_back_to_entry(self):
        """When message lacks requestId, the top-level entry requestId is used."""
        from obs_utils import extract_usage_full
        entry = {
            "requestId": "entry-req",
            "message": {
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1},
                "model": "m",
                "id": "msg-2",
            },
        }
        _, _, request_id, _ = extract_usage_full(entry)
        assert request_id == "entry-req"

    def test_message_usage_not_dict_falls_through(self):
        from obs_utils import extract_usage_full
        entry = {"message": {"stop_reason": "end_turn", "usage": "nope"}}
        assert extract_usage_full(entry) == (None, None, None, None)

    def test_tooluseresult_path_returns_no_model(self):
        """Subagent usage comes via toolUseResult; model is None, entry_id from uuid."""
        from obs_utils import extract_usage_full
        entry = {
            "uuid": "u-9",
            "toolUseResult": {"usage": {"input_tokens": 7}, "requestId": "tur-req"},
        }
        usage, model, request_id, entry_id = extract_usage_full(entry)
        assert usage == {"input_tokens": 7}
        assert model is None
        assert request_id == "tur-req"
        assert entry_id == "u-9"

    def test_tooluseresult_entry_id_falls_back_to_timestamp(self):
        from obs_utils import extract_usage_full
        entry = {
            "timestamp": "2026-06-23T00:00:00Z",
            "toolUseResult": {"usage": {"input_tokens": 3}},
        }
        _, _, _, entry_id = extract_usage_full(entry)
        assert entry_id == "2026-06-23T00:00:00Z"

    def test_no_usage_anywhere_returns_all_none(self):
        from obs_utils import extract_usage_full
        assert extract_usage_full({}) == (None, None, None, None)
        assert extract_usage_full({"message": {}}) == (None, None, None, None)


# --- generate_overhead_report -----------------------------------------------

def _turn(cc: int, cr: int, inp: int) -> str:
    """Build one transcript JSONL line with a usage-bearing message turn."""
    return json.dumps({
        "message": {
            "stop_reason": "end_turn",
            "model": "claude-x",
            "id": f"m-{cc}-{cr}-{inp}",
            "usage": {
                "cache_creation_input_tokens": cc,
                "cache_read_input_tokens": cr,
                "input_tokens": inp,
            },
        }
    })


class TestGenerateOverheadReport:
    def test_computes_totals_hitrate_and_cost_multiplier(self, tmp_path):
        from obs_utils import generate_overhead_report
        transcript = tmp_path / "transcript.jsonl"
        # anchor turn, a cache-hit turn, then a cache-busting turn
        transcript.write_text("\n".join([
            _turn(1000, 0, 50),    # turn 0 = anchor (cc=1000)
            _turn(100, 900, 20),   # turn 1 = not busting (100 < 900)
            _turn(500, 100, 10),   # turn 2 = busting (500 > 100, i>0)
        ]) + "\n")
        pkg = tmp_path / "pkg"
        pkg.mkdir()

        report = generate_overhead_report(str(pkg), str(transcript))

        assert report is not None
        assert report["total_turns"] == 3
        assert report["system_overhead_tokens"] == 1000          # first-turn anchor
        assert report["total_cache_read_tokens"] == 1000          # 0+900+100
        assert report["total_cache_create_tokens"] == 1600        # 1000+100+500
        assert report["total_fresh_input_tokens"] == 80           # 50+20+10
        assert report["cache_hit_rate_overall"] == 0.3846         # 1000/2600
        assert report["cache_busting_events"] == 1
        assert report["cache_busting_turns"] == [2]
        assert report["effective_cost_multiplier"] == 2.48        # 2680/1080

    def test_writes_report_to_derived_dir(self, tmp_path):
        from obs_utils import generate_overhead_report
        transcript = tmp_path / "t.jsonl"
        transcript.write_text(_turn(1000, 0, 50) + "\n")
        pkg = tmp_path / "pkg"
        pkg.mkdir()

        generate_overhead_report(str(pkg), str(transcript))

        out = pkg / "derived" / "overhead_report.json"
        assert out.exists(), "report must be persisted to derived/overhead_report.json"
        persisted = json.loads(out.read_text())
        assert persisted["total_turns"] == 1

    def test_none_when_no_usage_turns(self, tmp_path):
        from obs_utils import generate_overhead_report
        transcript = tmp_path / "empty.jsonl"
        # blank lines + a non-usage entry → no turns
        transcript.write_text("\n" + json.dumps({"message": {"stop_reason": None}}) + "\n")
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        assert generate_overhead_report(str(pkg), str(transcript)) is None

    def test_none_when_transcript_missing(self, tmp_path):
        from obs_utils import generate_overhead_report
        missing = tmp_path / "does-not-exist.jsonl"
        assert generate_overhead_report(str(tmp_path), str(missing)) is None
