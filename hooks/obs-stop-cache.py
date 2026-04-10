#!/usr/bin/env python3
"""Stop hook: captures per-turn cache metrics from transcript to session package.

Writes to three targets:
  1. hook_events.jsonl — cache.observed event (counter for status line)
  2. custom/cache_metrics.jsonl — full per-turn record (forensics sidecar)
  3. manifest.json — cache_anchor on first non-compaction turn (write-once)

Hardened transcript reading:
  - Every json.loads in try/except, backward scan from EOF
  - Turn-sequence deduplication via transcript entry ID
  - Graceful degradation: emits cache.skipped on any failure
"""
import json
import os
import sys
from typing import Any

from hook_utils import read_hook_input, run_fail_open
from obs_utils import (
    resolve_package_root_env,
    append_event,
    update_manifest_if_absent_batch,
    _atomic_jsonl_append,
    now_iso,
    extract_usage_full,
    load_manifest,
)

_HOOK_NAME = "obs-stop-cache"
_EVENT_NAME = "Stop"
_TAIL_BYTES = 8 * 1024
_MAX_SCAN_LINES = 50


def _extract_latest_cache_metrics(
    transcript_path: str, last_entry_id: str | None
) -> dict[str, Any] | None:
    """Extract cache metrics from the last completed transcript entry.

    Returns dict with cache fields, or None if no new usable entry found.
    Skips streaming stubs (stop_reason=null) and truncated lines.
    """
    try:
        size = os.path.getsize(transcript_path)
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            if size > _TAIL_BYTES:
                f.seek(size - _TAIL_BYTES)
                f.readline()  # Discard partial first line after seek
            lines = f.readlines()
    except OSError:
        return None

    scanned = 0
    for line in reversed(lines):
        if scanned >= _MAX_SCAN_LINES:
            break
        scanned += 1
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        usage, model, _request_id, entry_id = extract_usage_full(entry)
        if usage is None:
            continue

        cache_create = usage.get("cache_creation_input_tokens")
        cache_read = usage.get("cache_read_input_tokens")
        if cache_create is None and cache_read is None:
            continue

        # Deduplication: skip if same entry as last invocation
        if entry_id and entry_id == last_entry_id:
            return None

        cache_creation_detail = usage.get("cache_creation", {})
        if not isinstance(cache_creation_detail, dict):
            cache_creation_detail = {}

        return {
            "cache_read": int(cache_read or 0),
            "cache_create": int(cache_create or 0),
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "cache_create_1h": int(cache_creation_detail.get("ephemeral_1h_input_tokens") or 0),
            "cache_create_5m": int(cache_creation_detail.get("ephemeral_5m_input_tokens") or 0),
            "model": model or "",
            "entry_id": entry_id or "",
        }

    return None



def _read_last_sidecar_entry(sidecar_path: str) -> dict:
    """Read the last non-empty line of the sidecar for dedup and state tracking."""
    try:
        size = os.path.getsize(sidecar_path)
        with open(sidecar_path, "r") as f:
            if size > 2048:
                f.seek(size - 2048)
                f.readline()  # Discard partial
            lines = f.readlines()
        for line in reversed(lines):
            line = line.strip()
            if line:
                try:
                    return json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
    except (OSError, FileNotFoundError):
        pass
    return {}


def _read_compaction_count(package_root: str) -> int:
    """Read current compaction count from manifest compactions array."""
    return len(load_manifest(package_root).get("compactions", []))


def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = input_data.get("session_id")
    if not session_id:
        sys.exit(0)

    # Don't capture during forced continuation
    if input_data.get("stop_hook_active"):
        sys.exit(0)

    transcript_path = input_data.get("transcript_path")
    if not transcript_path:
        sys.exit(0)

    package_root = resolve_package_root_env(session_id)
    if package_root is None:
        sys.exit(0)

    # Read last sidecar entry for dedup and compaction tracking
    sidecar_path = os.path.join(package_root, "custom", "cache_metrics.jsonl")
    last_entry = _read_last_sidecar_entry(sidecar_path)
    last_entry_id = (
        last_entry.get("last_entry_id")
        if not last_entry.get("skipped")
        else None
    )
    last_compaction_count = last_entry.get("compaction_count", 0)

    # Determine turn number
    turn = last_entry.get("turn", 0) + 1

    # Extract cache metrics from transcript
    metrics = _extract_latest_cache_metrics(transcript_path, last_entry_id)

    now = now_iso()
    os.makedirs(os.path.join(package_root, "custom"), exist_ok=True)

    if metrics is None:
        # No new entry — log skip
        skip_record = {
            "ts": now,
            "session_id": session_id,
            "turn": turn,
            "skipped": True,
            "skip_reason": "NO_NEW_ENTRY",
        }
        _atomic_jsonl_append(sidecar_path, skip_record)
        append_event(
            package_root,
            "cache.skipped",
            session_id,
            {"reason": "NO_NEW_ENTRY"},
            origin_type="hook",
            hook=_HOOK_NAME,
        )
        sys.exit(0)

    # Check compaction state via manifest
    current_compaction_count = _read_compaction_count(package_root)
    post_compaction = current_compaction_count > last_compaction_count

    # Build sidecar record
    record = {
        "ts": now,
        "session_id": session_id,
        "turn": turn,
        "cache_read": metrics["cache_read"],
        "cache_create": metrics["cache_create"],
        "input_tokens": metrics["input_tokens"],
        "output_tokens": metrics["output_tokens"],
        "cache_create_1h": metrics["cache_create_1h"],
        "cache_create_5m": metrics["cache_create_5m"],
        "model": metrics["model"],
        "post_compaction": post_compaction,
        "compaction_count": current_compaction_count,
        "last_entry_id": metrics["entry_id"],
        "skipped": False,
    }

    # Write to sidecar
    _atomic_jsonl_append(sidecar_path, record)

    # Write to ledger
    append_event(
        package_root,
        "cache.observed",
        session_id,
        {
            "cache_read": metrics["cache_read"],
            "cache_create": metrics["cache_create"],
            "input_tokens": metrics["input_tokens"],
            "post_compaction": post_compaction,
        },
        origin_type="hook",
        hook=_HOOK_NAME,
    )

    # Anchor: write-once on first non-compaction turn
    if not post_compaction:
        update_manifest_if_absent_batch(
            package_root,
            "cache_anchor",
            {
                "cache_anchor": metrics["cache_create"],
                "cache_anchor_turn": turn,
                "cache_anchor_is_post_compaction": False,
            },
        )


run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
