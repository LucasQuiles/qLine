# hooks/precompact_config.py
"""Single config surface for the PreCompact orchestrator (portable tool).

Every host- or environment-specific seam resolves HERE: storage directories,
the source action-ledger, the optional escalation channel, and tunables. Each
has a documented environment override and a sterile default. No host identifier
(WhatsApp JID, machine-specific data path) is baked into any other module — a
deployer points the tool at their environment by setting env vars, nothing
else.

Resolution happens at call-time so deployers and tests can override via the
environment without reimporting. The seam modules bind their module-level
`DEFAULT_*` constants from these functions at import; hooks are short-lived
subprocesses, so import-time binding reads a stable per-process environment.

Env override reference (all optional):
    PRECOMPACT_CAPSULE_DIR        capsule store dir
    PRECOMPACT_HANDOFF_DIR        agent handoff-note dir
    PRECOMPACT_LEDGER_PATH        action-ledger JSONL the producers read
    PRECOMPACT_FAULT_LEDGER       lifecycle fault/rot ledger
    PRECOMPACT_ROT_OFFSET_FILE    byte-offset cursor for rot forwarding
    PRECOMPACT_BOTPATCHES_CHAT    escalation channel id (empty => disabled)
    PRECOMPACT_PRODUCER_DEADLINE_S  per-producer subprocess deadline (float s)
    PRECOMPACT_MAX_REPOS          max git repos reported
    PRECOMPACT_MAX_FAILURES       max unresolved failures reported
"""
from __future__ import annotations

import os


def _home(*parts: str) -> str:
    return os.path.join(os.path.expanduser("~"), *parts)


def _env_str(var: str, default: str) -> str:
    """Return a non-empty env value, else the default."""
    val = os.environ.get(var)
    return val if val else default


def _env_int(var: str, default: int) -> int:
    try:
        return int(os.environ.get(var) or default)
    except (TypeError, ValueError):
        return default


def _env_float(var: str, default: float) -> float:
    try:
        return float(os.environ.get(var) or default)
    except (TypeError, ValueError):
        return default


# --- storage directories ----------------------------------------------------
# capsule + handoff are session-keyed siblings; both go under ~/.claude.

def capsule_dir() -> str:
    return _env_str("PRECOMPACT_CAPSULE_DIR", _home(".claude", "precompact-capsules"))


def handoff_dir() -> str:
    return _env_str("PRECOMPACT_HANDOFF_DIR", _home(".claude", "precompact-handoff"))


# --- source data: the action-ledger the producers read ----------------------

def ledger_path() -> str:
    return _env_str(
        "PRECOMPACT_LEDGER_PATH",
        _home(".local", "share", "brick-lab", "action-ledger.jsonl"),
    )


# --- fault-rot escalation (optional; disabled unless a channel is set) -------

def fault_ledger_path() -> str:
    return _env_str("PRECOMPACT_FAULT_LEDGER",
                    _home(".claude", "logs", "lifecycle-hook-faults.jsonl"))


def rot_offset_file() -> str:
    return _env_str("PRECOMPACT_ROT_OFFSET_FILE",
                    _home(".claude", "logs", "precompact-rot-forward.offset"))


def botpatches_chat() -> str:
    """Escalation channel id. Empty => forwarding disabled (sterile default).

    A portable tool must NOT ship a specific host's chat/group identifier.
    Deployers opt in by exporting PRECOMPACT_BOTPATCHES_CHAT.
    """
    return os.environ.get("PRECOMPACT_BOTPATCHES_CHAT", "").strip()


# --- tunables ---------------------------------------------------------------

def per_producer_deadline_s() -> float:
    return _env_float("PRECOMPACT_PRODUCER_DEADLINE_S", 3.0)


def max_repos() -> int:
    return _env_int("PRECOMPACT_MAX_REPOS", 5)


def max_failures() -> int:
    return _env_int("PRECOMPACT_MAX_FAILURES", 10)
