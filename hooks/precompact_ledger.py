# hooks/precompact_ledger.py
"""Bounded tail reader for the brick-lab action-ledger JSONL.

The ledger is append-only and can be tens of MB. A session's records cluster at
the end, so we read a bounded tail from EOF rather than the whole file. This is
the single shared reader for all producers (reuse-first; one place owns the
latency contract).
"""
from __future__ import annotations

import json
import os

DEFAULT_LEDGER_PATH = os.path.join(
    os.path.expanduser("~"), ".local", "share", "brick-lab", "action-ledger.jsonl"
)
DEFAULT_MAX_BYTES = 2 * 1024 * 1024  # 2 MB tail window


def _read_tail_lines(path: str, max_bytes: int) -> list[str]:
    """Return decoded lines from the last <=max_bytes of the file.

    Drops a possibly-partial first line (we seeked into the middle of a record).
    """
    size = os.path.getsize(path)
    start = max(0, size - max_bytes)
    with open(path, "rb") as f:
        f.seek(start)
        chunk = f.read()
    text = chunk.decode("utf-8", errors="replace")
    lines = text.split("\n")
    if start > 0 and lines:
        lines = lines[1:]  # discard partial leading record
    return lines


def read_session_actions(
    session_id: str,
    *,
    ledger_path: str = DEFAULT_LEDGER_PATH,
    max_bytes: int = DEFAULT_MAX_BYTES,
    deadline=None,
) -> list[dict]:
    """Return action records for session_id found within the bounded tail window.

    Never raises; returns [] on any error. Honors a hook_utils.Deadline if given.
    """
    try:
        if not os.path.exists(ledger_path):
            return []
        lines = _read_tail_lines(ledger_path, max_bytes)
    except OSError:
        return []

    out: list[dict] = []
    for line in lines:
        if deadline is not None and deadline.remaining() == 0:
            break
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(entry, dict) and entry.get("session_id") == session_id:
            out.append(entry)
    return out
