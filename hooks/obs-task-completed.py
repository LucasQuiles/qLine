#!/usr/bin/env python3
"""TaskCompleted observability hook: logs task completion to the session package.

Steps:
  1. Read stdin; exit 0 if empty or no session_id.
  2. Resolve package_root via runtime map; exit 0 if unknown session.
  3. Append raw task payload to metadata/task_events.jsonl (dedicated task log).
  4. Emit task.completed event to metadata/hook_events.jsonl.
  5. Update manifest tasks array with {task_id, task_subject, completed_at}.
  6. Exit 0 always (fail-open).
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
from hook_utils import read_hook_input, run_fail_open
from obs_utils import (
    _atomic_jsonl_append,
    resolve_package_root,
    append_event,
    update_manifest_array,
    record_error,
    update_health,
    _now_iso,
)


def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = input_data.get("session_id")
    if not session_id:
        sys.exit(0)

    task_id = str(input_data.get("task_id") or "")
    task_subject = str(input_data.get("task_subject") or "")
    task_description = str(input_data.get("task_description") or "")
    cwd = str(input_data.get("cwd") or "")

    # Allow tests to override the observability root via env var
    obs_root_override = os.environ.get("OBS_ROOT")
    kwargs: dict = {}
    if obs_root_override:
        kwargs["obs_root"] = obs_root_override

    # Resolve package — if None, session was never packaged; exit silently
    package_root = resolve_package_root(session_id, **kwargs)
    if package_root is None:
        sys.exit(0)

    # ------------------------------------------------------------------
    # Step 3: Append raw task payload to metadata/task_events.jsonl
    # This is a dedicated task log, separate from the event ledger.
    # ------------------------------------------------------------------
    task_log_path = os.path.join(package_root, "metadata", "task_events.jsonl")
    raw_record = {
        "session_id": session_id,
        "task_id": task_id,
        "task_subject": task_subject,
        "task_description": task_description,
        "cwd": cwd,
        "recorded_at": _now_iso(),
    }
    task_log_ok = _atomic_jsonl_append(task_log_path, raw_record)
    if not task_log_ok:
        record_error(
            package_root, "TASK_EVENT_WRITE_FAILED", "warning", "task_capture",
            "append_task_events_jsonl", message=f"Failed to write task {task_id} to task_events.jsonl",
        )
        update_health(package_root, "task_capture", "degraded",
                     warning={"code": "TASK_EVENT_WRITE_FAILED", "task_id": task_id})

    # ------------------------------------------------------------------
    # Step 4: Emit task.completed event to hook_events.jsonl
    # ------------------------------------------------------------------
    append_event(
        package_root,
        "task.completed",
        session_id,
        {
            "task_id": task_id,
            "task_subject": task_subject,
            "cwd": cwd,
        },
        origin_type="native_snapshot",
        hook="obs-task-completed",
    )

    # ------------------------------------------------------------------
    # Step 5: Update manifest tasks array
    # ------------------------------------------------------------------
    update_manifest_array(
        package_root,
        "tasks",
        {
            "task_id": task_id,
            "task_subject": task_subject,
            "completed_at": _now_iso(),
        },
    )

    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, "obs-task-completed", "TaskCompleted")
