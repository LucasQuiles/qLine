#!/usr/bin/env python3
"""PreToolUse(Read) observability hook: records file reads, detects rereads.

Scope: Read tool only. Exits 0 immediately for any other tool_name.

Per-call steps:
  1. Read stdin payload via read_hook_input()
  2. Exit 0 if: empty stdin, no session_id, tool_name != "Read"
  3. Resolve package_root via resolve_package_root(session_id). Exit 0 if None.
  4. Build read record with fields: tool, tool_ref, path, offset, limit
  5. Compute reread detection using custom/.read_state.json sidecar
  6. Append to custom/reads.jsonl (O_APPEND — atomic)
  7. Append file.read event to event ledger via append_event()
  8. Update read_state with the seq from the event
  9. Exit 0 always
"""
import json
import os
from typing import Any

from hook_utils import run_fail_open, run_obs_hook
from obs_utils import (
    append_event,
    record_error,
    _atomic_jsonl_append,
    now_iso,
    _load_read_state,
    _save_read_state,
)

_HOOK_NAME = "obs-pretool-read"
_EVENT_NAME = "PreToolUse"


def _handle(input_data: dict, session_id: str, package_root: str) -> None:
    tool_name = input_data.get("tool_name", "")
    if tool_name != "Read":
        return

    # ------------------------------------------------------------------
    # Step 1: Extract tool_input fields
    # ------------------------------------------------------------------
    tool_input: dict = input_data.get("tool_input", {})
    tool_ref = input_data.get("tool_use_id", "")
    file_path: str = tool_input.get("file_path", "")
    offset: int = tool_input.get("offset") if tool_input.get("offset") is not None else 0
    limit: int = tool_input.get("limit") if tool_input.get("limit") is not None else 2000

    # ------------------------------------------------------------------
    # Step 2: Reread detection via custom/.read_state.json
    # ------------------------------------------------------------------
    custom_dir = os.path.join(package_root, "custom")
    state_path = os.path.join(custom_dir, ".read_state.json")

    state = _load_read_state(state_path)
    path_entry: dict = state.get(file_path, {})
    read_count: int = path_entry.get("read_count", 0)
    last_write_seq: Any = path_entry.get("last_write_seq", None)

    new_read_count = read_count + 1
    is_reread = read_count > 0  # True starting from second read

    # ------------------------------------------------------------------
    # Step 3: Build read record for custom/reads.jsonl
    # ------------------------------------------------------------------
    read_record: dict[str, Any] = {
        "ts": now_iso(),
        "session_id": session_id,
        "tool": tool_name,
        "tool_ref": tool_ref,
        "path": file_path,
        "offset": offset,
        "limit": limit,
        "is_reread": is_reread,
        "read_count": new_read_count,
        "last_write_seq": last_write_seq,
    }

    # ------------------------------------------------------------------
    # Step 4: Append to custom/reads.jsonl
    # ------------------------------------------------------------------
    reads_path = os.path.join(custom_dir, "reads.jsonl")
    success = _atomic_jsonl_append(reads_path, read_record)
    if not success:
        record_error(
            package_root,
            "READS_APPEND_FAILED",
            "warning",
            "read_audit",
            "append_reads_jsonl",
            message=f"Failed to append read record for {file_path}",
        )

    # ------------------------------------------------------------------
    # Step 5: Append file.read event to event ledger
    # ------------------------------------------------------------------
    event_data: dict[str, Any] = {
        "tool": tool_name,
        "tool_ref": tool_ref,
        "path": file_path,
        "offset": offset,
        "limit": limit,
        "is_reread": is_reread,
        "read_count": new_read_count,
    }

    seq = append_event(
        package_root,
        "file.read",
        session_id,
        event_data,
        origin_type="pretool_hook",
        hook=_HOOK_NAME,
    )

    # ------------------------------------------------------------------
    # Step 6: Update read state with new seq
    # ------------------------------------------------------------------
    state[file_path] = {
        "read_count": new_read_count,
        "last_read_seq": seq,
        "last_write_seq": last_write_seq,
    }
    _save_read_state(state_path, state)


if __name__ == "__main__":
    run_fail_open(lambda: run_obs_hook(_handle, _HOOK_NAME, _EVENT_NAME), _HOOK_NAME, _EVENT_NAME)
