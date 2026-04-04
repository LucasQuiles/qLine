"""Shared hook IO utilities for Claude Code native hooks.

Provides stdin reading with timeout, JSON parsing, and structured
response helpers. Mirrors the pattern established by secret_policy.py.

Usage in hook scripts:
    import sys
    sys.path.insert(0, os.path.expanduser("~/.claude/scripts"))
    from hook_utils import read_hook_input, deny, allow_with_context
"""
import json
import os
import select
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Callable


MAX_STDIN_BYTES = 1_048_576  # 1 MB — prevent unbounded memory allocation


def read_stdin_with_timeout(timeout_seconds: int = 2) -> str | None:
    """Read stdin with timeout to prevent hangs."""
    if select.select([sys.stdin], [], [], timeout_seconds)[0]:
        return sys.stdin.read(MAX_STDIN_BYTES)
    return None


def read_hook_input(timeout_seconds: int = 2) -> dict[str, Any] | None:
    """Read and parse hook JSON input from stdin.

    Returns parsed dict or None on timeout, parse failure, or non-object JSON.
    Hooks should exit(0) when None is returned (allow-by-default).
    """
    raw = read_stdin_with_timeout(timeout_seconds)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def sanitize_task_list_id(task_list_id: str) -> str:
    """Mirror Claude's local task-list directory sanitization.

    Native task storage uses a sanitized directory name for task-list IDs.
    Keep hook-side task readers aligned so env-var overrides cannot escape the
    task root or diverge from the native task directory shape.
    """
    return "".join(
        c if ((c.isascii() and c.isalnum()) or c in {"_", "-"}) else "-"
        for c in task_list_id
    )


def get_tool_info(input_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Extract tool_name and tool_input from hook input."""
    return (
        input_data.get("tool_name", ""),
        input_data.get("tool_input", {}),
    )


def deny(reason: str, event: str = "PreToolUse") -> None:
    """Print a deny response and exit 0.

    The hook protocol requires exit 0 even on deny — the JSON response
    carries the permission decision.
    """
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def is_strict(env_var: str) -> bool:
    """Check if a strict-mode env flag is set (truthy: 1, true, yes)."""
    val = os.environ.get(env_var, "").lower()
    return val in ("1", "true", "yes")


def block_stop(reason: str) -> None:
    """Print a SubagentStop block decision and exit 0.

    Uses the Stop-format JSON: {"decision": "block", "reason": "..."}.
    """
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SubagentStop",
            "decision": "block",
            "reason": reason,
        }
    }))
    sys.exit(0)


def allow_with_context(context: str, event: str = "PreToolUse") -> None:
    """Print an allow response with additional context injected into the conversation."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": context,
        }
    }))
    sys.exit(0)


# ---------------------------------------------------------------------------
# Fault ledger — structured observability for lifecycle hooks
# ---------------------------------------------------------------------------

_LEDGER_PATH = os.path.join(
    os.path.expanduser("~"), ".claude", "logs", "lifecycle-hook-faults.jsonl"
)


def _write_ledger_record(record: dict) -> None:
    """Atomic JSONL append to the fault ledger. Never raises."""
    try:
        ledger_dir = os.path.dirname(_LEDGER_PATH)
        os.makedirs(ledger_dir, exist_ok=True)
        line = json.dumps(record, default=str) + "\n"
        fd = os.open(_LEDGER_PATH, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode())
        finally:
            os.close(fd)
    except Exception:
        pass


def log_hook_fault(
    hook_name: str,
    event_name: str,
    error: Exception,
    context: dict | None = None,
) -> None:
    """Write a fault-level record with traceback extract."""
    tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    _write_ledger_record({
        "ts": datetime.now(timezone.utc).isoformat(),
        "hook": hook_name,
        "event": event_name,
        "level": "fault",
        "reason_class": "unhandled_exception",
        "message": str(error),
        "traceback": tb,
        "context": context or {},
    })


def log_hook_diagnostic(
    hook_name: str,
    event_name: str,
    reason_class: str,
    message: str,
    level: str = "diagnostic",
    context: dict | None = None,
) -> None:
    """Write a diagnostic or warning record."""
    _write_ledger_record({
        "ts": datetime.now(timezone.utc).isoformat(),
        "hook": hook_name,
        "event": event_name,
        "level": level,
        "reason_class": reason_class,
        "message": message,
        "context": context or {},
    })


def run_fail_open(main_fn: Callable, hook_name: str, event_name: str) -> None:
    """Run a hook main function with fail-open crash resistance.

    Catches Exception (not BaseException), logs the fault, then exits 0.
    SystemExit passes through naturally since it is not a subclass of Exception.
    """
    try:
        main_fn()
    except Exception as exc:
        log_hook_fault(hook_name, event_name, exc)
        sys.exit(0)
