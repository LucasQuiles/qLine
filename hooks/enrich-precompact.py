#!/usr/bin/env python3
"""PreCompact hook: inject session context summary before compaction.

When Claude auto-compacts (context full), critical context gets lost.
This hook aggregates what happened in the session from the action ledger
and injects it as additionalContext so compaction preserves what matters.

NO Brick GPU call needed — pure local aggregation from action ledger + metrics.
This is the bridge between "we capture data" and "data helps the agent."

Matchers: manual, auto (fires on both /compact and auto-compact)
Skips: none — always inject when we have data
"""
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
from hook_utils import read_hook_input, allow_with_context, run_fail_open

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_HOOK_NAME = "enrich-precompact"
_EVENT_NAME = "PreCompact"
_ACTION_LEDGER = Path(os.path.expanduser("~/.local/share/brick-lab/action-ledger.jsonl"))
_METRICS_LOG = Path("/tmp/brick-lab/enrich-metrics.jsonl")
_OPS_DB = Path(os.path.expanduser("~/.local/share/brick-lab/brick-ops.db"))
_DIGEST_DIR = Path(os.path.expanduser("~/.local/share/brick-lab/digests"))
_MAX_CONTEXT_TOKENS = 600  # hard cap on injected context
_ACTION_TOKEN_CAP = 300 * 4  # chars (~300 tokens) for action summary
_DECISIONS_TOKEN_CAP = 100 * 4  # chars (~100 tokens) for decisions
_DIGESTS_TOKEN_CAP = 100 * 4  # chars (~100 tokens) for digest summaries


def _read_session_actions(session_id: str) -> list[dict]:
    """Read all actions for this session from the action ledger."""
    actions = []
    if not _ACTION_LEDGER.exists():
        return actions
    try:
        for line in _ACTION_LEDGER.read_text().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("session_id") == session_id:
                actions.append(entry)
    except (json.JSONDecodeError, OSError):
        pass
    return actions


def _read_session_enrichments(session_id: str) -> list[dict]:
    """Read enrichment findings for this session from metrics."""
    findings = []
    if not _METRICS_LOG.exists():
        return findings
    try:
        for line in _METRICS_LOG.read_text().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if (entry.get("session_id") == session_id
                    and entry.get("action") == "enriched"
                    and entry.get("quality") == "useful"):
                findings.append(entry)
    except (json.JSONDecodeError, OSError):
        pass
    return findings


def _read_recent_decisions(limit: int = 3) -> list[tuple[str, str, str]]:
    """Read recent decisions with outcomes from ops DB. Fail-open."""
    if not _OPS_DB.exists():
        return []
    try:
        conn = sqlite3.connect(str(_OPS_DB), timeout=2)
        cur = conn.execute(
            "SELECT topic, decision_text, outcome FROM decisions "
            "WHERE outcome != '' AND outcome != 'untested' "
            "ORDER BY rowid DESC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def _read_recent_digests(limit: int = 2) -> list[str]:
    """Read summary excerpts from most recent digest files. Fail-open."""
    if not _DIGEST_DIR.exists():
        return []
    try:
        files = sorted(_DIGEST_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        summaries = []
        for f in files[:limit]:
            data = json.loads(f.read_text())
            summary = data.get("summary", "")
            if summary:
                words = summary.split()[:50]
                summaries.append(" ".join(words))
        return summaries
    except Exception:
        return []


def _build_compaction_brief(session_id: str) -> str:
    """Build a concise session brief for compaction preservation.

    Includes: what was done, key files, findings, and what's unresolved.
    Hard-capped at ~600 tokens to avoid bloating the compacted context.
    """
    actions = _read_session_actions(session_id)
    findings = _read_session_enrichments(session_id)

    if not actions:
        return ""

    # Tool usage summary
    tool_counts = Counter(a.get("tool", "?") for a in actions)
    tool_summary = ", ".join(f"{t}:{c}" for t, c in tool_counts.most_common())

    # Files touched (unique, most frequent first)
    file_counts = Counter(
        a.get("file_path", "") for a in actions if a.get("file_path")
    )
    top_files = [f for f, _ in file_counts.most_common(8)]

    # Repos
    repos = set()
    for fp in top_files:
        parts = fp.split("/")
        for i, p in enumerate(parts):
            if p == "LAB" and i + 1 < len(parts):
                repos.add(parts[i + 1])
                break

    # Failed commands
    failed_cmds = [
        a.get("command", "")[:80]
        for a in actions
        if a.get("tool") == "Bash" and a.get("exit_code") and a["exit_code"] != 0
    ]

    # Brick findings
    finding_briefs = [
        f.get("findings_preview", "")[:100]
        for f in findings[:5]  # cap at 5
    ]

    # Build the brief
    parts = []
    parts.append(f"Session activity: {len(actions)} actions ({tool_summary})")

    if repos:
        parts.append(f"Repos: {', '.join(sorted(repos))}")

    if top_files:
        file_list = "\n".join(f"  - {f.split('/')[-1]}" for f in top_files[:6])
        parts.append(f"Key files:\n{file_list}")

    if failed_cmds:
        parts.append(f"Failed commands ({len(failed_cmds)}):")
        for cmd in failed_cmds[:3]:
            parts.append(f"  - {cmd}")

    if finding_briefs:
        parts.append(f"Brick findings ({len(finding_briefs)}):")
        for fb in finding_briefs:
            parts.append(f"  - {fb}")

    action_brief = "\n".join(parts)
    if len(action_brief) > _ACTION_TOKEN_CAP:
        action_brief = action_brief[:_ACTION_TOKEN_CAP] + "\n[truncated]"

    sections = [action_brief]

    # Key decisions with outcomes
    decisions = _read_recent_decisions()
    if decisions:
        dec_lines = ["Key decisions:"]
        for topic, decision, outcome in decisions:
            dec_lines.append(f"  - {topic} → {decision} (outcome: {outcome})")
        dec_section = "\n".join(dec_lines)
        if len(dec_section) > _DECISIONS_TOKEN_CAP:
            dec_section = dec_section[:_DECISIONS_TOKEN_CAP] + "\n[truncated]"
        sections.append(dec_section)

    # Recent digest summaries
    digests = _read_recent_digests()
    if digests:
        dig_lines = ["Recent sessions:"]
        for s in digests:
            dig_lines.append(f"  - {s}")
        dig_section = "\n".join(dig_lines)
        if len(dig_section) > _DIGESTS_TOKEN_CAP:
            dig_section = dig_section[:_DIGESTS_TOKEN_CAP] + "\n[truncated]"
        sections.append(dig_section)

    brief = "\n".join(sections)

    # Final safety cap
    if len(brief) > _MAX_CONTEXT_TOKENS * 4:
        brief = brief[:_MAX_CONTEXT_TOKENS * 4] + "\n[truncated]"

    return brief


def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = input_data.get("session_id", "")
    if not session_id:
        sys.exit(0)

    trigger = input_data.get("trigger", "")  # manual or auto

    # Log to metrics
    try:
        from brick_metrics import log_enrichment
        log_enrichment("precompact", session_id, "compact", action="enriched", reason=trigger)
    except Exception:
        pass

    brief = _build_compaction_brief(session_id)
    if not brief:
        sys.exit(0)

    context = f"[Brick session context for compaction preservation]\n{brief}"
    allow_with_context(context, event=_EVENT_NAME)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
