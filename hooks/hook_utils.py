"""qLine hook utilities — stdin reading and fail-open execution.

# hook-utils-contract v1.0 -- update all copies if Claude Code hook stdin contract changes
Minimal shared module for qLine observability hooks.
"""
import json
import os
import select
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Callable


MAX_STDIN_BYTES = 1_048_576  # 1 MB

_LEDGER_PATH = os.path.join(
    os.path.expanduser("~"), ".claude", "logs", "lifecycle-hook-faults.jsonl"
)


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


# --- Session quality hook functions ---
# Used by precompact-preserve, session-end-summary, subagent-stop-gate, task-completed-gate


def sanitize_task_list_id(task_list_id: str) -> str:
    """Mirror Claude's local task-list directory sanitization."""
    return "".join(
        c if ((c.isascii() and c.isalnum()) or c in {"_", "-"}) else "-"
        for c in task_list_id
    )


def resolve_task_list_id(session_id: str) -> str:
    """Resolve the local task-list directory ID for hook-side task reads.

    Hooks can safely honor the documented/local env-var override but do not try to
    mirror deeper Claude-internal fallback resolution beyond that.
    """
    override = os.environ.get("CLAUDE_CODE_TASK_LIST_ID")
    if override:
        return sanitize_task_list_id(override)
    return session_id


def find_latest_plan() -> str | None:
    """Find the most recently modified plan file. Returns basename or None."""
    import glob
    plan_dir = os.path.expanduser("~/.claude/plans")
    if not os.path.isdir(plan_dir):
        return None
    plans = glob.glob(os.path.join(plan_dir, "*.md"))
    if not plans:
        return None
    try:
        latest = max(plans, key=os.path.getmtime)
        return os.path.basename(latest)
    except (OSError, ValueError):
        return None


def hash16(s: str) -> str:
    """SHA-256 truncated to 16 hex chars."""
    import hashlib
    return hashlib.sha256(s.encode()).hexdigest()[:16]


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


def is_strict(env_var: str) -> bool:
    """Check if a strict-mode env flag is set (truthy: 1, true, yes)."""
    val = os.environ.get(env_var, "").lower()
    return val in ("1", "true", "yes")


def block_stop(reason: str, event: str = "SubagentStop") -> None:
    """Print a stop-block decision and exit 0."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event,
            "decision": "block",
            "reason": reason,
        }
    }))
    sys.exit(0)
