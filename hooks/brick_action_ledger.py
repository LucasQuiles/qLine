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
    """Random UUID fallback — prefer derive_action_id() for deterministic linking."""
    return str(uuid.uuid4())[:12]


def derive_action_id(input_data: dict) -> str:
    """Deterministic action_id from hook input payload.

    Both obs hooks and enrichment hooks receive the same stdin payload.
    This function produces the same ID from either, enabling linkage
    without timestamp matching or row scanning.

    Fields used (all stable across parallel hook invocations):
    - session_id
    - tool_name
    - tool_use_id (unique per tool call, set by Claude Code)
    - file_path or command (for disambiguation)
    """
    import hashlib

    session_id = input_data.get("session_id", "")
    tool_name = input_data.get("tool_name", "")
    tool_use_id = input_data.get("tool_use_id", "")

    # tool_use_id is the best key — it's unique per tool call
    if tool_use_id:
        raw = f"{session_id}:{tool_use_id}"
    else:
        # Fallback: use tool + target
        tool_input = input_data.get("tool_input", {})
        target = (
            tool_input.get("file_path", "")
            or tool_input.get("command", "")
            or ""
        )
        raw = f"{session_id}:{tool_name}:{target}"

    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def get_read_count(session_id: str, file_path: str) -> int:
    """Count how many times a file was read in a session. Never raises."""
    try:
        if not LEDGER_PATH.exists():
            return 0
        count = 0
        with open(LEDGER_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    entry.get("session_id") == session_id
                    and entry.get("tool") == "Read"
                    and entry.get("file_path") == file_path
                ):
                    count += 1
        return count
    except Exception:
        return 0


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

        # Track re-read count for Read tool
        if tool == "Read" and file_path:
            existing = get_read_count(session_id, file_path)
            entry["read_count"] = existing + 1

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


def mark_enriched(
    session_id: str,
    tool: str,
    trace_id: str = "",
    action_id: str = "",
) -> int:
    """Mark matching ledger entries as enriched=true. Returns count updated.

    When action_id is provided, matches the exact ledger entry (precise).
    Falls back to session_id + tool when action_id is not available.
    If trace_id is provided, it's stored for correlation.
    Never raises.
    """
    try:
        if not LEDGER_PATH.exists():
            return 0

        lines = LEDGER_PATH.read_text().splitlines()
        updated = 0
        new_lines = []
        for line in lines:
            if not line.strip():
                new_lines.append(line)
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                new_lines.append(line)
                continue

            if entry.get("enriched", False):
                new_lines.append(line)
                continue

            matched = False
            if action_id:
                # Precise match on action_id
                matched = entry.get("action_id") == action_id
            else:
                # Fallback: session_id + tool (imprecise, may match multiple)
                matched = (
                    entry.get("session_id") == session_id
                    and entry.get("tool") == tool
                )

            if matched:
                entry["enriched"] = True
                if trace_id:
                    entry["trace_id"] = trace_id
                new_lines.append(json.dumps(entry))
                updated += 1
            else:
                new_lines.append(line)

        if updated:
            LEDGER_PATH.write_text("\n".join(new_lines) + "\n")

        return updated
    except Exception:
        return 0
