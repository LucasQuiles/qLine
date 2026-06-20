# hooks/precompact_capsule.py
"""PreCompact capsule schema — the single versioned receipt for the orchestrator.

One schema, many producers. Each producer contributes named sections; the
orchestrator records which producers succeeded, failed, or returned nothing.
"""
from __future__ import annotations

import json as _json
import os as _os

from precompact_paths import safe_name as _safe_name
from precompact_config import capsule_dir as _capsule_dir

CAPSULE_SCHEMA_VERSION = 1

# Section keys each producer may contribute. Order = render order.
SECTION_KEYS = (
    "open_tasks",       # preserve
    "active_plan",      # preserve
    "git_state",        # git
    "unresolved_failures",  # failures
    "session_stats",    # stats
    "handoff_note",     # handoff
)

_ENVELOPE_KEYS = {"_producers_ok", "_producers_failed", "_empty", "_ms", "schema_version"}


def _section_has_content(value) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, dict)) and len(value) == 0:
        return False
    return True


def merge_capsule(results: dict, failed: list, elapsed_ms: int) -> dict:
    """Merge per-producer section dicts into one capsule with an envelope.

    results: {producer_name: section_dict_or_None}
    failed:  producer names that errored/timed-out/returned-malformed.
    A producer is "ok" only if it returned at least one non-empty section.
    """
    capsule: dict = {"schema_version": CAPSULE_SCHEMA_VERSION}
    ok: list = []
    for name, section in results.items():
        if name in failed:
            continue
        if not section:
            continue
        contributed = False
        for key, value in section.items():
            if key not in SECTION_KEYS:
                continue
            if _section_has_content(value):
                capsule[key] = value
                contributed = True
        if contributed:
            ok.append(name)

    has_content = any(k in capsule for k in SECTION_KEYS)
    capsule["_producers_ok"] = ok
    capsule["_producers_failed"] = list(failed)
    capsule["_empty"] = not has_content
    capsule["_ms"] = int(elapsed_ms)
    return capsule


def build_envelope(capsule: dict) -> dict:
    """Extract just the envelope fields (for the sentinel)."""
    return {k: capsule.get(k) for k in _ENVELOPE_KEYS}


def render_systemmessage(capsule: dict) -> str | None:
    """Render the capsule to a single injected systemMessage. None if empty."""
    if capsule.get("_empty"):
        return None
    lines = ["[PreCompact capsule]"]
    if capsule.get("open_tasks"):
        lines.append(capsule["open_tasks"])
    if capsule.get("active_plan"):
        lines.append(f"Active plan: {capsule['active_plan']}")
    if capsule.get("git_state"):
        gl = ", ".join(
            f"{g.get('repo', '?')}(+{g.get('dirty', 0)}d/{g.get('unpushed', 0)}u)"
            for g in capsule["git_state"]
        )
        lines.append(f"Git: {gl}")
    if capsule.get("unresolved_failures"):
        lines.append("Unresolved command failures:")
        for f in capsule["unresolved_failures"][:10]:
            lines.append(f"  - {f}")
    if capsule.get("session_stats"):
        lines.append(f"Session stats: {capsule['session_stats']}")
    if capsule.get("handoff_note"):
        lines.append("Handoff note (agent-authored):")
        lines.append(capsule["handoff_note"])
    if len(lines) == 1:
        return None
    return "\n".join(lines)


# --- session-keyed capsule store -------------------------------------------
DEFAULT_CAPSULE_DIR = _capsule_dir()


def capsule_path(session_id: str, base_dir: str = DEFAULT_CAPSULE_DIR) -> str:
    return _os.path.join(base_dir, _safe_name(session_id) + ".json")


def write_capsule(session_id: str, capsule: dict, *, base_dir: str = DEFAULT_CAPSULE_DIR) -> None:
    try:
        _os.makedirs(base_dir, exist_ok=True)
        path = capsule_path(session_id, base_dir)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(_json.dumps(capsule))
        _os.replace(tmp, path)
    except OSError:
        pass


def read_capsule(session_id: str, *, base_dir: str = DEFAULT_CAPSULE_DIR) -> dict | None:
    try:
        path = capsule_path(session_id, base_dir)
        if not _os.path.exists(path):
            return None
        with open(path) as f:
            return _json.load(f)
    except (OSError, _json.JSONDecodeError):
        return None
