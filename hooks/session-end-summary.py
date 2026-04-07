#!/usr/bin/env python3
"""SessionEnd summary hook (log-only): writes a brief session handoff summary.

Logs a summary of open tasks and active plan to stderr on session exit.
Does NOT block session exit under any circumstances.

Payload shape (verified from fixtures):
    session_id, transcript_path, cwd, hook_event_name, reason
"""
import sys

from hook_utils import read_hook_input, iter_open_tasks, find_latest_plan, log_hook_diagnostic, run_fail_open


def main():
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = str(input_data.get("session_id") or "")
    reason = str(input_data.get("reason") or "unknown")
    parts = []

    # Count open tasks
    open_count, in_progress = _count_open_tasks(session_id)
    if open_count > 0:
        parts.append(f"Open tasks: {open_count} ({in_progress} in-progress)")

    # Active plan
    plan_name = find_latest_plan()
    if plan_name:
        parts.append(f"Active plan: {plan_name}")

    if parts:
        summary = " | ".join(parts)
        log_hook_diagnostic(
            "session-end-summary", "SessionEnd",
            "session_exit_summary",
            f"Exit reason: {reason}. {summary}",
            level="info",
        )

    # Never block session exit
    sys.exit(0)


def _count_open_tasks(session_id: str) -> tuple[int, int]:
    """Count non-completed tasks. Returns (total_open, in_progress)."""
    total_open = 0
    in_progress = 0
    for task, _ in iter_open_tasks(session_id):
        total_open += 1
        if task.get("status") == "in_progress":
            in_progress += 1
    return total_open, in_progress



if __name__ == "__main__":
    run_fail_open(main, "session-end-summary", "SessionEnd")
