#!/opt/homebrew/bin/python3.12
"""PostToolUseFailure observability hook: records tool execution failures.

Scope: All tools (matcher: .*). No tool_name filter.
Only Bash failure shape is proved; other tools handled defensively.
"""
import hashlib
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
from hook_utils import read_hook_input, run_fail_open
from obs_utils import resolve_package_root, append_event

_HOOK_NAME = "obs-posttool-failure"
_EVENT_NAME = "PostToolUseFailure"


def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = input_data.get("session_id")
    if not session_id:
        sys.exit(0)

    obs_root_override = os.environ.get("OBS_ROOT")
    kwargs: dict = {}
    if obs_root_override:
        kwargs["obs_root"] = obs_root_override

    package_root = resolve_package_root(session_id, **kwargs)
    if package_root is None:
        sys.exit(0)

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
            event_data["command_hash"] = hashlib.sha256(command.encode()).hexdigest()[:16]

    append_event(
        package_root,
        "tool.failed",
        session_id,
        event_data,
        origin_type="posttool_hook",
        hook=_HOOK_NAME,
    )

    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
