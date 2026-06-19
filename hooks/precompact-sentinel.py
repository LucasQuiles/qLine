#!/usr/bin/env python3
# hooks/precompact-sentinel.py
"""SessionStart hook: validate the prior session's PreCompact capsule envelope
and emit a producer-rot diagnostic. Purely observational — no injection.

Gated behind PRECOMPACT_ORCHESTRATOR_ENABLED=1 (only meaningful while the
orchestrator is producing capsules).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hook_utils import read_hook_input, run_fail_open, is_strict, log_hook_diagnostic  # noqa: E402
from precompact_capsule import read_capsule  # noqa: E402
from precompact_sentinel_lib import evaluate_capsule  # noqa: E402


def main():
    if not is_strict("PRECOMPACT_ORCHESTRATOR_ENABLED"):
        sys.exit(0)
    inp = read_hook_input(timeout_seconds=2)
    if not inp:
        sys.exit(0)
    session_id = str(inp.get("session_id") or "")
    if not session_id:
        sys.exit(0)

    capsule = read_capsule(session_id)
    for alert in evaluate_capsule(capsule):
        log_hook_diagnostic(
            "precompact-sentinel", "SessionStart",
            alert["reason_class"], alert["message"],
            level="warn", context=alert["context"],
        )
    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, "precompact-sentinel", "SessionStart")
