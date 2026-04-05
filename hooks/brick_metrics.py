"""Shared metrics logger for all Brick enrichment hooks.

Every hook call — whether it enriches, skips, or fails — gets logged.
Append-only JSONL file for analysis.

Enhanced fields (BES Bot recommendations):
- quality: useful | generic | empty (auto-classified from findings)
- cache: hit | miss (from Brick response)
- tokens_original / tokens_summary (for Read gate savings)
- relevance_score (for SessionStart Pinecone query)
- spool_stage: pending | ready | injected (for async pipeline tracking)
"""
import json
import os
import re
import time
from pathlib import Path

METRICS_PATH = Path("/tmp/brick-lab/enrich-metrics.jsonl")

# Patterns that indicate generic/unhelpful findings
_GENERIC_PATTERNS = re.compile(
    r"no critical|no issues|no significant|no apparent|not detected|"
    r"code consists of simple|no breaking changes",
    re.IGNORECASE,
)


def classify_quality(findings: str) -> str:
    """Classify finding quality: useful, generic, or empty."""
    if not findings or not findings.strip():
        return "empty"
    if _GENERIC_PATTERNS.search(findings):
        return "generic"
    return "useful"


def log_enrichment(
    hook: str,
    session_id: str,
    tool_name: str,
    file_path: str = "",
    action: str = "enriched",  # enriched | skipped | failed | degraded | spool | injected
    reason: str = "",
    latency_ms: int = 0,
    cache_hit: bool = False,
    findings_preview: str = "",
    lines_changed: int = 0,
    command_family: str = "",
    # Enhanced fields
    quality: str = "",  # useful | generic | empty (auto-classified if blank)
    cache: str = "",  # hit | miss (from Brick response)
    tokens_original: int = 0,  # for Read gate: original file tokens
    tokens_summary: int = 0,  # for Read gate: summary tokens
    relevance_score: float = 0.0,  # for SessionStart: Pinecone score
    spool_stage: str = "",  # for async: pending | ready | injected
) -> None:
    """Log a single enrichment event. Never raises."""
    try:
        METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Auto-classify quality if not provided
        if not quality and action == "enriched" and findings_preview:
            quality = classify_quality(findings_preview)

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

        # Schema version for forward compatibility (BES Bot recommendation)
        entry["v"] = 2

        # Raw fields (always present when populated)
        if cache:
            entry["cache"] = cache
        if tokens_original:
            entry["source_tokens_est"] = tokens_original
            entry["summary_tokens_est"] = tokens_summary
        if relevance_score > 0:
            entry["top_score"] = round(relevance_score, 3)
        if spool_stage:
            entry["spool_stage"] = spool_stage

        # Derived fields (clearly labeled as derived)
        if quality:
            entry["quality"] = quality
        if tokens_original and tokens_summary:
            entry["saved_tokens_est"] = tokens_original - tokens_summary

        with open(METRICS_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Never fail the hook for metrics
