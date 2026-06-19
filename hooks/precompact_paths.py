# hooks/precompact_paths.py
"""Single canonical session-id -> path-safe filename sanitizer.

Capsule files and handoff notes are keyed by the SAME session_id in sibling
directories. If the sanitizer diverged between them, a session would write its
capsule under one name and its note under another — a silent read-miss. One
implementation, imported by both, prevents that.
"""
from __future__ import annotations


def safe_name(session_id: str) -> str:
    """Map an arbitrary session_id to one path-safe filename (no traversal)."""
    cleaned = "".join(
        c if ((c.isascii() and c.isalnum()) or c in {"_", "-"}) else "-"
        for c in str(session_id)
    )
    return (cleaned or "unknown")[:128]
