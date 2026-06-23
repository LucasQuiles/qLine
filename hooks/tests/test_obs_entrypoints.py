"""T2: entrypoint fail-open contract for all 12 obs-*.py hooks.

Every obs hook is an observability side-car: on empty/malformed stdin or a
missing session_id it MUST exit 0 and emit NOTHING on stdout. Any stdout from an
obs hook contaminates Claude's hook-output protocol, so "silent on the fail-open
paths" is a load-bearing invariant. 11 hooks route through hook_utils.run_obs_hook
(wrapped in run_fail_open); obs-session-start has its own main() but the same
stdin/session preamble. None of the 12 had entrypoint coverage — a broken import,
a crash on bad input, or accidental stdout would ship silently.

Run as subprocesses: the contract IS the process exit code + stdout at the
__main__ boundary. HOME and OBS_ROOT are redirected to a tmp dir so the real fault
ledger and observability tree are never touched.
"""
import json
import os
import subprocess
import sys

import pytest

HOOKS_DIR = os.path.join(os.path.dirname(__file__), "..")

OBS_HOOKS = [
    "obs-posttool-bash.py",
    "obs-posttool-edit.py",
    "obs-posttool-failure.py",
    "obs-posttool-write.py",
    "obs-precompact.py",
    "obs-pretool-read.py",
    "obs-prompt-submit.py",
    "obs-session-end.py",
    "obs-session-start.py",
    "obs-stop-cache.py",
    "obs-subagent-stop.py",
    "obs-task-completed.py",
]


def _run(hook: str, stdin: str, tmp_home):
    env = {**os.environ, "HOME": str(tmp_home), "OBS_ROOT": str(tmp_home)}
    return subprocess.run(
        [sys.executable, os.path.join(HOOKS_DIR, hook)],
        input=stdin, capture_output=True, text=True, timeout=15, env=env,
    )


def test_obs_hook_list_matches_disk():
    """Drift guard: if a 13th obs-*.py is added without a test, this fails."""
    on_disk = sorted(
        f for f in os.listdir(HOOKS_DIR)
        if f.startswith("obs-") and f.endswith(".py")
    )
    assert on_disk == sorted(OBS_HOOKS), (
        f"obs hook set drifted from the parametrized list: {on_disk}")


@pytest.mark.parametrize("hook", OBS_HOOKS)
class TestObsEntrypointFailOpen:
    def test_empty_stdin_exits_0_silently(self, hook, tmp_path):
        r = _run(hook, "", tmp_path)
        assert r.returncode == 0, f"{hook} exit {r.returncode} on empty stdin: {r.stderr}"
        assert r.stdout == "", f"{hook} polluted stdout: {r.stdout!r}"

    def test_malformed_json_exits_0_silently(self, hook, tmp_path):
        r = _run(hook, "{not valid json", tmp_path)
        assert r.returncode == 0, f"{hook} exit {r.returncode} on bad json: {r.stderr}"
        assert r.stdout == "", f"{hook} polluted stdout: {r.stdout!r}"

    def test_missing_session_id_exits_0_silently(self, hook, tmp_path):
        payload = json.dumps({"tool_name": "X", "cwd": str(tmp_path)})
        r = _run(hook, payload, tmp_path)
        assert r.returncode == 0, f"{hook} exit {r.returncode} on no session: {r.stderr}"
        assert r.stdout == "", f"{hook} polluted stdout: {r.stdout!r}"
