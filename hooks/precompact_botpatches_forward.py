#!/usr/bin/env python3
# hooks/precompact_botpatches_forward.py
"""Relay PreCompact producer-rot diagnostics to BOT PATCHES.

Reads new rot records from the fault ledger past a persisted byte offset and
posts a summary via the WhatSoup create_agent_job mechanism (report_chat =
BOT PATCHES). Idempotent via the offset file. Run by cron/operator.

NOTE: the actual create_agent_job call is performed by the operator/agent layer
that has MCP access; this module isolates the *selection* logic (unit-tested)
from delivery. `main()` prints the payload to stdout for the caller to relay.
"""
from __future__ import annotations

import json
import os
import sys

FAULT_LEDGER = os.path.join(os.path.expanduser("~"), ".claude", "logs",
                            "lifecycle-hook-faults.jsonl")
OFFSET_FILE = os.path.join(os.path.expanduser("~"), ".claude", "logs",
                           "precompact-rot-forward.offset")
BOT_PATCHES_CHAT = "120363428426970843@g.us"
_ROT_CLASSES = {"precompact_producer_rot", "precompact_capsule_empty"}


def select_new_rot_records(ledger_path: str, offset: int) -> tuple[list[dict], int]:
    """Return (new_rot_records, new_offset) for records past `offset`."""
    if not os.path.exists(ledger_path):
        return [], offset
    size = os.path.getsize(ledger_path)
    if offset > size:  # ledger rotated/truncated
        offset = 0
    out: list[dict] = []
    with open(ledger_path, errors="replace") as f:
        f.seek(offset)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(rec, dict) and rec.get("reason_class") in _ROT_CLASSES:
                out.append(rec)
    return out, size


def _read_offset() -> int:
    try:
        with open(OFFSET_FILE) as f:
            return int(f.read().strip() or "0")
    except (OSError, ValueError):
        return 0


def _write_offset(offset: int) -> None:
    try:
        os.makedirs(os.path.dirname(OFFSET_FILE), exist_ok=True)
        with open(OFFSET_FILE, "w") as f:
            f.write(str(offset))
    except OSError:
        pass


def main() -> int:
    new, offset = select_new_rot_records(FAULT_LEDGER, _read_offset())
    if not new:
        return 0
    summary = "🧱 PreCompact producer rot detected:\n" + "\n".join(
        f"  - {r.get('reason_class')}: {r.get('message', '')}" for r in new[:20]
    )
    payload = {"report_chat": BOT_PATCHES_CHAT, "summary": summary, "count": len(new)}
    sys.stdout.write(json.dumps(payload))
    _write_offset(offset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
