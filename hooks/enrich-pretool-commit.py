#!/usr/bin/env python3
"""PreToolUse hook: suggest commit messages via Brick LLM.

Fires on Bash commands matching `git commit`. Reads staged diff,
sends to Brick preprocess, injects suggested message as additionalContext.
"""
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
from hook_utils import read_hook_input, allow_with_context, run_fail_open

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from brick_circuit import CircuitBreaker
from brick_common import get_brick_api_key, call_brick, generate_enrichment_id, build_enrichment_context
from brick_metrics import log_enrichment

_HOOK_NAME = "enrich-pretool-commit"
_EVENT_NAME = "PreToolUse"
_TIMEOUT_S = 15
_MAX_DIFF_CHARS = 32000
_COMMIT_RE = re.compile(r'\bgit\s+commit\b')
_ALLOW_EMPTY_RE = re.compile(r'--allow-empty')


def _get_staged_diff():
    """Get staged diff. Returns (diff_text, stats_text) or (None, None) if empty."""
    try:
        stats = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            capture_output=True, text=True, timeout=10,
        )
        if stats.returncode != 0 or not stats.stdout.strip():
            return None, None

        diff = subprocess.run(
            ["git", "diff", "--cached"],
            capture_output=True, text=True, timeout=10,
        )
        if diff.returncode != 0 or not diff.stdout.strip():
            return None, None

        diff_text = diff.stdout
        if len(diff_text) > _MAX_DIFF_CHARS:
            half = _MAX_DIFF_CHARS // 2
            diff_text = diff_text[:half] + "\n[... truncated ...]\n" + diff_text[-half:]

        return diff_text, stats.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None, None


def main():
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    if tool_name != "Bash":
        sys.exit(0)

    command = input_data.get("tool_input", {}).get("command", "")
    if not _COMMIT_RE.search(command):
        sys.exit(0)

    if _ALLOW_EMPTY_RE.search(command):
        sys.exit(0)

    session_id = input_data.get("session_id", "")
    cb = CircuitBreaker()
    if not cb.allow_request():
        log_enrichment("commit", session_id, "Bash", action="skipped", reason="circuit_breaker")
        sys.exit(0)

    api_key = get_brick_api_key()
    if not api_key:
        log_enrichment("commit", session_id, "Bash", action="skipped", reason="no_api_key")
        sys.exit(0)

    diff_text, stats = _get_staged_diff()
    if not diff_text:
        log_enrichment("commit", session_id, "Bash", action="skipped", reason="no_staged_changes")
        sys.exit(0)

    content = f"Staged changes:\n{stats}\n\nDiff:\n{diff_text}"
    t0 = time.monotonic()
    suggestion, failure_reason = call_brick(
        content, api_key,
        task_class="diff_review",
        format_hint="diff",
        intent_key="explain_changes",
        intent_note="Generate a conventional commit message (feat:/fix:/docs:/refactor:/test:). One-line summary under 72 chars. Optional body with bullet points if complex.",
        timeout_s=_TIMEOUT_S,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)

    if suggestion:
        cb.record_success()
        enrichment_id = generate_enrichment_id()
        context = build_enrichment_context("Commit", "", suggestion, enrichment_id)
        log_enrichment("commit", session_id, "Bash", action="enriched", latency_ms=latency_ms, findings_preview=suggestion, enrichment_id=enrichment_id)
        allow_with_context(context, event=_EVENT_NAME)
    else:
        cb.record_failure()
        log_enrichment("commit", session_id, "Bash", action="failed", reason=failure_reason or "", latency_ms=latency_ms)
        sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
