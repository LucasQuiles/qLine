#!/usr/bin/env python3
"""PostToolUse injection hook for Brick enrichment results.

Fires on action tools (Write, Edit, MultiEdit, Bash) — NOT on read-only tools.
Scans the ready/ spool directory for enrichments matching the current session,
injects them as additionalContext, and moves consumed files to processed/.
"""
import json
import os
import shutil
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hook_utils import read_hook_input, run_fail_open, allow_with_context

_HOOK_NAME = "enrich-inject"
_EVENT_NAME = "PostToolUse"
_SPOOL_ROOT = "/tmp/brick-lab/enrich-queue"
_ACTION_TOOLS = {"Write", "Edit", "MultiEdit", "Bash"}


def find_ready_enrichments(spool_root: str, session_id: str) -> list[dict]:
    """Scan ready/ dir for .result.json files matching session_id."""
    ready_dir = os.path.join(spool_root, "ready")
    if not os.path.isdir(ready_dir):
        return []

    results = []
    for fname in os.listdir(ready_dir):
        if not fname.endswith(".result.json"):
            continue
        fpath = os.path.join(ready_dir, fname)
        try:
            with open(fpath) as f:
                data = json.load(f)
            if data.get("session_id") == session_id:
                data["_path"] = fpath
                results.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return results


def format_injection(enrichments: list[dict]) -> str:
    """Format enrichment results for injection as additionalContext."""
    parts = []
    for e in enrichments:
        tool = e.get("tool", "unknown")
        findings = e.get("findings", e.get("summary", ""))
        parts.append(f"[Brick enrichment from prior {tool} call] {findings}")
    return "\n\n".join(parts)


def _move_to_processed(spool_root: str, enrichment: dict) -> None:
    """Move a consumed enrichment file to processed/."""
    src = enrichment.get("_path", "")
    if not src or not os.path.exists(src):
        return
    processed_dir = os.path.join(spool_root, "processed")
    os.makedirs(processed_dir, exist_ok=True)
    dst = os.path.join(processed_dir, os.path.basename(src))
    shutil.move(src, dst)


def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    if tool_name not in _ACTION_TOOLS:
        sys.exit(0)

    session_id = input_data.get("session_id", "")
    if not session_id:
        sys.exit(0)

    enrichments = find_ready_enrichments(_SPOOL_ROOT, session_id)
    if not enrichments:
        sys.exit(0)

    context = format_injection(enrichments)

    # Move consumed files to processed/
    for e in enrichments:
        _move_to_processed(_SPOOL_ROOT, e)

    allow_with_context(context, event=_EVENT_NAME)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
