#!/usr/bin/env python3
"""PreCompact preservation hook: injects active task/plan summary before compaction.

Reads the native task store for the current session and injects a minimal
handoff summary into the post-compact context via additionalContext.

Payload shape (verified from fixtures):
    session_id, transcript_path, cwd, hook_event_name, trigger, custom_instructions
"""
import json
import sys

from hook_utils import read_hook_input, iter_open_tasks, find_latest_plan, run_fail_open


def main():
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = str(input_data.get("session_id") or "")
    parts = []

    # Collect open tasks from the session's task directory
    task_summary = _format_open_tasks(session_id)
    if task_summary:
        parts.append(task_summary)

    # Check for recently active plan file
    plan_name = find_latest_plan()
    if plan_name:
        parts.append(f"Active plan: {plan_name}")

    if not parts:
        # Nothing to preserve
        sys.exit(0)

    context = "[PreCompact handoff]\n" + "\n".join(parts)

    # Inject into post-compact context via systemMessage (PreCompact has no hookSpecificOutput)
    print(json.dumps({
        "systemMessage": context,
    }))
    sys.exit(0)


def _format_open_tasks(session_id: str) -> str | None:
    """Format open tasks as a text block for compaction context."""
    lines = []
    for task, fname in iter_open_tasks(session_id):
        tid = task.get("id", fname)
        subject = task.get("subject", "(no subject)")
        status = task.get("status", "?")
        blocked_by = task.get("blockedBy", [])
        entry = f"  [{status}] #{tid}: {subject}"
        if blocked_by:
            entry += f" (blocked by: {', '.join(str(b) for b in blocked_by)})"
        lines.append(entry)

    if not lines:
        return None

    header = f"Open tasks ({len(lines)}):"
    return header + "\n" + "\n".join(lines[:20])  # Cap at 20 to avoid bloat



if __name__ == "__main__":
    run_fail_open(main, "precompact-preserve", "PreCompact")
