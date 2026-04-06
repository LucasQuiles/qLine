#!/usr/bin/env python3
"""PreToolUse hook: suggest PR descriptions via Brick LLM.

Fires on Bash commands matching `gh pr create`. Reads branch diff,
sends to Brick preprocess, injects suggested description as additionalContext.
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

_HOOK_NAME = "enrich-pretool-pr"
_EVENT_NAME = "PreToolUse"
_TIMEOUT_S = 15
_MAX_DIFF_CHARS = 32000
_PR_CREATE_RE = re.compile(r'\bgh\s+pr\s+create\b')
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


def _detect_base_branch():
    """Detect the base branch for diff comparison."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD@{upstream}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            upstream = result.stdout.strip()  # e.g., "origin/main"
            return upstream.split("/")[-1]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    # Fallback: check main, then master
    for branch in ("main", "master"):
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--verify", branch],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return branch
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
    return "HEAD~10"


def _get_branch_diff(base):
    """Get branch diff and commit list. Returns (diff_text, commits) or (None, None)."""
    try:
        diff = subprocess.run(
            ["git", "diff", f"{base}...HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if diff.returncode != 0 or not diff.stdout.strip():
            return None, None

        commits = subprocess.run(
            ["git", "log", f"{base}..HEAD", "--oneline"],
            capture_output=True, text=True, timeout=10,
        )
        commits_text = commits.stdout.strip() if commits.returncode == 0 else ""

        diff_text = diff.stdout
        if len(diff_text) > _MAX_DIFF_CHARS:
            half = _MAX_DIFF_CHARS // 2
            diff_text = diff_text[:half] + "\n[... truncated ...]\n" + diff_text[-half:]

        return diff_text, commits_text
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None, None


def _call_brick(content, api_key):
    """Call Brick preprocess and return root summary."""
    url = f"{BRICK_BASE_URL}/enrich/v1/preprocess"
    body = json.dumps({
        "content": content,
        "task_class": "diff_review",
        "format_hint": "diff",
        "intent_key": "summarize",
        "intent_note": "Generate a PR description: 2-3 sentence summary, bullet-point list of changes, and a test plan checklist. Format in markdown.",
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
    if not _PR_CREATE_RE.search(command):
        sys.exit(0)

    session_id = input_data.get("session_id", "")
    cb = CircuitBreaker()
    if not cb.allow_request():
        log_enrichment("pr", session_id, "Bash", action="skipped", reason="circuit_breaker")
        sys.exit(0)

    api_key = _get_api_key()
    if not api_key:
        log_enrichment("pr", session_id, "Bash", action="skipped", reason="no_api_key")
        sys.exit(0)

    base = _detect_base_branch()
    diff_text, commits = _get_branch_diff(base)
    if not diff_text:
        log_enrichment("pr", session_id, "Bash", action="skipped", reason="no_branch_diff")
        sys.exit(0)

    content = f"Branch diff against {base}:\n{diff_text}\n\nCommits:\n{commits}"
    t0 = time.monotonic()
    suggestion = _call_brick(content, api_key)
    latency_ms = int((time.monotonic() - t0) * 1000)

    if suggestion:
        cb.record_success()
        log_enrichment("pr", session_id, "Bash", action="enriched", latency_ms=latency_ms, findings_preview=suggestion)
        allow_with_context(f"[🧱 Brick enriched PR — show this to user]\n{suggestion}", event=_EVENT_NAME)
    else:
        cb.record_failure()
        log_enrichment("pr", session_id, "Bash", action="failed", latency_ms=latency_ms)
        sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
