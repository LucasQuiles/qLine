# hooks/precompact_sentinel_lib.py
"""Testable core for the SessionStart capsule sentinel.

EXPECTED_PRODUCERS lists producers that should normally appear. 'failures' and
'unresolved' sections are legitimately often empty, so only structural failures
(_producers_failed) and a fully-empty capsule are alertable — not a producer
that simply had nothing to contribute this session.
"""
from __future__ import annotations

# Producers whose *structural failure* (not merely empty output) signals rot.
EXPECTED_PRODUCERS = ("preserve", "git", "stats")


def evaluate_capsule(capsule) -> list[dict]:
    """Return a list of alert dicts (possibly empty). Pure; never raises."""
    if not capsule:
        return []
    alerts: list[dict] = []
    failed = list(capsule.get("_producers_failed") or [])
    if failed:
        alerts.append({
            "reason_class": "precompact_producer_rot",
            "message": f"PreCompact producers failed: {', '.join(failed)}",
            "context": {"failed": failed, "ok": capsule.get("_producers_ok", [])},
        })
    if capsule.get("_empty"):
        alerts.append({
            "reason_class": "precompact_capsule_empty",
            "message": "PreCompact capsule was empty (capture pipeline not capturing).",
            "context": {"ms": capsule.get("_ms")},
        })
    return alerts
