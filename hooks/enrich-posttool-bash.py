#!/usr/bin/env python3
"""PostToolUse(Bash) enrichment spool hook.

Non-blocking — writes qualifying outputs to the spool and exits immediately.
Qualifying: Bash output > 8K tokens (~32K chars).

Spool layout under /tmp/brick-lab/enrich-queue/:
  pending/{trace_id}.json   — spool metadata
  {trace_id}.raw            — raw output text
"""
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hook_utils import read_hook_input, run_fail_open
from brick_circuit import CircuitBreaker

_HOOK_NAME = "enrich-posttool-bash"
_EVENT_NAME = "PostToolUse"
_SPOOL_ROOT = "/tmp/brick-lab/enrich-queue"
_BASH_TOKEN_THRESHOLD = 8000
_AGENT_TOKEN_THRESHOLD = 4000


def estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ~= 4 chars."""
    return len(text) // 4


def should_spool_bash(output: str) -> bool:
    """Return True if Bash output exceeds the 8K-token threshold."""
    return estimate_tokens(output) > _BASH_TOKEN_THRESHOLD


def should_spool_agent(output: str, failed: bool) -> bool:
    """Return True if Agent output exceeds the 4K-token threshold OR failed."""
    if failed:
        return True
    return estimate_tokens(output) > _AGENT_TOKEN_THRESHOLD


def write_spool_entry(
    spool_root: str,
    tool: str,
    output: str,
    session_id: str,
    trace_id: str,
) -> None:
    """Atomically write a spool entry (pending JSON + raw output file)."""
    pending_dir = os.path.join(spool_root, "pending")
    os.makedirs(pending_dir, exist_ok=True)

    # Write raw output
    raw_path = os.path.join(spool_root, f"{trace_id}.raw")
    _atomic_write(raw_path, output)

    # Write spool metadata
    entry = {
        "tool": tool,
        "output_path": raw_path,
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trace_id": trace_id,
        "retry_count": 0,
    }
    pending_path = os.path.join(pending_dir, f"{trace_id}.json")
    _atomic_write(pending_path, json.dumps(entry, indent=2))


def _atomic_write(path: str, content: str) -> None:
    """Write content atomically via tmp + rename."""
    dir_name = os.path.dirname(path)
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        os.write(fd, content.encode())
        os.close(fd)
        os.rename(tmp_path, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _extract_output(tool_response: dict | str | None) -> str:
    """Extract text output from tool_response (may be dict or string)."""
    if tool_response is None:
        return ""
    if isinstance(tool_response, str):
        return tool_response
    if isinstance(tool_response, dict):
        return (
            tool_response.get("stdout")
            or tool_response.get("output")
            or tool_response.get("content", "")
        )
    return str(tool_response)


def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    if tool_name != "Bash":
        sys.exit(0)

    # Circuit breaker check — exit if OPEN (not allowing requests)
    cb = CircuitBreaker()
    if not cb.allow_request():
        sys.exit(0)

    output = _extract_output(input_data.get("tool_response"))
    if not output:
        sys.exit(0)

    if not should_spool_bash(output):
        sys.exit(0)

    session_id = input_data.get("session_id", "")
    trace_id = str(uuid.uuid4())

    write_spool_entry(_SPOOL_ROOT, "Bash", output, session_id, trace_id)
    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
