"""Tests for obs_utils LRU eviction in _save_read_state."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_evicts_oldest_entries(tmp_path):
    from obs_utils import _save_read_state

    state_path = str(tmp_path / "read-state.json")

    # Create 510 entries with sequential last_read_seq
    state = {}
    for i in range(510):
        state[f"file_{i:04d}"] = {"last_read_seq": i, "hash": f"h{i}"}

    _save_read_state(state_path, state)

    # Should have evicted the 10 oldest (seq 0-9)
    assert len(state) == 500
    for i in range(10):
        assert f"file_{i:04d}" not in state, f"file_{i:04d} should have been evicted"
    # Newest should remain
    for i in range(10, 510):
        assert f"file_{i:04d}" in state


def test_no_eviction_under_limit(tmp_path):
    from obs_utils import _save_read_state

    state_path = str(tmp_path / "read-state.json")
    state = {f"f{i}": {"last_read_seq": i} for i in range(100)}

    _save_read_state(state_path, state)
    assert len(state) == 100


def test_eviction_handles_non_dict_entries(tmp_path):
    from obs_utils import _save_read_state

    state_path = str(tmp_path / "read-state.json")
    state = {}
    for i in range(505):
        if i < 5:
            state[f"bad_{i}"] = "not_a_dict"  # non-dict entries get seq 0
        else:
            state[f"file_{i}"] = {"last_read_seq": i}

    _save_read_state(state_path, state)
    assert len(state) == 500
    # Non-dict entries (seq 0) should be evicted first
    for i in range(5):
        assert f"bad_{i}" not in state


def test_state_written_to_disk(tmp_path):
    from obs_utils import _save_read_state

    state_path = str(tmp_path / "read-state.json")
    state = {"a": {"last_read_seq": 1}, "b": {"last_read_seq": 2}}

    _save_read_state(state_path, state)

    with open(state_path) as f:
        on_disk = json.load(f)
    assert on_disk == state
