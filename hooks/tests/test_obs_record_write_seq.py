"""R4a: tests for obs_utils.record_write_seq — the shared read_state sidecar
update extracted from the post-write and post-edit observability hooks."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_record_write_seq_preserves_existing_entry(tmp_path):
    from obs_utils import record_write_seq, _load_read_state

    custom_dir = str(tmp_path)
    sp = os.path.join(custom_dir, ".read_state.json")
    with open(sp, "w") as f:
        json.dump({"/a.py": {"read_count": 3, "last_read_seq": 9}}, f)

    record_write_seq(custom_dir, "/a.py", 42)

    state = _load_read_state(sp)
    assert state["/a.py"]["last_write_seq"] == 42  # set
    assert state["/a.py"]["read_count"] == 3        # preserved
    assert state["/a.py"]["last_read_seq"] == 9      # preserved


def test_record_write_seq_creates_new_entry(tmp_path):
    from obs_utils import record_write_seq, _load_read_state

    custom_dir = str(tmp_path)
    record_write_seq(custom_dir, "/new.py", 7)

    state = _load_read_state(os.path.join(custom_dir, ".read_state.json"))
    assert state["/new.py"] == {"last_write_seq": 7}
