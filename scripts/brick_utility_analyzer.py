#!/usr/bin/env python3
"""Brick Utility Analyzer — verifiable metrics for enrichment value.

Computes three independent metrics from existing JSONL data:
A) Context Protection: re-read reduction on enriched vs unenriched large files
B) Code Quality Gate: follow-up edit rate on enriched vs unenriched writes
C) Session Continuity: error rate in enriched vs unenriched sessions

Each metric is independently falsifiable — no bundled "overall score."
"""
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

LEDGER_FILE = Path.home() / ".local/share/brick-lab/action-ledger.jsonl"
ENRICH_FILE = Path("/tmp/brick-lab/enrich-metrics.jsonl")
LATEST_FILE = Path("/tmp/brick-lab/utility-latest.json")
JSONL_FILE = Path("/tmp/brick-lab/utility-metrics.jsonl")

QUALITY_GATE_WINDOW_S = 120.0


def load_jsonl(path: Path) -> list[dict[str, Any]]:
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


def parse_ts(ts_str: str) -> float:
    try:
        return datetime.fromisoformat(ts_str).timestamp()
    except (ValueError, TypeError):
        return 0.0


def compute_context_protection(
    ledger_path: Path, metrics_path: Path,
) -> dict[str, Any]:
    """Metric A: average re-reads per file for enriched vs unenriched large-file reads.

    Uses read_count from action ledger to find max reads per (session, file).
    Compares files that were enriched by Read hook vs files that were skipped
    (due to circuit breaker or other reasons) on large files (>200 lines).
    """
    ledger = load_jsonl(ledger_path)
    metrics = load_jsonl(metrics_path)

    enriched_files: set[tuple[str, str]] = set()
    skipped_large_files: set[tuple[str, str]] = set()

    for m in metrics:
        if m.get("hook") != "read":
            continue
        sid = m.get("session_id", "")
        fp = m.get("file_path", "")
        if not sid or not fp:
            continue
        lines = m.get("lines_changed", 0)
        if lines < 200:
            continue
        if m.get("action") == "enriched":
            enriched_files.add((sid, fp))
        elif m.get("action") == "skipped" and m.get("reason") in ("circuit_breaker", "circuit_open"):
            skipped_large_files.add((sid, fp))

    max_reads: dict[tuple[str, str], int] = defaultdict(int)
    for entry in ledger:
        if entry.get("tool") != "Read":
            continue
        key = (entry.get("session_id", ""), entry.get("file_path", ""))
        rc = entry.get("read_count", 1)
        if rc > max_reads[key]:
            max_reads[key] = rc

    enriched_counts = [max_reads.get(k, 1) for k in enriched_files if k in max_reads]
    unenriched_counts = [max_reads.get(k, 1) for k in skipped_large_files if k in max_reads]

    return {
        "enriched_avg_reads": round(sum(enriched_counts) / len(enriched_counts), 2) if enriched_counts else 0.0,
        "unenriched_avg_reads": round(sum(unenriched_counts) / len(unenriched_counts), 2) if unenriched_counts else 0.0,
        "enriched_file_count": len(enriched_counts),
        "unenriched_file_count": len(unenriched_counts),
        "delta": round(
            (sum(unenriched_counts) / len(unenriched_counts) if unenriched_counts else 0.0)
            - (sum(enriched_counts) / len(enriched_counts) if enriched_counts else 0.0),
            2,
        ),
    }


def compute_quality_gate(
    ledger_path: Path, metrics_path: Path,
) -> dict[str, Any]:
    """Metric B: follow-up edit rate on enriched vs unenriched writes."""
    ledger = load_jsonl(ledger_path)
    metrics = load_jsonl(metrics_path)

    sessions: dict[str, list[dict]] = defaultdict(list)
    for entry in ledger:
        sid = entry.get("session_id", "")
        if sid:
            sessions[sid].append(entry)
    for actions in sessions.values():
        actions.sort(key=lambda a: parse_ts(a.get("ts", "")))

    enriched_writes: list[dict] = []
    skipped_writes: list[dict] = []
    for m in metrics:
        if m.get("hook") != "write":
            continue
        if m.get("action") == "enriched" and m.get("findings_preview"):
            enriched_writes.append(m)
        elif m.get("action") == "skipped" and m.get("reason") in ("circuit_open", "circuit_breaker"):
            skipped_writes.append(m)

    def has_followup(event: dict, session_actions: list[dict]) -> bool:
        ev_ts = parse_ts(event.get("ts", ""))
        ev_file = event.get("file_path", "")
        if not ev_ts or not ev_file:
            return False
        for act in session_actions:
            act_ts = parse_ts(act.get("ts", ""))
            if act_ts <= ev_ts:
                continue
            delta = act_ts - ev_ts
            if delta > QUALITY_GATE_WINDOW_S:
                break
            if act.get("file_path") == ev_file and act.get("tool") in ("Edit", "Write"):
                return True
        return False

    enriched_followups = sum(
        1 for w in enriched_writes
        if has_followup(w, sessions.get(w.get("session_id", ""), []))
    )
    unenriched_followups = sum(
        1 for w in skipped_writes
        if has_followup(w, sessions.get(w.get("session_id", ""), []))
    )

    return {
        "enriched_followup_rate": round(enriched_followups / len(enriched_writes), 4) if enriched_writes else 0.0,
        "unenriched_followup_rate": round(unenriched_followups / len(skipped_writes), 4) if skipped_writes else 0.0,
        "enriched_write_count": len(enriched_writes),
        "unenriched_write_count": len(skipped_writes),
        "enriched_followups": enriched_followups,
        "unenriched_followups": unenriched_followups,
    }


def compute_session_continuity(
    ledger_path: Path, metrics_path: Path,
) -> dict[str, Any]:
    """Metric C: Bash error rate in sessions with vs without SessionStart enrichment."""
    ledger = load_jsonl(ledger_path)
    metrics = load_jsonl(metrics_path)

    enriched_sessions: set[str] = set()
    for m in metrics:
        if m.get("hook") == "session_start" and m.get("action") == "enriched":
            enriched_sessions.add(m.get("session_id", ""))

    session_bash: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "errors": 0})
    for entry in ledger:
        if entry.get("tool") != "Bash":
            continue
        sid = entry.get("session_id", "")
        if not sid:
            continue
        session_bash[sid]["total"] += 1
        if entry.get("exit_code") is not None and entry["exit_code"] != 0:
            session_bash[sid]["errors"] += 1

    enriched_totals = 0
    enriched_errors = 0
    unenriched_totals = 0
    unenriched_errors = 0
    enriched_count = 0
    unenriched_count = 0

    for sid, counts in session_bash.items():
        if counts["total"] == 0:
            continue
        if sid in enriched_sessions:
            enriched_totals += counts["total"]
            enriched_errors += counts["errors"]
            enriched_count += 1
        else:
            unenriched_totals += counts["total"]
            unenriched_errors += counts["errors"]
            unenriched_count += 1

    return {
        "enriched_error_rate": round(enriched_errors / enriched_totals, 4) if enriched_totals else 0.0,
        "unenriched_error_rate": round(unenriched_errors / unenriched_totals, 4) if unenriched_totals else 0.0,
        "enriched_session_count": enriched_count,
        "unenriched_session_count": unenriched_count,
        "enriched_bash_total": enriched_totals,
        "unenriched_bash_total": unenriched_totals,
    }


def main() -> None:
    from datetime import timezone

    now = datetime.now(timezone.utc)

    a = compute_context_protection(LEDGER_FILE, ENRICH_FILE)
    b = compute_quality_gate(LEDGER_FILE, ENRICH_FILE)
    c = compute_session_continuity(LEDGER_FILE, ENRICH_FILE)

    report = {
        "ts": now.isoformat(),
        "context_protection": a,
        "quality_gate": b,
        "session_continuity": c,
    }

    LATEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        LATEST_FILE.write_text(json.dumps(report, indent=2) + "\n")
    except OSError:
        pass
    try:
        with open(JSONL_FILE, "a") as f:
            f.write(json.dumps(report) + "\n")
    except OSError:
        pass

    print("=" * 60)
    print("BRICK UTILITY REPORT")
    print("=" * 60)
    print()
    print(f"A) Context Protection (re-reads per large file):")
    print(f"   Enriched: {a['enriched_avg_reads']:.1f} avg reads ({a['enriched_file_count']} files)")
    print(f"   Unenriched: {a['unenriched_avg_reads']:.1f} avg reads ({a['unenriched_file_count']} files)")
    print(f"   Delta: {a['delta']:+.1f} reads {'(BETTER)' if a['delta'] > 0 else '(WORSE)' if a['delta'] < 0 else '(NEUTRAL)'}")
    print()
    print(f"B) Code Quality Gate (follow-up edit rate):")
    print(f"   Enriched: {b['enriched_followup_rate']:.1%} ({b['enriched_followups']}/{b['enriched_write_count']})")
    print(f"   Unenriched: {b['unenriched_followup_rate']:.1%} ({b['unenriched_followups']}/{b['unenriched_write_count']})")
    print()
    print(f"C) Session Continuity (bash error rate):")
    print(f"   Enriched: {c['enriched_error_rate']:.1%} ({c['enriched_session_count']} sessions, {c['enriched_bash_total']} cmds)")
    print(f"   Unenriched: {c['unenriched_error_rate']:.1%} ({c['unenriched_session_count']} sessions, {c['unenriched_bash_total']} cmds)")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
