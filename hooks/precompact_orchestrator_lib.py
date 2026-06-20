# hooks/precompact_orchestrator_lib.py
"""Testable core for the PreCompact orchestrator: fan out producers as
subprocesses with a per-producer deadline, then merge into one capsule."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from precompact_capsule import merge_capsule
from precompact_config import per_producer_deadline_s as _deadline

PRODUCER_ORDER = ["preserve", "git", "failures", "stats", "handoff"]
PER_PRODUCER_DEADLINE_S = _deadline()
_PRODUCERS_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "precompact_producers.py")


def _subprocess_runner(name: str, inp: dict, deadline_s: float):
    """Run one producer as a subprocess; return its section dict or raise."""
    try:
        from hook_utils import subprocess_resource_limits
        preexec = subprocess_resource_limits
    except Exception:
        preexec = None
    proc = subprocess.run(
        [sys.executable, _PRODUCERS_SCRIPT, name, "--json-out"],
        input=json.dumps(inp), capture_output=True, text=True,
        timeout=deadline_s, preexec_fn=preexec,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"producer {name} rc={proc.returncode}")
    out = proc.stdout.strip()
    return json.loads(out) if out else None  # "null" -> None


def run_producers(inp: dict, *, producers=None, runner=None, deadline_s=PER_PRODUCER_DEADLINE_S):
    """Run each producer concurrently; return (results, failed).

    Producers are independent subprocesses, so they run in parallel: total
    wall-clock is bounded by the slowest single producer (~deadline_s), NOT the
    sum. This keeps the hook within its registered timeout even if every
    producer runs to its per-producer deadline.
    """
    producers = producers or PRODUCER_ORDER
    runner = runner or _subprocess_runner
    results: dict = {}
    failed: list = []
    with ThreadPoolExecutor(max_workers=max(1, len(producers))) as ex:
        futures = {name: ex.submit(runner, name, inp, deadline_s) for name in producers}
        for name in producers:
            try:
                results[name] = futures[name].result()
            except Exception:
                failed.append(name)
                results[name] = None
    return results, failed


def build_capsule(inp: dict, elapsed_ms: int, **kw) -> dict:
    results, failed = run_producers(inp, **kw)
    return merge_capsule(results, failed, elapsed_ms)
