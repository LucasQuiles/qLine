"""qLine hook utilities — stdin reading and fail-open execution.

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
