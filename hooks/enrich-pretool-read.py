#!/usr/bin/env python3
"""PreToolUse(Read) hook: context window protection via Brick file summaries.

When an agent is about to read a file >200 lines, sends head+tail to Brick
for a structural summary and injects it as additionalContext. The agent
still gets the full file — this just helps them navigate it.
"""
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
from hook_utils import read_hook_input, allow_with_context, run_fail_open

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from brick_circuit import CircuitBreaker
from brick_metrics import log_enrichment

_HOOK_NAME = "enrich-pretool-read"
_EVENT_NAME = "PreToolUse"
_LINES_THRESHOLD = 200
_HEAD_LINES = 200
_TAIL_LINES = 200
_TIMEOUT_S = 15

BRICK_BASE_URL = os.environ.get("BRICK_BASE_URL", "https://brick.tail64ad01.ts.net:8443")


def _get_api_key() -> str | None:
    """Get Brick API key from env or keyring."""
    key = os.environ.get("BRICK_API_KEY")
    if key:
        return key
    try:
        result = subprocess.run(
            ["secret-tool", "lookup", "service", "brick-api-key"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


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


def call_brick_summarize(content: str, file_path: str, api_key: str) -> str | None:
    """POST to Brick preprocess for structural summary. Returns summary or None."""
    url = f"{BRICK_BASE_URL}/enrich/v1/preprocess"
    payload = json.dumps({
        "content": content,
        "task_class": "generic",
        "format_hint": "plain_text",
        "intent_key": "extract_structure",
        "intent_note": (
            "Summarize this file's structure: key sections, important "
            "functions/classes, and line ranges. Help the reader focus on what matters."
        ),
        "tree_depth": 1,
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S, context=ctx) as resp:
            data = json.loads(resp.read())
            summary = data.get("tree", {}).get("root", {}).get("content", "").strip()
            return summary or None
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError,
            OSError, TimeoutError):
        return None


def build_enrichment_context(
    file_path: str, line_count: int, summary: str, enrichment_id: str,
) -> str:
    """Build additionalContext string with machine-readable enrichment_id."""
    return (
        f"[🧱 Brick enriched Read: {file_path} ({line_count} lines) "
        f"enrichment_id={enrichment_id} — show this to user] {summary}"
    )


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

    api_key = _get_api_key()
    if not api_key:
        log_enrichment("read", session_id, "Read", file_path, action="skipped", reason="no_api_key")
        sys.exit(0)

    # Extract head + tail
    content = extract_head_tail(file_path)
    if not content:
        log_enrichment("read", session_id, "Read", file_path, action="skipped", reason="empty_file")
        sys.exit(0)

    t0 = time.monotonic()
    summary = call_brick_summarize(content, file_path, api_key)
    latency_ms = int((time.monotonic() - t0) * 1000)

    if summary:
        cb.record_success()
        import uuid
        enrichment_id = str(uuid.uuid4())[:12]
        tokens_orig = int(line_count * 80 / 4)
        tokens_summ = int(len(summary) / 4)
        context = build_enrichment_context(file_path, line_count, summary, enrichment_id)
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
        log_enrichment("read", session_id, "Read", file_path, action="failed", latency_ms=latency_ms, lines_changed=line_count)
        sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
