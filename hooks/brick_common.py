#!/usr/bin/env python3
"""Shared utilities for Brick enrichment hooks.

Consolidates duplicate functions found across enrich-pretool-read.py,
enrich-posttool-write.py, enrich-pretool-commit.py, and enrich-pretool-pr.py.
"""
import json
import os
import ssl
import subprocess
import uuid
import urllib.error
import urllib.request
from typing import Any

BRICK_BASE_URL = os.environ.get("BRICK_BASE_URL", "https://brick.tail64ad01.ts.net:8443")


def make_ssl_context() -> ssl.SSLContext:
    """Create SSL context for Brick API calls (shared across all hooks)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def get_brick_api_key() -> str | None:
    """Get Brick API key from env or GNOME keyring.

    Previously duplicated in 4 hook files as _get_api_key().
    """
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


def call_brick(
    content: str,
    api_key: str,
    *,
    task_class: str = "generic",
    format_hint: str = "plain_text",
    intent_key: str = "extract_structure",
    intent_note: str = "",
    timeout_s: int = 15,
) -> tuple[str | None, str | None]:
    """POST to Brick preprocess endpoint.

    Returns (summary, None) on success or (None, failure_reason) on failure.

    Previously duplicated as:
    - call_brick_summarize() in enrich-pretool-read.py
    - call_brick_preprocess() in enrich-posttool-write.py
    - _call_brick() in enrich-pretool-commit.py
    - _call_brick() in enrich-pretool-pr.py
    """
    import socket

    url = f"{BRICK_BASE_URL}/enrich/v1/preprocess"
    payload = json.dumps({
        "content": content,
        "task_class": task_class,
        "format_hint": format_hint,
        "intent_key": intent_key,
        "intent_note": intent_note,
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
        ctx = make_ssl_context()
        with urllib.request.urlopen(req, timeout=timeout_s, context=ctx) as resp:
            data = json.loads(resp.read())
            summary = data.get("tree", {}).get("root", {}).get("content", "").strip()
            return (summary, None) if summary else (None, "empty_response")
    except socket.timeout:
        return (None, "timeout")
    except urllib.error.HTTPError as e:
        return (None, f"http_{e.code}")
    except urllib.error.URLError as e:
        if "timed out" in str(e.reason):
            return (None, "timeout")
        return (None, "url_error")
    except (json.JSONDecodeError, OSError, TimeoutError):
        return (None, "unknown_error")


def generate_enrichment_id() -> str:
    """Generate a 12-char UUID for enrichment correlation."""
    return str(uuid.uuid4())[:12]


def build_enrichment_context(
    hook_label: str,
    file_path: str,
    summary: str,
    enrichment_id: str,
    *,
    extra_info: str = "",
    verb: str = "enriched",
) -> str:
    """Build additionalContext string with machine-readable enrichment_id.

    Previously duplicated as:
    - build_enrichment_context() in enrich-pretool-read.py
    - build_write_enrichment_context() in enrich-posttool-write.py

    Args:
        hook_label: e.g. "Read", "Write", "Commit", "PR"
        file_path: file being operated on (can be empty for non-file hooks)
        summary: the enrichment findings text
        enrichment_id: machine-readable correlation key
        extra_info: optional extra metadata (e.g. line count)
        verb: action verb (default "enriched", use "reviewed" for Write hooks)
    """
    parts = [f"[\U0001f9f1 Brick {verb} {hook_label}:"]
    if file_path:
        parts.append(f" {file_path}")
    if extra_info:
        parts.append(f" ({extra_info})")
    parts.append(f" enrichment_id={enrichment_id}")
    parts.append(f" \u2014 show this to user] {summary}")
    return "".join(parts)
