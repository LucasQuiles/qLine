#!/usr/bin/env python3
"""Brick System Dashboard — aggregates all metric sources into one report.

Reads circuit-breaker state, queue SLA, enrichment metrics, causality links,
action ledger, brick-ops DB, Brick API health, systemd timers, and brick-run
metrics. Prints a formatted dashboard to stdout and writes JSON to
/tmp/brick-lab/dashboard-latest.json.

stdlib-only. Fails gracefully on any missing source.
"""

import json
import os
import sqlite3
import subprocess
import ssl
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Paths ──────────────────────────────────────────────────────────────────

TMP = Path("/tmp/brick-lab")
DATA = Path.home() / ".local" / "share" / "brick-lab"

CB_PATH = TMP / "circuit-breaker.json"
QUEUE_SLA_PATH = TMP / "queue-sla-latest.json"
ENRICH_METRICS_PATH = TMP / "enrich-metrics.jsonl"
IMPACT_PATH = TMP / "impact-latest.json"
CAUSALITY_PATH = TMP / "causality-links.jsonl"
METRICS_PATH = TMP / "metrics.jsonl"
LEDGER_PATH = DATA / "action-ledger.jsonl"
DB_PATH = DATA / "brick-ops.db"

BRICK_HEALTH_URL = "https://brick.tail64ad01.ts.net:8443/health"


# ── Helpers ────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _count_lines(path: Path) -> int:
    try:
        with open(path) as f:
            return sum(1 for _ in f)
    except (FileNotFoundError, OSError):
        return 0


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except (FileNotFoundError, OSError):
        pass
    return rows


def _fmt(n: int | float) -> str:
    """Format number with commas."""
    if isinstance(n, float):
        return f"{n:,.1f}"
    return f"{n:,}"


def _pct(part: int, total: int) -> str:
    if total == 0:
        return "0.0%"
    return f"{part / total * 100:.1f}%"


# ── Data collectors ────────────────────────────────────────────────────────

def collect_circuit_breaker() -> dict[str, Any]:
    data = _load_json(CB_PATH)
    if not data:
        return {"state": "unknown", "ok": False}
    state = data.get("state", "unknown")
    return {"state": state, "ok": state == "closed"}


def collect_brick_api() -> dict[str, Any]:
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(BRICK_HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
            return {"status": resp.status, "ok": resp.status == 200}
    except Exception as e:
        return {"status": str(e), "ok": False}


def collect_timers() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "list-timers", "brick-*", "--no-pager"],
            capture_output=True, text=True, timeout=5,
        )
        lines = result.stdout.strip().splitlines()
        # Count timer lines (skip header and footer)
        timer_lines = [
            l for l in lines
            if "brick-" in l and ".timer" in l
        ]
        active = len(timer_lines)
        # Parse total from footer like "6 timers listed."
        total = active
        for l in lines:
            if "timers listed" in l:
                parts = l.split()
                if parts and parts[0].isdigit():
                    total = int(parts[0])
        return {"active": active, "total": total, "ok": active == total and active > 0}
    except Exception:
        return {"active": 0, "total": 0, "ok": False}


def collect_enrichment() -> dict[str, Any]:
    rows = _load_jsonl(ENRICH_METRICS_PATH)
    total = len(rows)
    if total == 0:
        return {"total": 0}

    action_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    hook_counts: Counter[str] = Counter()
    total_latency = 0
    cache_hits = 0

    for r in rows:
        action = r.get("action", "unknown")
        action_counts[action] += 1
        if action == "skipped":
            reason_counts[r.get("reason", "unknown")] += 1
        hook_counts[r.get("hook", "unknown")] += 1
        total_latency += r.get("latency_ms", 0)
        if r.get("cache_hit") or r.get("cache") == "hit":
            cache_hits += 1

    enriched = action_counts.get("enriched", 0)
    skipped = action_counts.get("skipped", 0)
    failed = action_counts.get("failed", 0)
    spooled = action_counts.get("spool", 0) + action_counts.get("spooled", 0)
    degraded = action_counts.get("degraded", 0)

    # Top skip reasons
    top_reasons = reason_counts.most_common(5)

    return {
        "total": total,
        "enriched": enriched,
        "skipped": skipped,
        "failed": failed,
        "spooled": spooled,
        "degraded": degraded,
        "action_counts": dict(action_counts),
        "top_skip_reasons": top_reasons,
        "avg_latency_ms": total_latency / total if total else 0,
        "cache_hits": cache_hits,
    }


def collect_queues() -> dict[str, Any]:
    data = _load_json(QUEUE_SLA_PATH)
    if not data:
        return {}
    result: dict[str, Any] = {}
    for qname in ("enrich_queue", "digest_queue"):
        q = data.get(qname, {})
        if q:
            result[qname] = {
                "pending": q.get("pending", 0),
                "processing": q.get("processing", 0),
                "processed": q.get("processed", 0),
                "dead_letter": q.get("dead_letter", 0),
                "dead_letter_rate": q.get("dead_letter_rate", 0),
                "oldest_pending_age_s": q.get("oldest_pending_age_s", 0),
            }
    return result


def collect_causality() -> dict[str, Any]:
    count = _count_lines(CAUSALITY_PATH)
    return {"link_count": count}


def collect_ledger() -> dict[str, Any]:
    rows = _load_jsonl(LEDGER_PATH)
    total = len(rows)
    enriched = sum(1 for r in rows if r.get("enriched"))
    return {"total": total, "enriched": enriched}


def collect_decisions() -> dict[str, Any]:
    if not DB_PATH.exists():
        return {"total": 0, "with_outcomes": 0}
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.cursor()
        cur.execute("SELECT count(*), sum(CASE WHEN outcome != 'untested' THEN 1 ELSE 0 END) FROM decisions")
        row = cur.fetchone()
        conn.close()
        return {"total": row[0] or 0, "with_outcomes": row[1] or 0}
    except Exception:
        return {"total": 0, "with_outcomes": 0}


def collect_impact() -> dict[str, Any] | None:
    return _load_json(IMPACT_PATH)


def collect_brick_run() -> dict[str, Any]:
    rows = _load_jsonl(METRICS_PATH)
    brick_run = [r for r in rows if r.get("tool") == "brick_run"]
    preprocess = [r for r in rows if r.get("tool") == "brick_preprocess_output"]

    intercepted_run = sum(1 for r in brick_run if r.get("intercepted"))
    skipped_run = sum(1 for r in brick_run if not r.get("intercepted"))

    intercepted_pp = sum(
        1 for r in preprocess
        if r.get("truncated") or (r.get("compression_ratio") is not None and r.get("compression_ratio", 1.0) < 1.0)
    )

    total_run = len(brick_run)
    total_pp = len(preprocess)

    # Token savings from preprocessing
    token_savings = sum(
        r.get("input_tokens", 0) - r.get("output_tokens", 0)
        for r in preprocess
        if r.get("input_tokens") and r.get("output_tokens")
    )

    return {
        "brick_run_total": total_run,
        "brick_run_intercepted": intercepted_run,
        "brick_run_skipped": skipped_run,
        "preprocess_total": total_pp,
        "preprocess_intercepted": intercepted_pp,
        "token_savings": token_savings,
    }


# ── Formatter ──────────────────────────────────────────────────────────────

def format_dashboard(data: dict[str, Any]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M %Z").strip()
    lines: list[str] = []

    def section(title: str) -> None:
        lines.append("")
        lines.append(title)

    def row(label: str, value: str) -> None:
        lines.append(f"  {label:<21s}{value}")

    lines.append(f"\u2550\u2550\u2550 BRICK SYSTEM DASHBOARD \u2550\u2550\u2550  {now}")

    # ── HEALTH ──
    section("HEALTH")
    cb = data["circuit_breaker"]
    cb_state = cb["state"].upper()
    cb_icon = "\u2713" if cb["ok"] else "\u2717"
    row("Circuit Breaker:", f"{cb_state} {cb_icon}")

    api = data["brick_api"]
    if api["ok"]:
        row("Brick API:", f"{api['status']} OK \u2713")
    else:
        row("Brick API:", f"{api['status']} \u2717")

    timers = data["timers"]
    t_icon = "\u2713" if timers["ok"] else "\u2717"
    row("Timers:", f"{timers['active']}/{timers['total']} active {t_icon}")

    # ── ENRICHMENT PIPELINE ──
    section("ENRICHMENT PIPELINE")
    enr = data["enrichment"]
    total_e = enr.get("total", 0)
    enriched = enr.get("enriched", 0)
    spooled = enr.get("spooled", 0)
    skipped = enr.get("skipped", 0)
    failed = enr.get("failed", 0)
    degraded = enr.get("degraded", 0)

    row("Total events:", _fmt(total_e))
    row("Enriched:", f"{_fmt(enriched)} ({_pct(enriched, total_e)})")
    if spooled:
        row("Spooled:", _fmt(spooled))
    if skipped:
        # Build reason breakdown
        reasons = enr.get("top_skip_reasons", [])
        reason_parts = []
        for reason, count in reasons:
            reason_parts.append(f"{reason}: {_pct(count, skipped)}")
        reason_str = ", ".join(reason_parts) if reason_parts else ""
        skip_detail = f"{_fmt(skipped)} ({_pct(skipped, total_e)})"
        if reason_str:
            skip_detail += f"  [{reason_str}]"
        row("Skipped:", skip_detail)
    if failed:
        row("Failed:", _fmt(failed))
    if degraded:
        row("Degraded:", _fmt(degraded))

    br = data["brick_run"]
    token_savings = br.get("token_savings", 0)
    if token_savings:
        row("Token savings:", f"~{_fmt(token_savings)} est")

    # ── QUEUES ──
    section("QUEUES")
    queues = data["queues"]
    for qname, label in [("enrich_queue", "Enrich"), ("digest_queue", "Digest")]:
        q = queues.get(qname)
        if q:
            dl = q["dead_letter"]
            dl_rate = q["dead_letter_rate"]
            row(f"{label}:", (
                f"pending={q['pending']}, processing={q['processing']}, "
                f"processed={q['processed']}, DL={dl} ({dl_rate:.1%})"
            ))
        else:
            row(f"{label}:", "no data")

    # ── MEMORY LOOP ──
    section("MEMORY LOOP")
    causality = data["causality"]
    row("Causality links:", _fmt(causality["link_count"]))

    decisions = data["decisions"]
    row("Decisions:", f"{decisions['total']} ({decisions['with_outcomes']} with outcomes)")

    ledger = data["ledger"]
    led_total = ledger["total"]
    led_enriched = ledger["enriched"]
    if led_total > 0:
        row("Ledger:", f"{_pct(led_enriched, led_total)} enriched ({_fmt(led_enriched)}/{_fmt(led_total)})")
    else:
        row("Ledger:", "empty")

    # ── BEHAVIORAL IMPACT ──
    section("BEHAVIORAL IMPACT")
    impact = data.get("impact")
    if impact:
        # Display whatever keys are present
        for key, val in impact.items():
            if key != "ts":
                row(f"{key}:", str(val))
    else:
        row("Responsiveness:", "no data yet")

    # ── BRICK-RUN ──
    section("BRICK-RUN")
    br_total = br["brick_run_total"]
    br_intercepted = br["brick_run_intercepted"]
    br_skipped = br["brick_run_skipped"]
    pp_total = br["preprocess_total"]
    pp_intercepted = br["preprocess_intercepted"]

    total_all = br_total + pp_total
    intercepted_all = br_intercepted + pp_intercepted
    skipped_all = total_all - intercepted_all

    row("Intercepted:", _fmt(intercepted_all))
    row("Skipped:", _fmt(skipped_all))
    if total_all > 0:
        row("Intercept rate:", _pct(intercepted_all, total_all))
    else:
        row("Intercept rate:", "n/a (no events)")

    lines.append("")
    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    data: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "circuit_breaker": collect_circuit_breaker(),
        "brick_api": collect_brick_api(),
        "timers": collect_timers(),
        "enrichment": collect_enrichment(),
        "queues": collect_queues(),
        "causality": collect_causality(),
        "ledger": collect_ledger(),
        "decisions": collect_decisions(),
        "impact": collect_impact(),
        "brick_run": collect_brick_run(),
    }

    # Print formatted dashboard
    print(format_dashboard(data))

    # Write JSON snapshot
    TMP.mkdir(parents=True, exist_ok=True)
    out_path = TMP / "dashboard-latest.json"
    out_path.write_text(json.dumps(data, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
