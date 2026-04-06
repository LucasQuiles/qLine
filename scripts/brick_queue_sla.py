#!/usr/bin/env python3
"""Brick queue SLA metrics (P8b).

Scans enrich-queue and digest-queue directories, computes health metrics
(pending age, processing time, dead-letter rate), checks Brick API health
and circuit breaker state, then writes results to JSONL + latest JSON.

Runs periodically via systemd timer.
"""
import json
import os
import ssl
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path("/tmp/brick-lab")
HEALTH_URL = "https://brick.tail64ad01.ts.net:8443/health"
CB_STATE_FILE = BASE_DIR / "circuit-breaker.json"
JSONL_FILE = BASE_DIR / "queue-sla.jsonl"
LATEST_FILE = BASE_DIR / "queue-sla-latest.json"
TIMEOUT_S = 8

ENRICH_STAGES = ("pending", "processing", "ready", "processed", "dead-letter")
DIGEST_STAGES = ("pending", "processing", "processed", "dead-letter")


def count_files(directory: Path) -> int:
    """Count regular files in a directory, ignoring missing dirs."""
    try:
        return sum(1 for f in directory.iterdir() if f.is_file())
    except (FileNotFoundError, PermissionError):
        return 0


def oldest_pending_age_s(directory: Path) -> float | None:
    """Seconds since the oldest file in the pending directory was created."""
    try:
        files = [f for f in directory.iterdir() if f.is_file()]
    except (FileNotFoundError, PermissionError):
        return None
    if not files:
        return 0.0
    now = time.time()
    oldest = min(f.stat().st_ctime for f in files)
    return round(now - oldest, 1)


def avg_processing_time_s(directory: Path) -> float | None:
    """Average time between ctime and mtime for processed files (sample up to 200)."""
    try:
        files = [f for f in directory.iterdir() if f.is_file()]
    except (FileNotFoundError, PermissionError):
        return None
    if not files:
        return 0.0
    # Sample to keep it fast
    sample = files[:200]
    deltas = []
    for f in sample:
        st = f.stat()
        delta = st.st_mtime - st.st_ctime
        if delta >= 0:
            deltas.append(delta)
    if not deltas:
        return 0.0
    return round(sum(deltas) / len(deltas), 2)


def dead_letter_rate(dead: int, processed: int) -> float:
    """Dead-letter count / (processed + dead-letter), or 0 if no data."""
    total = processed + dead
    if total == 0:
        return 0.0
    return round(dead / total, 4)


def scan_queue(base: Path, stages: tuple[str, ...]) -> dict[str, Any]:
    """Compute metrics for a single queue."""
    counts: dict[str, int] = {}
    for stage in stages:
        key = stage.replace("-", "_")
        counts[key] = count_files(base / stage)

    result: dict[str, Any] = dict(counts)
    result["oldest_pending_age_s"] = oldest_pending_age_s(base / "pending")
    result["avg_processing_time_s"] = avg_processing_time_s(base / "processed")
    result["dead_letter_rate"] = dead_letter_rate(
        counts.get("dead_letter", 0), counts.get("processed", 0)
    )
    return result


def read_circuit_breaker() -> dict[str, str]:
    """Read circuit breaker state from JSON file."""
    try:
        data = json.loads(CB_STATE_FILE.read_text())
        return {"state": data.get("state", "unknown")}
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return {"state": "unknown"}


def check_brick_health() -> bool:
    """Probe the Brick health endpoint. Returns True if healthy."""
    try:
        api_key = subprocess.run(
            ["secret-tool", "lookup", "service", "brick-api-key"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        return False

    if not api_key:
        return False

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(
        HEALTH_URL,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=ctx) as resp:
            return resp.status == 200
    except Exception:
        return False


def main() -> None:
    now = datetime.now(timezone.utc)

    enrich = scan_queue(BASE_DIR / "enrich-queue", ENRICH_STAGES)
    digest = scan_queue(BASE_DIR / "digest-queue", DIGEST_STAGES)
    cb = read_circuit_breaker()
    healthy = check_brick_health()

    entry: dict[str, Any] = {
        "ts": now.isoformat(),
        "enrich_queue": enrich,
        "digest_queue": digest,
        "circuit_breaker": cb,
        "brick_api_healthy": healthy,
    }

    # Append to JSONL
    try:
        with open(JSONL_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        print(f"brick_queue_sla: failed to write JSONL: {e}")

    # Overwrite latest snapshot
    try:
        LATEST_FILE.write_text(json.dumps(entry, indent=2) + "\n")
    except OSError as e:
        print(f"brick_queue_sla: failed to write latest: {e}")

    # Print summary to journal
    print(
        f"brick_queue_sla: enrich pending={enrich['pending']} processing={enrich['processing']} "
        f"ready={enrich.get('ready', 0)} dead={enrich['dead_letter']} "
        f"oldest_pending={enrich['oldest_pending_age_s']}s | "
        f"digest pending={digest['pending']} processing={digest['processing']} "
        f"dead={digest['dead_letter']} | "
        f"cb={cb['state']} api_healthy={healthy}"
    )


if __name__ == "__main__":
    main()
