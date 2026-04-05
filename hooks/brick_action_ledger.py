"""Layer 0: Action Ledger — records every tool action for decision tree tracing.

Durable append-only JSONL at ~/.local/share/brick-lab/action-ledger.jsonl.
Every Read, Write, Edit, MultiEdit, Bash, Grep, Glob action is logged
with a stable action_id and optional parent linkage.

This is NOT enrichment — no Brick calls. Pure observability for:
- Decision tree tracing: Read X → Edit Y → test fail → decision Z
- Artifact history: what changed, when, in which session
- Coverage analysis: what files are touched most, by whom

Schema v1:
{
  "v": 1,
  "action_id": "uuid-short",      # stable ID for this action
  "ts": "ISO-8601",
  "session_id": "string",
  "tool": "Read|Write|Edit|...",
  "file_path": "string",
  "lines": int,                    # lines read/written/changed
  "cwd": "string",
  "exit_code": int|null,           # for Bash
  "command": "string",             # for Bash
  "enriched": bool,                # whether Brick enriched this action
}
"""
import json
import os
import time
import uuid
from pathlib import Path

LEDGER_PATH = Path(
    os.environ.get(
        "BRICK_ACTION_LEDGER",
        os.path.expanduser("~/.local/share/brick-lab/action-ledger.jsonl"),
    )
)


def generate_action_id() -> str:
    """Short stable UUID for action linkage."""
    return str(uuid.uuid4())[:12]


def log_action(
    session_id: str,
    tool: str,
    file_path: str = "",
    lines: int = 0,
    cwd: str = "",
    exit_code: int | None = None,
    command: str = "",
    action_id: str = "",
    enriched: bool = False,
) -> str:
    """Log a tool action. Returns the action_id for downstream linkage. Never raises."""
    if not action_id:
        action_id = generate_action_id()

    try:
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)

        entry = {
            "v": 1,
            "action_id": action_id,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "session_id": session_id,
            "tool": tool,
            "file_path": file_path,
            "lines": lines,
            "cwd": cwd,
            "enriched": enriched,
        }

        # Only include optional fields when present
        if exit_code is not None:
            entry["exit_code"] = exit_code
        if command:
            entry["command"] = command[:200]  # cap command length

        with open(LEDGER_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Never fail a hook for ledger logging

    return action_id
