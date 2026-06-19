#!/usr/bin/env python3
# hooks/precompact-orchestrator.py
"""Registered PreCompact hook (Shape A orchestrator).

Gated behind PRECOMPACT_ORCHESTRATOR_ENABLED=1. Runs five producers as
subprocesses under per-producer deadlines, merges into one capsule, persists it
session-keyed, and injects once. Single fail-open boundary.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hook_utils import read_hook_input, run_fail_open, is_strict  # noqa: E402
from precompact_capsule import render_systemmessage, write_capsule  # noqa: E402
from precompact_orchestrator_lib import build_capsule  # noqa: E402


def main():
    if not is_strict("PRECOMPACT_ORCHESTRATOR_ENABLED"):
        sys.exit(0)  # disabled -> no-op (rollback path)

    inp = read_hook_input(timeout_seconds=2)
    if not inp:
        sys.exit(0)
    session_id = str(inp.get("session_id") or "")

    t0 = time.monotonic()
    capsule = build_capsule(inp, elapsed_ms=0)
    capsule["_ms"] = int((time.monotonic() - t0) * 1000)

    if session_id:
        write_capsule(session_id, capsule)

    msg = render_systemmessage(capsule)
    if msg:
        print(json.dumps({"systemMessage": msg}))
    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, "precompact-orchestrator", "PreCompact")
