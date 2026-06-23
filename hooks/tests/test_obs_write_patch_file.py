"""R4b: tests for obs_utils.write_patch_file — the shared patch-capture write
extracted from the post-write and post-edit hooks. The two copies diverged on the
FAILURE path (edit degraded patch_capture health, write did not); the helper
unifies on the safer behavior (record_error AND degrade health)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_write_patch_file_success_writes_and_returns_path(tmp_path):
    from obs_utils import write_patch_file

    custom_dir = str(tmp_path / "custom")
    path = write_patch_file("pkg", custom_dir, "1-abc.patch", "PATCH_BODY", "/f.py")

    assert path == os.path.join(custom_dir, "write_diffs", "1-abc.patch")
    with open(path) as f:
        assert f.read() == "PATCH_BODY"


def test_write_patch_file_failure_records_error_and_degrades_health(tmp_path, monkeypatch):
    import obs_utils

    calls = {"err": 0, "health": []}
    monkeypatch.setattr(obs_utils, "record_error",
                        lambda *a, **k: calls.__setitem__("err", calls["err"] + 1))
    monkeypatch.setattr(obs_utils, "update_health",
                        lambda pkg, subsystem, state, **k: calls["health"].append((subsystem, state)))

    # Make the custom dir a FILE so os.makedirs(write_diffs) raises -> failure path.
    blocker = tmp_path / "custom"
    blocker.write_text("x")

    from obs_utils import write_patch_file
    path = write_patch_file("pkg", str(blocker), "1-abc.patch", "BODY", "/f.py")

    assert calls["err"] == 1, "failure must record_error"
    assert ("patch_capture", "degraded") in calls["health"], (
        "R4b: a failed patch write must degrade patch_capture health (write hook "
        "previously skipped this)")
    # best-effort path still returned for artifact registration
    assert path == os.path.join(str(blocker), "write_diffs", "1-abc.patch")
