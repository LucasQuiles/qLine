#!/usr/bin/env python3
"""PostToolUse(Bash) observability hook: records Bash commands with bounded previews.

Scope: Bash tool only. Exits 0 immediately for any other tool_name.

Privacy: Previews are intentionally unsanitized and bounded. This creates
acceptable bounded duplication of transcript-level information. No full
stdout/stderr capture. No secret scrubbing in v1.

Per-call steps:
  1. Read stdin payload via read_hook_input()
  2. Exit 0 if: empty stdin, no session_id, tool_name != "Bash"
  3. Resolve package_root via resolve_package_root(session_id). Exit 0 if None.
  4. Extract command, stdout, stderr from tool_input/tool_response
  5. Compute hashes, byte counts, bounded previews
  6. Emit bash.executed event via append_event()
  7. Append detail record to custom/bash_commands.jsonl
  8. Update bash_capture health subsystem
  9. Exit 0 always
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
from hook_utils import read_hook_input, run_fail_open
from obs_utils import (
    resolve_package_root,
    append_event,
    update_health,
    record_error,
    _atomic_jsonl_append,
)

_HOOK_NAME = "obs-posttool-bash"
_EVENT_NAME = "PostToolUse"
_MAX_CMD_PREVIEW = 500
_MAX_STDOUT_PREVIEW = 500
_MAX_STDERR_PREVIEW = 200


def _hash16(s: str) -> str:
    """SHA-256 truncated to 16 hex chars."""
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = input_data.get("session_id")
    if not session_id:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    if tool_name != "Bash":
        sys.exit(0)

    tool_response = input_data.get("tool_response")
    if not isinstance(tool_response, dict):
        sys.exit(0)

    obs_root_override = os.environ.get("OBS_ROOT")
    kwargs: dict = {}
    if obs_root_override:
        kwargs["obs_root"] = obs_root_override

    package_root = resolve_package_root(session_id, **kwargs)
    if package_root is None:
        sys.exit(0)

    # --- Extract fields ---
    tool_input: dict = input_data.get("tool_input", {})
    tool_ref = input_data.get("tool_use_id", "")
    command: str = tool_input.get("command", "")
    stdout: str = tool_response.get("stdout", "")
    stderr: str = tool_response.get("stderr", "")
    interrupted: bool = tool_response.get("interrupted", False)
    is_image: bool = tool_response.get("isImage", False)
    no_output_expected: bool = tool_response.get("noOutputExpected", False)

    # --- Compute bounded fields ---
    command_hash = _hash16(command)
    stdout_hash = _hash16(stdout)
    stderr_hash = _hash16(stderr)
    stdout_bytes = len(stdout.encode()) if stdout else 0
    stderr_bytes = len(stderr.encode()) if stderr else 0
    command_preview = command[:_MAX_CMD_PREVIEW]
    stdout_preview = stdout[:_MAX_STDOUT_PREVIEW]
    stderr_preview = stderr[:_MAX_STDERR_PREVIEW]
    truncated = (
        len(command) > _MAX_CMD_PREVIEW
        or len(stdout) > _MAX_STDOUT_PREVIEW
        or len(stderr) > _MAX_STDERR_PREVIEW
    )

    # --- Emit event to ledger ---
    event_data: dict[str, Any] = {
        "tool": "Bash",
        "tool_ref": tool_ref,
        "command_hash": command_hash,
        "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes,
        "interrupted": interrupted,
    }

    append_event(
        package_root,
        "bash.executed",
        session_id,
        event_data,
        origin_type="posttool_hook",
        hook=_HOOK_NAME,
    )

    # --- Append detail record to side log ---
    detail_record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "tool_ref": tool_ref,
        "command_hash": command_hash,
        "command_preview": command_preview,
        "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes,
        "stdout_preview": stdout_preview,
        "stderr_preview": stderr_preview,
        "stdout_hash": stdout_hash,
        "stderr_hash": stderr_hash,
        "interrupted": interrupted,
        "isImage": is_image,
        "noOutputExpected": no_output_expected,
        "truncated": truncated,
    }

    custom_dir = os.path.join(package_root, "custom")
    bash_log_path = os.path.join(custom_dir, "bash_commands.jsonl")
    success = _atomic_jsonl_append(bash_log_path, detail_record)

    if success:
        update_health(package_root, "bash_capture", "healthy")
    else:
        record_error(
            package_root,
            "BASH_LOG_APPEND_FAILED",
            "warning",
            "bash_capture",
            "append_bash_commands_jsonl",
            message="Failed to append bash command record",
        )
        update_health(
            package_root, "bash_capture", "degraded",
            warning={"code": "BASH_LOG_APPEND_FAILED"},
        )

    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
