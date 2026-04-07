"""Shared session observability utilities for Claude Code lifecycle hooks.

Package-aware glue layer. Does NOT re-implement:
- stdin reading / timeout  →  use hook_utils.read_hook_input()
- crash-to-ledger          →  use hook_utils.run_fail_open()
- global fault ledger      →  use hook_utils.log_hook_fault()

Directory layout produced by create_package():
  <obs_root>/
    sessions/
      <YYYY-MM-DD>/
        <session_id>/
          manifest.json
          source_map.json
          metadata/
            hook_events.jsonl
            errors.jsonl
            artifact_index.jsonl
            .seq_counter
    runtime/
      <session_id>.json   ← lookup key for resolve_package_root()
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

from hook_utils import _now_iso  # canonical timestamp; defined in hook_utils to keep dependency direction correct

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_DEFAULT_OBS_ROOT = os.path.join(os.path.expanduser("~"), ".claude", "observability")

# Per-process cache; hooks are separate processes so no cross-session leakage.
# Dict operations are GIL-protected — no additional locking needed.
_health_cache: dict[tuple[str, str], tuple[str, dict | None]] = {}

_INITIAL_HEALTH: dict[str, Any] = {
    "overall": "initializing",
    "subsystems": {
        "core_packaging": "healthy",
        "transcript_linkage": "healthy",
        "transcript_archive": "unavailable",
        "hook_ledger": "healthy",
        "statusline_capture": "unavailable",
        "subagent_archive": "healthy",
        "task_capture": "healthy",
        "patch_capture": "healthy",
        "read_audit": "healthy",
        "derived_analysis": "unavailable",
        "otel_correlation": "unavailable",
    },
    "warnings": [],
    "errors": [],
}


def _load_read_state(state_path: str) -> dict[str, Any]:
    """Load read state sidecar. Returns {} on any error."""
    try:
        with open(state_path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_read_state(state_path: str, state: dict) -> None:
    """Write read state sidecar atomically. Never raises.

    Evicts oldest entries (by last_read_seq) when the state dict exceeds
    500 entries, keeping only the 500 most-recently-accessed files.
    """
    try:
        if len(state) > 500:
            sorted_keys = sorted(
                state.keys(),
                key=lambda k: state[k].get("last_read_seq", 0) if isinstance(state[k], dict) else 0,
            )
            for evict_key in sorted_keys[: len(state) - 500]:
                del state[evict_key]
        parent = os.path.dirname(state_path)
        if parent and parent not in _dirs_ensured:
            os.makedirs(parent, exist_ok=True)
            _dirs_ensured.add(parent)
        tmp_path = state_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(state, f)
        os.replace(tmp_path, state_path)
    except Exception:
        pass


_dirs_ensured: set[str] = set()


def _atomic_jsonl_append(path: str, record: dict) -> bool:
    """O_APPEND write. Returns True on success, False on failure. Never raises."""
    try:
        parent = os.path.dirname(path)
        if parent and parent not in _dirs_ensured:
            os.makedirs(parent, exist_ok=True)
            _dirs_ensured.add(parent)
        line = json.dumps(record, default=str) + "\n"
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode())
        finally:
            os.close(fd)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Tier 0: Package creation and runtime mapping
# ---------------------------------------------------------------------------


def create_package(
    session_id: str,
    cwd: str,
    transcript_path: str,
    source: str,
    *,
    obs_root: str = _DEFAULT_OBS_ROOT,
) -> str:
    """Create a session observability package and register it in the runtime map.

    Returns the package_root path.
    Raises OSError on Tier 0 failures (can't create dirs or write manifest).
    """
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    package_root = os.path.join(obs_root, "sessions", date_str, session_id)

    # Create directory tree — Tier 0: raise on failure
    os.makedirs(os.path.join(package_root, "metadata"), exist_ok=True)

    # Touch JSONL stub files
    for stub in ("hook_events.jsonl", "errors.jsonl", "artifact_index.jsonl"):
        stub_path = os.path.join(package_root, "metadata", stub)
        if not os.path.exists(stub_path):
            open(stub_path, "a").close()  # noqa: WPS515 — intentional touch

    # Initialise seq counter
    seq_path = os.path.join(package_root, "metadata", ".seq_counter")
    if not os.path.exists(seq_path):
        with open(seq_path, "w") as f:
            f.write("0")

    # Write manifest.json — Tier 0: raise on failure
    manifest: dict[str, Any] = {
        "session_id": session_id,
        "cwd": cwd,
        "source": source,
        "transcript_path": transcript_path,
        "package_root": package_root,
        "status": "active",
        "created_at": _now_iso(),
        "native_links": {
            "transcript": "native/transcripts/main.jsonl",
            "transcript_origin": transcript_path,
        },
        "subagents": [],
        "tasks": [],
        "compactions": [],
        "patches": {"count": 0, "files_touched": [], "total_added": 0, "total_removed": 0},
        "health": {
            "overall": _INITIAL_HEALTH["overall"],
            "subsystems": dict(_INITIAL_HEALTH["subsystems"]),
            "warnings": list(_INITIAL_HEALTH["warnings"]),
            "errors": list(_INITIAL_HEALTH["errors"]),
        },
    }
    manifest_path = os.path.join(package_root, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    # Write source_map.json
    source_map: dict[str, Any] = {
        "session_id": session_id,
        "cwd": cwd,
        "transcript_path": transcript_path,
        "source": source,
        "created_at": _now_iso(),
    }
    source_map_path = os.path.join(package_root, "source_map.json")
    with open(source_map_path, "w") as f:
        json.dump(source_map, f, indent=2)

    # Write runtime mapping — Tier 0: raise on failure
    runtime_dir = os.path.join(obs_root, "runtime")
    os.makedirs(runtime_dir, exist_ok=True)
    runtime_record: dict[str, Any] = {
        "package_root": package_root,
        "session_id": session_id,
        "created_at": _now_iso(),
    }
    runtime_path = os.path.join(runtime_dir, f"{session_id}.json")
    with open(runtime_path, "w") as f:
        json.dump(runtime_record, f, indent=2)

    return package_root


_package_root_cache: dict[str, str | None] = {}


def resolve_package_root_env(session_id: str) -> str | None:
    """Resolve package root, respecting OBS_ROOT env override."""
    obs_root = os.environ.get("OBS_ROOT")
    kwargs = {"obs_root": obs_root} if obs_root else {}
    return resolve_package_root(session_id, **kwargs)


def resolve_package_root(
    session_id: str,
    *,
    obs_root: str = _DEFAULT_OBS_ROOT,
) -> str | None:
    """Lookup package_root for session_id via the runtime map.

    Returns None if the session is unknown or the mapping is invalid.
    session_id is the universal lookup key across all hooks and the statusline.
    Cached after first lookup (the runtime map never changes after session start).
    """
    if session_id in _package_root_cache:
        return _package_root_cache[session_id]
    runtime_path = os.path.join(obs_root, "runtime", f"{session_id}.json")
    try:
        with open(runtime_path) as f:
            data = json.load(f)
        pkg = data.get("package_root")
        result = pkg if isinstance(pkg, str) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        result = None
    _package_root_cache[session_id] = result
    return result


# ---------------------------------------------------------------------------
# Tier 1: Sequence counter
# ---------------------------------------------------------------------------


def next_seq(package_root: str) -> int:
    """Atomic file-based monotonic counter using fcntl.flock.

    Fallback: timestamp-based pseudo-seq on any failure.
    """
    seq_path = os.path.join(package_root, "metadata", ".seq_counter")
    try:
        with open(seq_path, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                val = int(f.read().strip() or "0")
                new_val = val + 1
                f.seek(0)
                f.write(str(new_val))
                f.truncate()
                return new_val
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        # Fallback: use microseconds as pseudo-seq (never raises)
        return int(time.time() * 1_000_000)


# ---------------------------------------------------------------------------
# Tier 1: Event and error appenders
# ---------------------------------------------------------------------------


def append_event(
    package_root: str,
    event: str,
    session_id: str,
    data: dict,
    origin_type: str,
    hook: str,
    **extra: Any,
) -> int:
    """Append a JSONL record to metadata/hook_events.jsonl.

    Returns the seq number used.
    Ledger write failures are surfaced to the health model (hook_ledger degraded).
    """
    seq = next_seq(package_root)
    record: dict[str, Any] = {
        "seq": seq,
        "ts": _now_iso(),
        "event": event,
        "session_id": session_id,
        "data": data,
        "origin_type": origin_type,
        "hook": hook,
    }
    record.update(extra)
    path = os.path.join(package_root, "metadata", "hook_events.jsonl")
    success = _atomic_jsonl_append(path, record)
    if not success:
        # Ledger write failed — mark subsystem degraded.
        # Use update_health directly (not record_error) to avoid circular dependency.
        update_health(
            package_root,
            "hook_ledger",
            "degraded",
            warning={"code": "LEDGER_WRITE_FAILED", "seq": seq},
        )
    return seq


def record_error(
    package_root: str,
    code: str,
    severity: str,
    subsystem: str,
    action: str,
    *,
    message: str = "",
    **extra: Any,
) -> None:
    """Append a structured error record to metadata/errors.jsonl.

    Never raises (Tier 1 resilience contract).
    """
    record: dict[str, Any] = {
        "ts": _now_iso(),
        "code": code,
        "severity": severity,
        "subsystem": subsystem,
        "action": action,
        "message": message,
    }
    record.update(extra)
    path = os.path.join(package_root, "metadata", "errors.jsonl")
    _atomic_jsonl_append(path, record)


def register_artifact(
    package_root: str,
    artifact_id: str,
    *,
    artifact_type: str = "",
    path: str = "",
    **extra: Any,
) -> None:
    """Append an artifact registration record to metadata/artifact_index.jsonl.

    Never raises (Tier 1 resilience contract).
    """
    record: dict[str, Any] = {
        "ts": _now_iso(),
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "path": path,
    }
    record.update(extra)
    index_path = os.path.join(package_root, "metadata", "artifact_index.jsonl")
    _atomic_jsonl_append(index_path, record)


# ---------------------------------------------------------------------------
# Tier 1: Manifest mutators (flock-protected)
# ---------------------------------------------------------------------------


def _read_manifest(manifest_path: str, f: Any) -> dict[str, Any]:
    """Read and parse manifest from an open file object. Returns {} on error."""
    try:
        f.seek(0)
        return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return {}


def update_manifest(package_root: str, updates: dict) -> None:
    """flock-protected read-parse-merge-write of manifest.json.

    Top-level keys from `updates` are merged into the manifest.
    Never raises (Tier 1 resilience contract).
    """
    manifest_path = os.path.join(package_root, "manifest.json")
    try:
        with open(manifest_path, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                manifest = _read_manifest(manifest_path, f)
                manifest.update(updates)
                f.seek(0)
                f.write(json.dumps(manifest, indent=2))
                f.truncate()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        pass


def update_manifest_array(package_root: str, key: str, entry: dict) -> None:
    """flock-protected append to a manifest array field.

    Creates the array if the key is absent.
    Never raises (Tier 1 resilience contract).
    """
    manifest_path = os.path.join(package_root, "manifest.json")
    try:
        with open(manifest_path, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                manifest = _read_manifest(manifest_path, f)
                arr = manifest.get(key)
                if not isinstance(arr, list):
                    arr = []
                arr.append(entry)
                manifest[key] = arr
                f.seek(0)
                f.write(json.dumps(manifest, indent=2))
                f.truncate()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        pass




def generate_overhead_report(
    package_root: str,
    transcript_path: str,
    context_window_size: int = 1_000_000,
) -> "dict | None":
    """Generate overhead report from full transcript JSONL.

    Re-reads entire transcript for complete session analysis.
    Writes to derived/overhead_report.json.
    """
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None

    turns: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        msg = entry.get("message")
        if isinstance(msg, dict) and msg.get("stop_reason") is not None:
            usage = msg.get("usage")
            if isinstance(usage, dict):
                turns.append(usage)
                continue
        tur = entry.get("toolUseResult")
        if isinstance(tur, dict):
            usage = tur.get("usage")
            if isinstance(usage, dict):
                turns.append(usage)

    if not turns:
        return None

    anchor = turns[0].get("cache_creation_input_tokens", 0)

    total_cache_read = sum(t.get("cache_read_input_tokens", 0) for t in turns)
    total_cache_create = sum(t.get("cache_creation_input_tokens", 0) for t in turns)
    total_fresh = sum(t.get("input_tokens", 0) for t in turns)

    denom = total_cache_read + total_cache_create
    hit_rate = total_cache_read / denom if denom > 0 else 0.0

    busting_turns = [
        i for i, t in enumerate(turns)
        if t.get("cache_creation_input_tokens", 0) > t.get("cache_read_input_tokens", 0)
        and i > 0
    ]

    theoretical_input = anchor + total_fresh
    actual_input = total_cache_read + total_cache_create + total_fresh
    cost_mult = actual_input / theoretical_input if theoretical_input > 0 else 1.0

    report = {
        "total_turns": len(turns),
        "system_overhead_tokens": anchor,
        "system_overhead_source": "first_turn_anchor",
        "system_overhead_pct_of_window": round(anchor * 100 / context_window_size, 1)
        if context_window_size > 0 else 0,
        "cache_hit_rate_overall": round(hit_rate, 4),
        "cache_busting_events": len(busting_turns),
        "cache_busting_turns": busting_turns,
        "total_cache_read_tokens": total_cache_read,
        "total_cache_create_tokens": total_cache_create,
        "total_fresh_input_tokens": total_fresh,
        "effective_cost_multiplier": round(cost_mult, 2),
    }

    derived_dir = os.path.join(package_root, "derived")
    os.makedirs(derived_dir, exist_ok=True)
    report_path = os.path.join(derived_dir, "overhead_report.json")
    try:
        tmp_path = report_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(report, f, indent=2)
        os.rename(tmp_path, report_path)
    except OSError:
        pass

    return report



def update_manifest_if_absent_batch(
    package_root: str, gate_key: str, updates: dict[str, Any]
) -> bool:
    """Write multiple keys to manifest only if gate_key is absent.

    Uses fcntl.LOCK_EX. Atomically writes all keys or none.
    Returns True if written, False if gate_key already existed.
    Never raises (Tier 1 resilience contract).
    """
    manifest_path = os.path.join(package_root, "manifest.json")
    try:
        with open(manifest_path, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                manifest = _read_manifest(manifest_path, f)
                if gate_key in manifest:
                    return False
                manifest.update(updates)
                f.seek(0)
                f.write(json.dumps(manifest, indent=2))
                f.truncate()
                return True
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        return False

def update_health(
    package_root: str,
    subsystem: str,
    state: str,
    warning: dict | None = None,
) -> None:
    """Update subsystem health state and recompute overall health.

    Overall health rules:
      - 'degraded' if any subsystem is 'degraded'
      - 'healthy'  if all subsystems are 'healthy'
      - 'initializing' otherwise (mix of healthy/unavailable)

    Never raises (Tier 1 resilience contract).

    Skips all I/O when the subsystem's state and warning are unchanged
    from the last successful write — eliminates the flock cycle for repeated
    "healthy" reports (the common case).
    """
    cache_key = (package_root, subsystem)
    cached = _health_cache.get(cache_key)
    if cached is not None and cached == (state, warning):
        # No change — skip the flock read-modify-write entirely.
        return

    manifest_path = os.path.join(package_root, "manifest.json")
    try:
        with open(manifest_path, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                manifest = _read_manifest(manifest_path, f)
                health = manifest.setdefault("health", {})
                subsystems = health.setdefault("subsystems", {})
                warnings_list = health.setdefault("warnings", [])

                # Update the target subsystem
                subsystems[subsystem] = state

                # Append warning if provided (cap at 50 to bound manifest size)
                if warning is not None:
                    warnings_list.append(warning)
                    if len(warnings_list) > 50:
                        warnings_list[:] = warnings_list[-50:]

                # Recompute overall health
                states = set(subsystems.values())
                if "failed" in states:
                    health["overall"] = "incomplete"
                elif "degraded" in states:
                    health["overall"] = "degraded"
                elif states <= {"healthy", "unavailable", "disabled"}:
                    health["overall"] = "healthy"
                else:
                    health["overall"] = "initializing"

                f.seek(0)
                f.write(json.dumps(manifest, indent=2))
                f.truncate()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        _health_cache[cache_key] = (state, warning)
    except Exception:
        pass
