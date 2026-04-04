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
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
from hook_utils import read_hook_input, run_fail_open
from obs_utils import (
    resolve_package_root,
    append_event,
    record_error,
    _atomic_jsonl_append,
)

_HOOK_NAME = "obs-pretool-read"
_EVENT_NAME = "PreToolUse"


def _load_read_state(state_path: str) -> dict[str, Any]:
    """Load read state sidecar. Returns {} on any error."""
    try:
        with open(state_path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_read_state(state_path: str, state: dict) -> None:
    """Write read state sidecar atomically. Never raises."""
    try:
        parent = os.path.dirname(state_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp_path = state_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(state, f)
        os.replace(tmp_path, state_path)
    except Exception:
        pass


def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = input_data.get("session_id")
    if not session_id:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    if tool_name != "Read":
        sys.exit(0)

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
    from datetime import datetime, timezone

    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    read_record: dict[str, Any] = {
        "ts": _now_iso(),
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

    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
