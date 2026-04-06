#!/usr/bin/env python3
"""P7c: Brick Causality Linker — links decisions ↔ actions ↔ changelog entries.

Closes the causality loop by correlating:
  1. Decisions (from session digests) → Actions (same session_id)
  2. Actions (enriched) → Changelog entries (same session_id + file_path)

Writes:
  - decision_actions rows in brick-ops.db
  - Updates decisions.outcome based on adoption evidence
  - Appends causality-links.jsonl for observability

Designed as a periodic batch job (systemd timer, every 5 min).
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".local/share/brick-lab/brick-ops.db"
LINKS_DIR = Path("/tmp/brick-lab")
LINKS_PATH = LINKS_DIR / "causality-links.jsonl"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def ensure_dirs() -> None:
    LINKS_DIR.mkdir(parents=True, exist_ok=True)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def link_decisions_to_actions(conn: sqlite3.Connection) -> list[dict]:
    """For each decision, find actions in the same session and insert into decision_actions."""
    decisions = conn.execute(
        "SELECT decision_id, session_id, topic, decision_text FROM decisions"
    ).fetchall()

    links = []
    for dec in decisions:
        # Find actions in the same session
        actions = conn.execute(
            """SELECT action_id, tool, file_path, enriched
               FROM actions
               WHERE session_id = ?
               ORDER BY ts""",
            (dec["session_id"],),
        ).fetchall()

        for act in actions:
            # Check if link already exists
            existing = conn.execute(
                "SELECT 1 FROM decision_actions WHERE decision_id = ? AND action_id = ?",
                (dec["decision_id"], act["action_id"]),
            ).fetchone()

            if existing:
                continue

            conn.execute(
                """INSERT INTO decision_actions (decision_id, action_id, relation_type)
                   VALUES (?, ?, 'related')""",
                (dec["decision_id"], act["action_id"]),
            )

            links.append(
                {
                    "decision_id": dec["decision_id"],
                    "decision_topic": dec["topic"],
                    "action_id": act["action_id"],
                    "action_tool": act["tool"],
                    "action_file": act["file_path"],
                    "enriched": bool(act["enriched"]),
                }
            )

    return links


def link_actions_to_changelog(conn: sqlite3.Connection) -> list[dict]:
    """For enriched actions, find matching changelog entries (session_id + file_path)."""
    enriched_actions = conn.execute(
        """SELECT action_id, session_id, tool, file_path
           FROM actions
           WHERE enriched = 1 AND file_path != ''"""
    ).fetchall()

    links = []
    for act in enriched_actions:
        changelog_entries = conn.execute(
            """SELECT id, brick_summary, action_id AS cl_action_id
               FROM changelog
               WHERE session_id = ? AND file_path = ?""",
            (act["session_id"], act["file_path"]),
        ).fetchall()

        for cl in changelog_entries:
            # Update changelog.action_id if not already set
            if not cl["cl_action_id"]:
                conn.execute(
                    "UPDATE changelog SET action_id = ? WHERE id = ?",
                    (act["action_id"], cl["id"]),
                )

            links.append(
                {
                    "action_id": act["action_id"],
                    "action_session": act["session_id"],
                    "action_tool": act["tool"],
                    "action_file": act["file_path"],
                    "changelog_id": cl["id"],
                    "changelog_summary": cl["brick_summary"][:200] if cl["brick_summary"] else "",
                }
            )

    return links


def update_decision_adoption(conn: sqlite3.Connection) -> list[dict]:
    """Update decision outcome based on whether linked actions exist and were enriched."""
    decisions = conn.execute(
        "SELECT decision_id, session_id, topic, outcome FROM decisions"
    ).fetchall()

    updates = []
    for dec in decisions:
        action_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM decision_actions WHERE decision_id = ?",
            (dec["decision_id"],),
        ).fetchone()["cnt"]

        enriched_count = conn.execute(
            """SELECT COUNT(*) as cnt
               FROM decision_actions da
               JOIN actions a ON da.action_id = a.action_id
               WHERE da.decision_id = ? AND a.enriched = 1""",
            (dec["decision_id"],),
        ).fetchone()["cnt"]

        # Determine adoption: if there are enriched actions in the session,
        # the agent acted on the decision context
        adopted = enriched_count > 0
        new_outcome = "validated" if adopted else dec["outcome"]

        if new_outcome != dec["outcome"] and dec["outcome"] == "untested":
            conn.execute(
                "UPDATE decisions SET outcome = ? WHERE decision_id = ?",
                (new_outcome, dec["decision_id"]),
            )

        updates.append(
            {
                "decision_id": dec["decision_id"],
                "decision_topic": dec["topic"],
                "action_count": action_count,
                "enriched_count": enriched_count,
                "adopted": adopted,
                "outcome": new_outcome,
            }
        )

    return updates


def write_links_log(
    decision_action_links: list[dict],
    action_changelog_links: list[dict],
    adoption_updates: list[dict],
) -> int:
    """Append causality link entries to JSONL log. Returns count written."""
    ts = now_iso()
    count = 0

    with open(LINKS_PATH, "a") as f:
        for link in decision_action_links:
            entry = {
                "type": "decision_action",
                "linked_at": ts,
                **link,
            }
            f.write(json.dumps(entry) + "\n")
            count += 1

        for link in action_changelog_links:
            entry = {
                "type": "action_changelog",
                "linked_at": ts,
                **link,
            }
            f.write(json.dumps(entry) + "\n")
            count += 1

        for update in adoption_updates:
            if update["action_count"] > 0:  # Only log decisions with actions
                entry = {
                    "type": "adoption_update",
                    "linked_at": ts,
                    **update,
                }
                f.write(json.dumps(entry) + "\n")
                count += 1

    return count


def main() -> None:
    if not DB_PATH.exists():
        print(f"[causality-linker] DB not found: {DB_PATH}", file=sys.stderr)
        sys.exit(0)  # Graceful — not an error if system not bootstrapped yet

    ensure_dirs()

    try:
        conn = get_db()
    except sqlite3.Error as e:
        print(f"[causality-linker] DB error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        # Phase 1: Link decisions → actions (by session_id)
        da_links = link_decisions_to_actions(conn)

        # Phase 2: Link enriched actions → changelog (by session_id + file_path)
        ac_links = link_actions_to_changelog(conn)

        # Phase 3: Update adoption status on decisions
        adoption = update_decision_adoption(conn)

        conn.commit()

        # Phase 4: Write observability log
        count = write_links_log(da_links, ac_links, adoption)

        # Summary
        stats = {
            "ts": now_iso(),
            "decision_action_links_new": len(da_links),
            "action_changelog_links": len(ac_links),
            "adoption_updates": len([u for u in adoption if u["action_count"] > 0]),
            "total_log_entries": count,
        }
        print(f"[causality-linker] {json.dumps(stats)}")

    except sqlite3.Error as e:
        print(f"[causality-linker] SQL error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
