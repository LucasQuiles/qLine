#!/usr/bin/env python3
"""SessionEnd summary hook (log-only): writes a brief session handoff summary.

Logs a summary of open tasks and active plan to stderr on session exit.
Does NOT block session exit under any circumstances.

Payload shape (verified from fixtures):
    session_id, transcript_path, cwd, hook_event_name, reason
"""
import glob
import json
import os
import sys

from hook_utils import read_hook_input, sanitize_task_list_id, resolve_task_list_id, log_hook_diagnostic, run_fail_open

TASK_DIR = os.path.expanduser("~/.claude/tasks")
PLAN_DIR = os.path.expanduser("~/.claude/plans")


def main():
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = str(input_data.get("session_id") or "")
    reason = str(input_data.get("reason") or "unknown")
    parts = []

    # Count open tasks
    open_count, in_progress = _count_open_tasks(resolve_task_list_id(session_id))
    if open_count > 0:
        parts.append(f"Open tasks: {open_count} ({in_progress} in-progress)")

    # Active plan
    plan = _get_active_plan()
    if plan:
        parts.append(f"Active plan: {plan}")

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
    task_path = os.path.join(TASK_DIR, session_id)
    if not os.path.isdir(task_path):
        return 0, 0

    total_open = 0
    in_progress = 0
    try:
        entries = os.listdir(task_path)
    except OSError as exc:
        log_hook_diagnostic(
            "session-end-summary", "SessionEnd",
            "task_dir_unreadable",
            f"OSError reading task dir {task_path}: {exc}",
            context={"task_path": task_path},
        )
        return 0, 0
    for fname in entries:
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(task_path, fname)
        try:
            with open(fpath) as f:
                task = json.load(f)
            status = task.get("status", "")
            if status in ("pending", "in_progress"):
                total_open += 1
                if status == "in_progress":
                    in_progress += 1
        except (json.JSONDecodeError, OSError):
            continue

    return total_open, in_progress



def _get_active_plan() -> str | None:
    """Find the most recently modified plan file name."""
    if not os.path.isdir(PLAN_DIR):
        log_hook_diagnostic(
            "session-end-summary", "SessionEnd",
            "plan_dir_missing",
            f"Plan directory does not exist: {PLAN_DIR}",
        )
        return None

    plans = glob.glob(os.path.join(PLAN_DIR, "*.md"))
    if not plans:
        return None

    try:
        latest = max(plans, key=os.path.getmtime)
    except (OSError, ValueError) as exc:
        log_hook_diagnostic(
            "session-end-summary", "SessionEnd",
            "plan_dir_missing",
            f"Failed to read plan mtime: {exc}",
        )
        return None
    return os.path.basename(latest)


if __name__ == "__main__":
    run_fail_open(main, "session-end-summary", "SessionEnd")
