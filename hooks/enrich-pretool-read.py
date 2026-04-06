#!/usr/bin/env python3
"""PreToolUse(Read) hook: context window protection via Brick file summaries.

When an agent is about to read a file >200 lines, sends head+tail to Brick
for a structural summary and injects it as additionalContext. The agent
still gets the full file — this just helps them navigate it.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
from hook_utils import read_hook_input, allow_with_context, run_fail_open

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from brick_circuit import CircuitBreaker
from brick_common import get_brick_api_key, call_brick, generate_enrichment_id, build_enrichment_context
from brick_metrics import log_enrichment

_HOOK_NAME = "enrich-pretool-read"
_EVENT_NAME = "PreToolUse"
_LINES_THRESHOLD = 200
_HEAD_LINES = 200
_TAIL_LINES = 200
_TIMEOUT_S = 15

BRICK_BASE_URL = os.environ.get("BRICK_BASE_URL", "https://brick.tail64ad01.ts.net:8443")


def get_line_count(file_path: str) -> int | None:
    """Get line count via wc -l. Returns None if file doesn't exist."""
    try:
        result = subprocess.run(
            ["wc", "-l", file_path],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        # wc -l output: "  123 /path/to/file"
        return int(result.stdout.strip().split()[0])
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def extract_head_tail(file_path: str, head: int = _HEAD_LINES, tail: int = _TAIL_LINES) -> str | None:
    """Read first `head` and last `tail` lines of a file via Python."""
    try:
        with open(file_path, "r", errors="replace") as f:
            lines = f.readlines()
    except (OSError, PermissionError):
        return None

    if not lines:
        return None

    total = len(lines)
    if total <= head + tail:
        return "".join(lines)

    head_part = "".join(lines[:head])
    tail_part = "".join(lines[-tail:])
    return f"{head_part}\n[... {total - head - tail} lines omitted ...]\n\n{tail_part}"


def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    if tool_name != "Read":
        sys.exit(0)

    session_id = input_data.get("session_id", "")
    file_path = input_data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        sys.exit(0)

    cb = CircuitBreaker()

    # OPEN -> skip entirely; DEGRADED -> still allow (so record_success can heal)
    if not cb.allow_request():
        log_enrichment("read", session_id, "Read", file_path, action="skipped", reason="circuit_breaker")
        sys.exit(0)

    # Check line count
    line_count = get_line_count(file_path)
    if line_count is None:
        log_enrichment("read", session_id, "Read", file_path, action="skipped", reason="file_not_found")
        sys.exit(0)

    if line_count <= _LINES_THRESHOLD:
        log_enrichment("read", session_id, "Read", file_path, action="skipped", reason="small_file", lines_changed=line_count)
        sys.exit(0)

    api_key = get_brick_api_key()
    if not api_key:
        log_enrichment("read", session_id, "Read", file_path, action="skipped", reason="no_api_key")
        sys.exit(0)

    # Extract head + tail
    content = extract_head_tail(file_path)
    if not content:
        log_enrichment("read", session_id, "Read", file_path, action="skipped", reason="empty_file")
        sys.exit(0)

    t0 = time.monotonic()
    summary, failure_reason = call_brick(
        content, api_key,
        intent_key="extract_structure",
        intent_note="Summarize this file's structure: key sections, important functions/classes, and line ranges. Help the reader focus on what matters.",
        timeout_s=_TIMEOUT_S,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)

    if summary:
        cb.record_success()
        enrichment_id = generate_enrichment_id()
        tokens_orig = int(line_count * 80 / 4)
        tokens_summ = int(len(summary) / 4)
        context = build_enrichment_context("Read", file_path, summary, enrichment_id, extra_info=f"{line_count} lines")
        log_enrichment(
            "read", session_id, "Read", file_path,
            action="enriched", latency_ms=latency_ms,
            findings_preview=summary, lines_changed=line_count,
            tokens_original=tokens_orig, tokens_summary=tokens_summ,
            enrichment_id=enrichment_id,
        )
        allow_with_context(context, event=_EVENT_NAME)
    else:
        cb.record_failure()
        log_enrichment("read", session_id, "Read", file_path, action="failed", reason=failure_reason, latency_ms=latency_ms, lines_changed=line_count)
        sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
