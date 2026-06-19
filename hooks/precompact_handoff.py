#!/usr/bin/env python3
# hooks/precompact_handoff.py
"""Agent-authored handoff note: trusted, local-only, zero-leak.

The live agent records intent/blockers/next-action in its own words during the
session. At PreCompact the handoff producer reads the latest note. No note ->
no section (never fabricated). Content never leaves the machine, so no
sanitization and no 'unverified' label.

CLI (for the agent to record a note):
    python3 precompact_handoff.py write <session_id> "next: wire the tests"
    echo "long note" | python3 precompact_handoff.py write <session_id> -
"""
from __future__ import annotations

import os
import sys

MAX_NOTE_CHARS = 4000
DEFAULT_BASE_DIR = os.path.join(
    os.path.expanduser("~"), ".claude", "precompact-handoff"
)


def _safe_name(session_id: str) -> str:
    """Sanitize session_id to a single path-safe filename (no traversal)."""
    cleaned = "".join(
        c if ((c.isascii() and c.isalnum()) or c in {"_", "-"}) else "-"
        for c in str(session_id)
    )
    return (cleaned or "unknown")[:128]


def _note_path(session_id: str, base_dir: str) -> str:
    return os.path.join(base_dir, _safe_name(session_id) + ".md")


def write_note(session_id: str, text: str, *, base_dir: str = DEFAULT_BASE_DIR) -> None:
    """Overwrite the session's handoff note. Blank text clears it. Never raises."""
    try:
        text = (text or "").strip()[:MAX_NOTE_CHARS]
        os.makedirs(base_dir, exist_ok=True)
        path = _note_path(session_id, base_dir)
        if not text:
            if os.path.exists(path):
                os.remove(path)
            return
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(text)
        os.replace(tmp, path)  # atomic
    except OSError:
        pass


def read_note(session_id: str, *, base_dir: str = DEFAULT_BASE_DIR) -> str | None:
    """Return the session's handoff note, or None if absent/blank. Never raises."""
    try:
        path = _note_path(session_id, base_dir)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            text = f.read().strip()[:MAX_NOTE_CHARS]
        return text or None
    except OSError:
        return None


def _main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[0] == "write":
        session_id = argv[1]
        if argv[2] == "-":
            text = sys.stdin.read()
        else:
            text = " ".join(argv[2:])
        write_note(session_id, text)
        return 0
    sys.stderr.write("usage: precompact_handoff.py write <session_id> <text|->\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
