# hooks/tests/test_precompact_botpatches_forward.py
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestSelectNewRotRecords:
    def test_selects_only_precompact_rot_after_offset(self, tmp_path):
        from precompact_botpatches_forward import select_new_rot_records
        ledger = tmp_path / "faults.jsonl"
        rows = [
            {"reason_class": "other_thing", "level": "warn"},
            {"reason_class": "precompact_producer_rot", "message": "git failed",
             "context": {"failed": ["git"]}},
            {"reason_class": "precompact_capsule_empty", "message": "empty"},
        ]
        with open(ledger, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        new, new_offset = select_new_rot_records(str(ledger), offset=0)
        classes = {r["reason_class"] for r in new}
        assert classes == {"precompact_producer_rot", "precompact_capsule_empty"}
        assert new_offset == os.path.getsize(ledger)

    def test_offset_prevents_redelivery(self, tmp_path):
        from precompact_botpatches_forward import select_new_rot_records
        ledger = tmp_path / "faults.jsonl"
        with open(ledger, "w") as f:
            f.write(json.dumps({"reason_class": "precompact_producer_rot"}) + "\n")
        _, off = select_new_rot_records(str(ledger), offset=0)
        new2, off2 = select_new_rot_records(str(ledger), offset=off)
        assert new2 == []
        assert off2 == off
