"""qLine hook utilities — stdin reading and fail-open execution.

# hook-utils-contract v2.0 -- update all copies if Claude Code hook stdin contract changes
Minimal shared module for qLine observability hooks.
"""
import glob
import hashlib
import json
import os
import select
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Callable


MAX_STDIN_BYTES = 1_048_576  # 1 MB


def now_iso() -> str:
    """UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()

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


try:
    from obs_utils import _atomic_jsonl_append
except ImportError:
    _atomic_jsonl_append = None


def _write_ledger_record(record: dict) -> None:
    """Atomic JSONL append to the fault ledger. Never raises."""
    try:
        if _atomic_jsonl_append is not None:
            _atomic_jsonl_append(_LEDGER_PATH, record)
            return
    except Exception:
        pass
    # Fallback: direct write if obs_utils unavailable or append fails
    try:
        os.makedirs(os.path.dirname(_LEDGER_PATH), exist_ok=True)
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
        "ts": now_iso(),
        "hook": hook_name,
        "event": event_name,
        "level": "fault",
        "reason_class": "unhandled_exception",
        "message": str(error),
        "traceback": tb,
        "context": context or {},
    })


def _write_hook_perf(
    session_id: str,
    hook_name: str,
    event_name: str,
    elapsed_ms: float,
) -> None:
    """Write a hook performance record to {package_root}/metadata/hook_perf.jsonl.

    Never raises — all errors are silently ignored.
    """
    try:
        try:
            from obs_utils import resolve_package_root_env
        except ImportError:
            return
        package_root = resolve_package_root_env(session_id)
        if not package_root:
            return
        record = {
            "ts": now_iso(),
            "hook": hook_name,
            "event": event_name,
            "duration_ms": round(elapsed_ms, 1),
        }
        perf_path = os.path.join(package_root, "metadata", "hook_perf.jsonl")
        try:
            if _atomic_jsonl_append is not None:
                _atomic_jsonl_append(perf_path, record)
                return
        except Exception:
            pass
        # Fallback: direct write
        os.makedirs(os.path.dirname(perf_path), exist_ok=True)
        line = json.dumps(record, default=str) + "\n"
        fd = os.open(perf_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode())
        finally:
            os.close(fd)
    except Exception:
        pass


def run_fail_open(
    main_fn: Callable,
    hook_name: str,
    event_name: str,
    *,
    session_id: str | None = None,
) -> None:
    """Run a hook main function with fail-open crash resistance.

    Catches Exception (not BaseException), logs the fault, then exits 0.
    SystemExit passes through naturally since it is not a subclass of Exception.

    If session_id is provided, wall-clock timing is recorded to
    {package_root}/metadata/hook_perf.jsonl (fail-open — never crashes).
    """
    t0 = time.monotonic()
    try:
        main_fn()
    except Exception as exc:
        log_hook_fault(hook_name, event_name, exc)
        sys.exit(0)
    finally:
        elapsed_ms = (time.monotonic() - t0) * 1000
        if session_id:
            _write_hook_perf(session_id, hook_name, event_name, elapsed_ms)


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


def iter_open_tasks(session_id: str):
    """Yield (task_dict, filename) for non-completed tasks in session task dir.

    session_id is the raw session ID; resolve_task_list_id is called internally.
    Silently yields nothing on missing dirs or parse errors.
    """
    task_path = os.path.join(
        os.path.expanduser("~"), ".claude", "tasks",
        resolve_task_list_id(session_id),
    )
    if not os.path.isdir(task_path):
        return
    try:
        entries = sorted(os.listdir(task_path))
    except OSError:
        return
    for fname in entries:
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(task_path, fname)) as f:
                task = json.load(f)
            if task.get("status") in ("pending", "in_progress"):
                yield task, fname
        except (json.JSONDecodeError, OSError, KeyError):
            continue


def hash16(s: str) -> str:
    """SHA-256 truncated to 16 hex chars."""
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
        "ts": now_iso(),
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


# ---------------------------------------------------------------------------
# v2.0 contract additions
# ---------------------------------------------------------------------------


def validate_session_id(session_id: Any) -> str | None:
    """Validate and normalize a session_id from hook input.

    Returns the stripped session_id string, or None if invalid.
    Rejects: non-string, empty/whitespace-only, >256 chars, null bytes.
    """
    if not session_id or not isinstance(session_id, str):
        return None
    session_id = session_id.strip()
    if not session_id or len(session_id) > 256 or "\x00" in session_id:
        return None
    return session_id


def validate_payload_structure(data: dict, required_keys: set) -> bool:
    """Lightweight schema check — reject payloads missing required keys."""
    if not isinstance(data, dict):
        return False
    return required_keys.issubset(data.keys())


SCHEMA_SESSION_START = {"session_id"}
SCHEMA_PRETOOL_USE = {"session_id", "tool_name", "tool_input"}
SCHEMA_POSTTOOL_USE = {"session_id", "tool_name", "tool_input", "tool_response"}
SCHEMA_PROMPT_SUBMIT = {"session_id"}
SCHEMA_SESSION_END = {"session_id"}


class Deadline:
    """Wall-clock budget that propagates through sub-calls.
    NOT a context manager. Use remaining() and check().
    """
    __slots__ = ("_expires",)

    def __init__(self, budget_s: float = 3.0):
        self._expires = time.monotonic() + budget_s

    def remaining(self) -> float:
        return max(0.0, self._expires - time.monotonic())

    def check(self, op: str = "") -> None:
        if self.remaining() == 0:
            raise TimeoutError(f"Latency budget exhausted{f' at: {op}' if op else ''}")


def log_hook_event(
    hook_name: str,
    event_name: str,
    outcome: str,
    duration_ms: float,
    extras: dict | None = None,
) -> None:
    """Write an info-level timing record to the fault ledger."""
    _write_ledger_record({
        "ts": now_iso(),
        "hook": hook_name,
        "event": event_name,
        "level": "info",
        "outcome": outcome,
        "duration_ms": round(duration_ms, 1),
        **(extras or {}),
    })


def subprocess_resource_limits() -> None:
    """Apply resource limits to child processes. Use as preexec_fn."""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (5, 10))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 128))
        resource.setrlimit(resource.RLIMIT_NPROC, (16, 32))
    except Exception:
        pass


_CIRCUIT_PATH = os.path.join(
    os.path.expanduser("~"), ".claude", "logs", "hook-circuit.json"
)
_CIRCUIT_OPEN_THRESHOLD = 3
_CIRCUIT_RECOVERY_S = 120


def circuit_is_open(service: str) -> bool:
    """Check if circuit breaker is open for a service. Never raises."""
    try:
        with open(_CIRCUIT_PATH) as f:
            state = json.load(f)
        s = state.get(service, {})
        if s.get("failures", 0) >= _CIRCUIT_OPEN_THRESHOLD:
            return (time.time() - s.get("opened_at", 0)) < _CIRCUIT_RECOVERY_S
    except Exception:
        pass
    return False


def record_circuit_result(service: str, success: bool) -> None:
    """Record a success or failure for circuit breaker state. Never raises."""
    try:
        try:
            with open(_CIRCUIT_PATH) as f:
                state = json.load(f)
        except Exception:
            state = {}

        s = state.setdefault(service, {"failures": 0})
        if success:
            s["failures"] = 0
            s.pop("opened_at", None)
        else:
            s["failures"] = s.get("failures", 0) + 1
            if s["failures"] >= _CIRCUIT_OPEN_THRESHOLD:
                s["opened_at"] = time.time()

        fd = os.open(_CIRCUIT_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            os.write(fd, json.dumps(state).encode())
        finally:
            os.close(fd)
    except Exception:
        pass
