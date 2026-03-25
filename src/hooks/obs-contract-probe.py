#!/opt/homebrew/bin/python3.12
"""Disposable probe: captures payload fixtures for unproven observability contract fields.

Registered for: SessionStart, PreToolUse(Read), PostToolUse(Write|Edit|MultiEdit),
                UserPromptSubmit.
Writes raw payloads to ~/.claude/tests/fixtures/obs-contracts/.
Does NOT block or modify any behavior — purely observational.

TEMPORARY: Remove after fixtures are captured and documented.
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
from hook_utils import read_hook_input

FIXTURE_DIR = os.path.expanduser("~/.claude/tests/fixtures/obs-contracts")


def main():
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    event_name = input_data.get("hook_event_name", "unknown")
    tool_name = input_data.get("tool_name", "")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if tool_name:
        fixture_name = f"{event_name}-{tool_name}-{timestamp}.json"
    else:
        fixture_name = f"{event_name}-{timestamp}.json"

    os.makedirs(FIXTURE_DIR, exist_ok=True)
    fixture_path = os.path.join(FIXTURE_DIR, fixture_name)

    redacted = _redact_large_fields(input_data)

    with open(fixture_path, "w") as f:
        json.dump(redacted, f, indent=2, default=str)

    env_capture = {
        "CLAUDE_ENV_FILE": os.environ.get("CLAUDE_ENV_FILE"),
        "OBS_PACKAGE_ROOT": os.environ.get("OBS_PACKAGE_ROOT"),
        "CLAUDE_CODE_TASK_LIST_ID": os.environ.get("CLAUDE_CODE_TASK_LIST_ID"),
        "HOME": os.environ.get("HOME"),
    }
    env_path = os.path.join(FIXTURE_DIR, f"env-{event_name}-{tool_name or 'none'}-{timestamp}.json")
    with open(env_path, "w") as f:
        json.dump(env_capture, f, indent=2)

    print(f"[obs-contract-probe] Captured {event_name}/{tool_name} -> {fixture_path}", file=sys.stderr)
    sys.exit(0)


def _redact_large_fields(data, max_str_len=2000):
    if isinstance(data, dict):
        return {k: _redact_large_fields(v, max_str_len) for k, v in data.items()}
    if isinstance(data, list):
        return [_redact_large_fields(item, max_str_len) for item in data]
    if isinstance(data, str) and len(data) > max_str_len:
        return f"[REDACTED: {len(data)} chars]"
    return data


if __name__ == "__main__":
    main()
