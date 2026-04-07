#!/usr/bin/env python3
"""PreCompact preservation hook: injects active task/plan summary before compaction.

Reads the native task store for the current session and injects a minimal
handoff summary into the post-compact context via additionalContext.

Payload shape (verified from fixtures):
    session_id, transcript_path, cwd, hook_event_name, trigger, custom_instructions
"""
import glob
import json
import os
import sys

from hook_utils import read_hook_input, sanitize_task_list_id, log_hook_diagnostic, run_fail_open

TASK_DIR = os.path.expanduser("~/.claude/tasks")
PLAN_DIR = os.path.expanduser("~/.claude/plans")


def main():
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = str(input_data.get("session_id") or "")
    parts = []

    # Collect open tasks from the session's task directory
    task_summary = _get_open_tasks(_resolve_task_list_id(session_id))
    if task_summary:
        parts.append(task_summary)

    # Check for recently active plan file
    plan_summary = _get_active_plan()
    if plan_summary:
        parts.append(plan_summary)

    if not parts:
        # Nothing to preserve
        sys.exit(0)

    context = "[PreCompact handoff]\n" + "\n".join(parts)

    # Inject into post-compact context via systemMessage (PreCompact has no hookSpecificOutput)
    print(json.dumps({
        "systemMessage": context,
    }))
    sys.exit(0)


def _get_open_tasks(session_id: str) -> str | None:
    """Read non-completed tasks from the session task directory."""
    task_path = os.path.join(TASK_DIR, session_id)
    if not os.path.isdir(task_path):
        return None

    open_tasks = []
    try:
        entries = sorted(os.listdir(task_path))
    except OSError as exc:
        log_hook_diagnostic(
            "precompact-preserve", "PreCompact",
            "task_dir_unreadable",
            f"OSError reading task dir {task_path}: {exc}",
            context={"task_path": task_path},
        )
        return None
    for fname in entries:
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(task_path, fname)
        try:
            with open(fpath) as f:
                task = json.load(f)
            status = task.get("status", "")
            if status in ("pending", "in_progress"):
                tid = task.get("id", fname)
                subject = task.get("subject", "(no subject)")
                blocked_by = task.get("blockedBy", [])
                entry = f"  [{status}] #{tid}: {subject}"
                if blocked_by:
                    entry += f" (blocked by: {', '.join(str(b) for b in blocked_by)})"
                open_tasks.append(entry)
        except (json.JSONDecodeError, OSError):
            continue

    if not open_tasks:
        return None

    header = f"Open tasks ({len(open_tasks)}):"
    return header + "\n" + "\n".join(open_tasks[:20])  # Cap at 20 to avoid bloat


def _resolve_task_list_id(session_id: str) -> str:
    """Resolve the local task-list directory ID for hook-side task reads.

    Hooks can safely honor the documented/local env-var override but do not try to
    mirror deeper Claude-internal fallback resolution beyond that.
    """
    override = os.environ.get("CLAUDE_CODE_TASK_LIST_ID")
    if override:
        return sanitize_task_list_id(override)
    return session_id


def _get_active_plan() -> str | None:
    """Find the most recently modified plan file."""
    if not os.path.isdir(PLAN_DIR):
        log_hook_diagnostic(
            "precompact-preserve", "PreCompact",
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
            "precompact-preserve", "PreCompact",
            "plan_dir_missing",
            f"Failed to read plan mtime: {exc}",
        )
        return None
    name = os.path.basename(latest)
    return f"Active plan: {name}"


if __name__ == "__main__":
    run_fail_open(main, "precompact-preserve", "PreCompact")
