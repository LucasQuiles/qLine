#!/usr/bin/env python3
"""Brick behavioral impact tracker.

Measures whether agents change behavior in response to Brick enrichment
findings. For each enrichment event with findings, checks if the NEXT
action in the same session targets the same file (responsive) or not
(unresponsive). A responsive action within 30s suggests the agent acted
on the finding.

Runs periodically via systemd timer.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LEDGER_FILE = Path.home() / ".local/share/brick-lab/action-ledger.jsonl"
ENRICH_FILE = Path("/tmp/brick-lab/enrich-metrics.jsonl")
JSONL_FILE = Path("/tmp/brick-lab/impact-metrics.jsonl")
LATEST_FILE = Path("/tmp/brick-lab/impact-latest.json")
RESPONSE_WINDOW_S = 30.0
RESPONSIVE_TOOLS = {"Edit", "Write", "Bash"}


def parse_ts(ts_str: str) -> float:
    """Parse ISO timestamp to epoch seconds, tolerating offset formats."""
    try:
        dt = datetime.fromisoformat(ts_str)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL file, skipping malformed lines."""
    entries: list[dict[str, Any]] = []
    if not path.exists():
        return entries
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def build_session_actions(ledger: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group ledger actions by session_id, sorted by timestamp."""
    sessions: dict[str, list[dict[str, Any]]] = {}
    for entry in ledger:
        sid = entry.get("session_id", "")
        if not sid:
            continue
        sessions.setdefault(sid, []).append(entry)
    for actions in sessions.values():
        actions.sort(key=lambda a: parse_ts(a.get("ts", "")))
    return sessions


def classify_response(
    enrichment: dict[str, Any],
    next_action: dict[str, Any],
) -> tuple[bool, float]:
    """Classify whether next_action is responsive to the enrichment.

    Returns (is_responsive, delta_seconds).
    Responsive = same file + edit/write tool + within time window.
    """
    enrich_ts = parse_ts(enrichment.get("ts", ""))
    action_ts = parse_ts(next_action.get("ts", ""))
    delta = action_ts - enrich_ts

    if delta < 0 or delta > RESPONSE_WINDOW_S:
        return False, delta

    enrich_file = enrichment.get("file_path", "")
    action_file = next_action.get("file_path", "")
    action_tool = next_action.get("tool", "")

    if not enrich_file or not action_file:
        return False, delta

    # Same file and a write-oriented tool
    if action_file == enrich_file and action_tool in RESPONSIVE_TOOLS:
        return True, delta

    return False, delta


def main() -> None:
    now = datetime.now(timezone.utc)

    ledger = load_jsonl(LEDGER_FILE)
    enrich = load_jsonl(ENRICH_FILE)

    if not ledger or not enrich:
        print("brick_impact_tracker: no data available")
        return

    sessions = build_session_actions(ledger)

    # Filter to enrichment events with actual findings
    enrichments = [
        e for e in enrich
        if e.get("action") == "enriched" and e.get("findings_preview")
    ]

    total = 0
    responsive = 0
    response_times: list[float] = []

    for ev in enrichments:
        sid = ev.get("session_id", "")
        if sid not in sessions:
            continue

        ev_ts = parse_ts(ev.get("ts", ""))
        actions = sessions[sid]

        # Find the next action after this enrichment timestamp
        next_action = None
        for act in actions:
            act_ts = parse_ts(act.get("ts", ""))
            if act_ts > ev_ts:
                next_action = act
                break

        if next_action is None:
            total += 1
            continue

        total += 1
        is_resp, delta = classify_response(ev, next_action)
        if is_resp:
            responsive += 1
            response_times.append(delta)

    rate = (responsive / total) if total > 0 else 0.0
    avg_time = (sum(response_times) / len(response_times)) if response_times else 0.0

    entry: dict[str, Any] = {
        "ts": now.isoformat(),
        "total_enrichments": total,
        "responsive_actions": responsive,
        "responsiveness_rate": round(rate, 4),
        "avg_response_time_s": round(avg_time, 2),
        "sample_window_s": RESPONSE_WINDOW_S,
    }

    # Ensure output dir exists
    JSONL_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Append to JSONL
    try:
        with open(JSONL_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        print(f"brick_impact_tracker: failed to write JSONL: {e}")

    # Overwrite latest snapshot
    try:
        LATEST_FILE.write_text(json.dumps(entry, indent=2) + "\n")
    except OSError as e:
        print(f"brick_impact_tracker: failed to write latest: {e}")

    # Print summary to journal
    print(
        f"brick_impact_tracker: total={total} responsive={responsive} "
        f"rate={rate:.1%} avg_time={avg_time:.1f}s"
    )


if __name__ == "__main__":
    main()
