#!/usr/bin/env python3
"""Brick dead-letter redrive (P8c).

Scans enrich-queue and digest-queue dead-letter directories.
Moves retriable items (503/timeout with retry_count < 5) back to pending/.
Leaves permanent failures (422/Unprocessable or exhausted retries) in place.
Logs actions to enrich-metrics.jsonl.

Runs periodically via systemd timer (every 10 minutes).
"""
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path("/tmp/brick-lab")
METRICS_FILE = BASE_DIR / "enrich-metrics.jsonl"

QUEUES = {
    "enrich": BASE_DIR / "enrich-queue",
    "digest": BASE_DIR / "digest-queue",
}

MAX_RETRIES = 5
RETRIABLE_PATTERNS = re.compile(r"503|timeout|timed out", re.IGNORECASE)
PERMANENT_PATTERNS = re.compile(r"422|Unprocessable", re.IGNORECASE)


def log_metric(entry: dict) -> None:
    entry.setdefault("ts", datetime.now(timezone.utc).isoformat())
    entry.setdefault("hook", "redrive")
    with METRICS_FILE.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def process_dead_letter(path: Path, queue_name: str) -> str:
    """Process a single dead-letter file. Returns action taken."""
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log_metric({
            "action": "skipped_unreadable",
            "queue": queue_name,
            "file": path.name,
            "error": str(exc),
        })
        return "skipped_unreadable"

    retry_count = data.get("retry_count", 0)
    last_error = data.get("last_error", "")

    # Permanent: content errors that won't resolve on retry
    if PERMANENT_PATTERNS.search(last_error):
        log_metric({
            "action": "skipped_permanent",
            "queue": queue_name,
            "file": path.name,
            "reason": "content_error",
            "last_error": last_error,
            "retry_count": retry_count,
        })
        return "skipped_permanent"

    # Exhausted: too many retries
    if retry_count >= MAX_RETRIES:
        log_metric({
            "action": "skipped_permanent",
            "queue": queue_name,
            "file": path.name,
            "reason": "max_retries_exhausted",
            "last_error": last_error,
            "retry_count": retry_count,
        })
        return "skipped_permanent"

    # Only redrive if the error looks transient
    if not RETRIABLE_PATTERNS.search(last_error):
        log_metric({
            "action": "skipped_permanent",
            "queue": queue_name,
            "file": path.name,
            "reason": "unknown_error_type",
            "last_error": last_error,
            "retry_count": retry_count,
        })
        return "skipped_permanent"

    # Retriable: increment retry_count and move to pending/
    data["retry_count"] = retry_count + 1
    data["redrived_at"] = datetime.now(timezone.utc).isoformat()

    pending_dir = path.parent.parent / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    dest = pending_dir / path.name

    try:
        dest.write_text(json.dumps(data, indent=2, default=str))
        path.unlink()
    except OSError as exc:
        log_metric({
            "action": "redrive_failed",
            "queue": queue_name,
            "file": path.name,
            "error": str(exc),
        })
        return "redrive_failed"

    log_metric({
        "action": "redrived",
        "queue": queue_name,
        "file": path.name,
        "retry_count": data["retry_count"],
        "last_error": last_error,
    })
    return "redrived"


def main() -> None:
    totals: dict[str, dict[str, int]] = {}

    for queue_name, queue_dir in QUEUES.items():
        dl_dir = queue_dir / "dead-letter"
        if not dl_dir.is_dir():
            totals[queue_name] = {"total": 0, "redrived": 0, "skipped": 0}
            continue

        files = sorted(dl_dir.glob("*.json"))
        redrived = 0
        skipped = 0

        for f in files:
            action = process_dead_letter(f, queue_name)
            if action == "redrived":
                redrived += 1
            else:
                skipped += 1

        totals[queue_name] = {
            "total": len(files),
            "redrived": redrived,
            "skipped": skipped,
        }

    parts = []
    total_permanent = 0
    for qn, counts in totals.items():
        parts.append(f"{counts['redrived']}/{counts['total']} {qn}")
        total_permanent += counts["skipped"]

    summary = f"Redrived {', '.join(parts)}, skipped {total_permanent} permanent"
    print(summary)


if __name__ == "__main__":
    main()
