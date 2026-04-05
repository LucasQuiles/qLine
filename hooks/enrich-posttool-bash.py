#!/usr/bin/env python3
"""PostToolUse(Bash) enrichment spool hook.

Non-blocking — writes qualifying outputs to the spool and exits immediately.

v2 trigger: risk-based — fires on nonzero exit, error patterns, stack traces,
large output, or build warnings in medium output.

Spool layout under /tmp/brick-lab/enrich-queue/:
  pending/{trace_id}.json   — spool metadata
  {trace_id}.raw            — raw output text
"""
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hook_utils import read_hook_input, run_fail_open
from brick_circuit import CircuitBreaker
from brick_metrics import log_enrichment

_TEST_PATTERNS = [
    (re.compile(r'\b(pytest|python\s+-m\s+pytest)\b'), 'pytest'),
    (re.compile(r'\b(vitest|npx\s+vitest)\b'), 'vitest'),
    (re.compile(r'\b(jest|npx\s+jest)\b'), 'jest'),
    (re.compile(r'\bcargo\s+test\b'), 'cargo_test'),
    (re.compile(r'\b(npm\s+test|npm\s+run\s+test)\b'), 'npm_test'),
    (re.compile(r'\b(make\s+test|make\s+check)\b'), 'make'),
]


def detect_command_family(command: str) -> str:
    """Detect if a command is a known test runner. Returns family name or 'unknown'."""
    for pattern, family in _TEST_PATTERNS:
        if pattern.search(command):
            return family
    return "unknown"


_HOOK_NAME = "enrich-posttool-bash"
_EVENT_NAME = "PostToolUse"
_SPOOL_ROOT = "/tmp/brick-lab/enrich-queue"
_BASH_TOKEN_THRESHOLD = 8000
_AGENT_TOKEN_THRESHOLD = 4000


def estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ~= 4 chars."""
    return len(text) // 4


def should_spool_bash(output: str) -> bool:
    """Return True if Bash output exceeds the 8K-token threshold.

    .. deprecated:: v2
        Use :func:`should_spool_bash_v2` which applies risk-based triggering.
    """
    return estimate_tokens(output) > _BASH_TOKEN_THRESHOLD


# ── v2 risk-based trigger patterns ──────────────────────────────────────────

_ERROR_PATTERNS = re.compile(
    r'\b(ERROR|FAILED|Exception|panic|FATAL|Traceback|TypeError|SyntaxError|'
    r'AssertionError|ModuleNotFoundError|ImportError|NameError|RuntimeError)\b',
    re.IGNORECASE,
)

_STACK_TRACE_PATTERNS = re.compile(
    r'(File "/.+", line \d+|at Object\.<anonymous>|^\s+at\s+)',
    re.MULTILINE,
)

_WARNING_PATTERNS = re.compile(
    r'(?:\bwarning:|(?<!\w)WARN\b|\bdeprecated\b)',
    re.IGNORECASE,
)


def should_spool_bash_v2(
    output: str, exit_code: int | None, command: str,
) -> tuple[bool, str]:
    """Risk-based trigger for Bash enrichment.

    Returns ``(should_spool, reason)`` where *reason* is a short tag
    suitable for metrics (e.g. ``"nonzero_exit"``, ``"error_pattern"``).
    """
    tokens = estimate_tokens(output)

    # Rule 1: Any nonzero exit code
    if exit_code is not None and exit_code != 0:
        return True, "nonzero_exit"

    # Rule 2: Error patterns in output
    if _ERROR_PATTERNS.search(output):
        return True, "error_pattern"

    # Rule 3: Stack traces
    if _STACK_TRACE_PATTERNS.search(output):
        return True, "stack_trace"

    # Rule 4: Test runner failures — already covered by Rule 1

    # Rule 5: Large output (original threshold for successful commands)
    if tokens > _BASH_TOKEN_THRESHOLD:
        return True, "large_output"

    # Rule 6: Build warnings in medium-sized output
    if tokens > 1000 and _WARNING_PATTERNS.search(output):
        return True, "build_warnings"

    return False, ""


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
    *,
    extra: dict | None = None,
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
    if extra:
        entry.update(extra)
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
    session_id = input_data.get("session_id", "")
    if not cb.allow_request():
        log_enrichment("bash", session_id, "Bash", action="skipped", reason="circuit_open")
        sys.exit(0)

    tool_response = input_data.get("tool_response")
    output = _extract_output(tool_response)
    if not output:
        sys.exit(0)

    command = input_data.get("tool_input", {}).get("command", "")
    exit_code = (
        tool_response.get("exit_code")
        if isinstance(tool_response, dict)
        else None
    )
    command_family = detect_command_family(command)

    # v2: risk-based trigger
    should_spool, reason = should_spool_bash_v2(output, exit_code, command)
    if not should_spool:
        log_enrichment("bash", session_id, "Bash", action="skipped", reason="below_threshold", command_family=command_family)
        sys.exit(0)

    trace_id = str(uuid.uuid4())

    write_spool_entry(
        _SPOOL_ROOT,
        "Bash",
        output,
        session_id,
        trace_id,
        extra={
            "command": command,
            "command_family": command_family,
            "exit_code": exit_code,
            "trigger_reason": reason,
        },
    )
    log_enrichment("bash", session_id, "Bash", action="spool", command_family=command_family, reason=reason)
    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
