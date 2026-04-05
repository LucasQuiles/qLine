#!/usr/bin/env python3
"""PostToolUse enrichment hook: sends code changes to Brick preprocess API.

Scope: Write, Edit, MultiEdit tools on code files with >20 lines changed.
Circuit breaker: skips enrichment when OPEN or DEGRADED.
Fail-open: any uncaught exception exits 0 silently.
"""
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
from hook_utils import read_hook_input, allow_with_context, run_fail_open

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from brick_circuit import CircuitBreaker
from brick_metrics import log_enrichment

_HOOK_NAME = "enrich-posttool-write"
_EVENT_NAME = "PostToolUse"
_ENRICHABLE_TOOLS = {"Write", "Edit", "MultiEdit"}
_LINES_THRESHOLD = 20
_TIMEOUT_S = 15

BRICK_BASE_URL = os.environ.get("BRICK_BASE_URL", "https://brick.tail64ad01.ts.net:8443")

CODE_EXTENSIONS: set[str] = {
    ".ts", ".tsx", ".js", ".jsx", ".py", ".sh", ".sql",
    ".rs", ".go", ".vue", ".svelte", ".java", ".rb",
    ".c", ".cpp", ".h",
}


# ------------------------------------------------------------------
# Exported helpers (for testing)
# ------------------------------------------------------------------

def is_code_file(path: str) -> bool:
    """Return True if the file extension is in CODE_EXTENSIONS."""
    _, ext = os.path.splitext(path)
    return ext.lower() in CODE_EXTENSIONS


def count_lines_changed(input_data: dict[str, Any]) -> int:
    """Count lines changed based on tool type."""
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    if tool_name == "Write":
        content = tool_input.get("content", "")
        return len(content.splitlines()) if content else 0
    elif tool_name in ("Edit", "MultiEdit"):
        new_string = tool_input.get("new_string", "")
        return len(new_string.splitlines()) if new_string else 0
    return 0


def should_enrich(tool_name: str, file_path: str, lines_changed: int) -> bool:
    """Decide whether to enrich based on tool, file type, and change size."""
    if tool_name not in _ENRICHABLE_TOOLS:
        return False
    if not is_code_file(file_path):
        return False
    if lines_changed <= _LINES_THRESHOLD:
        return False
    return True


def extract_summary(data: dict[str, Any]) -> str | None:
    """Extract root summary from Brick preprocess response data."""
    try:
        return data["tree"]["root"]["content"]
    except (KeyError, TypeError):
        return None


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


def call_brick_preprocess(
    content: str, format_hint: str, api_key: str,
    task_class: str = "diff_review",
) -> str | None:
    """POST to Brick preprocess endpoint. Returns summary or None on failure."""
    url = f"{BRICK_BASE_URL}/enrich/v1/preprocess"
    payload = json.dumps({
        "content": content,
        "task_class": task_class,
        "format_hint": format_hint,
        "intent_key": "flag_risks",
        "intent_note": "PostToolUse enrichment — flag security issues, logic errors, regressions, missing error handling",
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
            resp_data = json.loads(resp.read())
            return extract_summary(resp_data)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError,
            OSError, TimeoutError):
        return None


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    if tool_name not in _ENRICHABLE_TOOLS:
        sys.exit(0)

    session_id = input_data.get("session_id", "")
    cb = CircuitBreaker()

    # OPEN -> skip entirely
    if not cb.allow_request():
        log_enrichment("write", session_id, tool_name, action="skipped", reason="circuit_open")
        sys.exit(0)

    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    lines_changed = count_lines_changed(input_data)

    if not should_enrich(tool_name, file_path, lines_changed):
        reason = "non_code_file" if not is_code_file(file_path) else "below_threshold"
        log_enrichment("write", session_id, tool_name, file_path, action="skipped", reason=reason, lines_changed=lines_changed)
        sys.exit(0)

    # Determine content and format hint
    if tool_name == "Write":
        content = tool_input.get("content", "")
        format_hint = "plain_text"
    else:
        content = tool_input.get("new_string", "")
        format_hint = "diff"

    # DEGRADED -> downgrade to async spool instead of sync call
    if cb.is_degraded():
        try:
            from enrich_posttool_bash import write_spool_entry
            import uuid
            _SPOOL_ROOT = "/tmp/brick-lab/enrich-queue"
            trace_id = str(uuid.uuid4())[:12]
            write_spool_entry(_SPOOL_ROOT, tool_name, content, session_id or "unknown", trace_id)
        except Exception:
            pass  # fail-open
        log_enrichment("write", session_id, tool_name, file_path, action="degraded", reason="circuit_degraded", lines_changed=lines_changed)
        sys.exit(0)

    api_key = _get_api_key()
    if not api_key:
        log_enrichment("write", session_id, tool_name, file_path, action="skipped", reason="no_api_key")
        sys.exit(0)

    # Use "generic" for all tools — "diff_review" cache collisions produce
    # hallucinated results, and "generic" + flag_risks catches more issues.
    # Depth 2 for Edit/MultiEdit to catch subtle bugs in diffs.
    task_class = "generic"
    t0 = time.monotonic()
    summary = call_brick_preprocess(content, format_hint, api_key, task_class=task_class)
    latency_ms = int((time.monotonic() - t0) * 1000)

    if summary is not None:
        cb.record_success()
        log_enrichment("write", session_id, tool_name, file_path, action="enriched", latency_ms=latency_ms, findings_preview=summary, lines_changed=lines_changed)
        allow_with_context(f"[Brick review] {summary}", event=_EVENT_NAME)
    else:
        cb.record_failure()
        log_enrichment("write", session_id, tool_name, file_path, action="failed", latency_ms=latency_ms, lines_changed=lines_changed)
        sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
