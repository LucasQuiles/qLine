#!/usr/bin/env python3
"""TaskCompleted observability hook: logs task completion to the session package.

Per-call steps (preamble handled by run_obs_hook):
  1. Append raw task payload to metadata/task_events.jsonl (dedicated task log).
  2. Emit task.completed event to metadata/hook_events.jsonl.
  3. Update manifest tasks array with {task_id, task_subject, completed_at}.
"""
import os
from hook_utils import run_fail_open, run_obs_hook
from obs_utils import (
    _atomic_jsonl_append,
    append_event,
    update_manifest_array,
    record_error,
    update_health,
    now_iso,
)


def _handle(input_data: dict, session_id: str, package_root: str) -> None:
    task_id = str(input_data.get("task_id") or "")
    task_subject = str(input_data.get("task_subject") or "")
    task_description = str(input_data.get("task_description") or "")
    cwd = str(input_data.get("cwd") or "")

    # ------------------------------------------------------------------
    # Step 1: Append raw task payload to metadata/task_events.jsonl
    # ------------------------------------------------------------------
    task_log_path = os.path.join(package_root, "metadata", "task_events.jsonl")
    raw_record = {
        "session_id": session_id,
        "task_id": task_id,
        "task_subject": task_subject,
        "task_description": task_description,
        "cwd": cwd,
        "recorded_at": now_iso(),
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
    # Step 2: Emit task.completed event to hook_events.jsonl
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
    # Step 3: Update manifest tasks array
    # ------------------------------------------------------------------
    update_manifest_array(
        package_root,
        "tasks",
        {
            "task_id": task_id,
            "task_subject": task_subject,
            "completed_at": now_iso(),
        },
    )


if __name__ == "__main__":
    run_fail_open(lambda: run_obs_hook(_handle, "obs-task-completed", "TaskCompleted"), "obs-task-completed", "TaskCompleted")
