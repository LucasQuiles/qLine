#!/usr/bin/env python3
"""PreToolUse hook: suggest commit messages via Brick LLM.

Fires on Bash commands matching `git commit`. Reads staged diff,
sends to Brick preprocess, injects suggested message as additionalContext.
"""
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.error
import socket

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
from hook_utils import read_hook_input, allow_with_context, run_fail_open

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from brick_circuit import CircuitBreaker
from brick_metrics import log_enrichment

_HOOK_NAME = "enrich-pretool-commit"
_EVENT_NAME = "PreToolUse"
_TIMEOUT_S = 15
_MAX_DIFF_CHARS = 32000
_COMMIT_RE = re.compile(r'\bgit\s+commit\b')
_ALLOW_EMPTY_RE = re.compile(r'--allow-empty')
BRICK_BASE_URL = os.environ.get("BRICK_BASE_URL", "https://brick.tail64ad01.ts.net:8443")


def _get_api_key():
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


def _call_brick(content, api_key):
    """Call Brick preprocess and return root summary."""
    url = f"{BRICK_BASE_URL}/enrich/v1/preprocess"
    body = json.dumps({
        "content": content,
        "task_class": "diff_review",
        "format_hint": "diff",
        "intent_key": "explain_changes",
        "intent_note": "Generate a conventional commit message (feat:/fix:/docs:/refactor:/test:). One-line summary under 72 chars. Optional body with bullet points if complex.",
        "tree_depth": 1,
    }).encode()

    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }, method="POST")

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S, context=ctx) as resp:
            data = json.loads(resp.read())
            return data.get("tree", {}).get("root", {}).get("content", "").strip() or None
    except Exception:
        return None


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
    if not cb.allow_request() or cb.is_degraded():
        log_enrichment("commit", session_id, "Bash", action="skipped", reason="circuit_breaker")
        sys.exit(0)

    api_key = _get_api_key()
    if not api_key:
        log_enrichment("commit", session_id, "Bash", action="skipped", reason="no_api_key")
        sys.exit(0)

    diff_text, stats = _get_staged_diff()
    if not diff_text:
        log_enrichment("commit", session_id, "Bash", action="skipped", reason="no_staged_changes")
        sys.exit(0)

    content = f"Staged changes:\n{stats}\n\nDiff:\n{diff_text}"
    t0 = time.monotonic()
    suggestion = _call_brick(content, api_key)
    latency_ms = int((time.monotonic() - t0) * 1000)

    if suggestion:
        cb.record_success()
        log_enrichment("commit", session_id, "Bash", action="enriched", latency_ms=latency_ms, findings_preview=suggestion)
        allow_with_context(f"[Brick suggests commit message] {suggestion}", event=_EVENT_NAME)
    else:
        cb.record_failure()
        log_enrichment("commit", session_id, "Bash", action="failed", latency_ms=latency_ms)
        sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
