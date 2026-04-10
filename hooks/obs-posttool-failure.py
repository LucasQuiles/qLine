#!/usr/bin/env python3
"""PostToolUseFailure observability hook: records tool execution failures.

Scope: All tools (matcher: .*). No tool_name filter.
Only Bash failure shape is proved; other tools handled defensively.
"""
from typing import Any

from hook_utils import run_fail_open, run_obs_hook, hash16
from obs_utils import append_event

_HOOK_NAME = "obs-posttool-failure"
_EVENT_NAME = "PostToolUseFailure"


def _handle(input_data: dict, session_id: str, package_root: str) -> None:
    tool_name = input_data.get("tool_name", "unknown")
    tool_ref = input_data.get("tool_use_id", "")
    error = input_data.get("error", "")
    is_interrupt = input_data.get("is_interrupt", False)

    event_data: dict[str, Any] = {
        "tool_name": tool_name,
        "tool_ref": tool_ref,
        "error": error,
        "is_interrupt": is_interrupt,
    }

    tool_input = input_data.get("tool_input", {})
    if tool_name == "Bash" and isinstance(tool_input, dict):
        command = tool_input.get("command", "")
        if command:
            event_data["command_preview"] = command[:500]
            event_data["command_hash"] = hash16(command)

    append_event(
        package_root,
        "tool.failed",
        session_id,
        event_data,
        origin_type="posttool_hook",
        hook=_HOOK_NAME,
    )


if __name__ == "__main__":
    run_fail_open(lambda: run_obs_hook(_handle, _HOOK_NAME, _EVENT_NAME), _HOOK_NAME, _EVENT_NAME)
