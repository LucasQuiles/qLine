"""Shared metrics logger for all Brick enrichment hooks.

Every hook call — whether it enriches, skips, or fails — gets logged.
Append-only JSONL file for analysis.
"""
import json
import os
import time
from pathlib import Path

METRICS_PATH = Path("/tmp/brick-lab/enrich-metrics.jsonl")


def log_enrichment(
    hook: str,
    session_id: str,
    tool_name: str,
    file_path: str = "",
    action: str = "enriched",  # enriched | skipped | failed | degraded | spool
    reason: str = "",
    latency_ms: int = 0,
    cache_hit: bool = False,
    findings_preview: str = "",
    lines_changed: int = 0,
    command_family: str = "",
) -> None:
    """Log a single enrichment event. Never raises."""
    try:
        METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "hook": hook,
            "session_id": session_id,
            "tool": tool_name,
            "file_path": file_path,
            "action": action,
            "reason": reason,
            "latency_ms": latency_ms,
            "cache_hit": cache_hit,
            "findings_preview": findings_preview[:200],
            "lines_changed": lines_changed,
            "command_family": command_family,
        }
        with open(METRICS_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Never fail the hook for metrics
