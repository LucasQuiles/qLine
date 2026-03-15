#!/usr/bin/env python3
"""Claude Code status-line command.

Reads Claude status JSON from stdin, emits exactly one deterministic
stdout line (or empty output), exits 0 on recoverable failures.

Contract:
  - One bounded binary stdin read with overall deadline
  - Byte-capped (not char-capped) input
  - Sparse-safe normalizer: documented fields are baseline, runtime
    additions are optional
  - Pure renderer: fixed module order, ASCII-safe separators, no
    shell/network/secret dependencies
  - No stderr on normal execution
  - Exit 0 on all recoverable failures

Ownership: local code owns stdin intake, normalization, formatting,
and silent failure behavior. Claude runtime owns cadence, payload
assembly, trust gating, command invocation, and final rendering.
"""
from __future__ import annotations

import json
import os
import select
import sys
from typing import Any

# --- Constants ---

MAX_STDIN_BYTES = 524_288  # 512 KB byte budget (binary read)
READ_DEADLINE_S = 0.2      # Overall read deadline in seconds

# Context window thresholds
CONTEXT_WARN_PCT = 70
CONTEXT_CRITICAL_PCT = 85


# --- Reader ---

def read_stdin_bounded() -> dict[str, Any] | None:
    """Single-read bounded binary stdin reader.

    Enforces:
      - Overall read deadline (not just first-byte)
      - Byte cap (not character cap)
      - Single read only (no remainder consumption)
      - Returns dict or None

    Returns None on: timeout, empty, malformed JSON, non-dict JSON,
    decode failure, or any exception.
    """
    try:
        stdin_fd = sys.stdin.buffer
        if not select.select([stdin_fd], [], [], READ_DEADLINE_S)[0]:
            return None
        raw = stdin_fd.read(MAX_STDIN_BYTES)
        if not raw:
            return None
        text = raw.decode("utf-8", errors="replace")
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            return None
        return parsed
    except Exception:
        return None


# --- Normalizer ---

def normalize(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a normalized internal state from the raw payload.

    Documented fields (baseline):
      - model.display_name -> model_name
      - workspace.current_dir (fallback to cwd) -> dir_basename
      - version -> version
      - output_style.name -> output_style
      - cost.total_cost_usd -> cost_usd
      - cost.total_duration_ms -> duration_ms

    Optional/version-sensitive fields:
      - context_window.used, context_window.total -> context_used, context_total
      - added_dirs -> added_dirs (list)
      - worktree -> is_worktree (bool)
      - current_usage -> current_usage (dict)
      - agent_id -> agent_id (str)
    """
    state: dict[str, Any] = {}

    # Model name
    model = payload.get("model")
    if isinstance(model, dict):
        name = model.get("display_name")
        if isinstance(name, str) and name:
            state["model_name"] = name

    # Directory — prefer workspace.current_dir, fall back to cwd
    workspace = payload.get("workspace")
    current_dir = None
    if isinstance(workspace, dict):
        current_dir = workspace.get("current_dir")
    if not isinstance(current_dir, str) or not current_dir:
        current_dir = payload.get("cwd")
    if isinstance(current_dir, str) and current_dir:
        state["dir_basename"] = os.path.basename(current_dir) or current_dir

    # Version
    version = payload.get("version")
    if isinstance(version, str) and version:
        state["version"] = version

    # Output style
    output_style = payload.get("output_style")
    if isinstance(output_style, dict):
        style_name = output_style.get("name")
        if isinstance(style_name, str) and style_name:
            state["output_style"] = style_name

    # Cost fields
    cost = payload.get("cost")
    if isinstance(cost, dict):
        cost_usd = cost.get("total_cost_usd")
        if isinstance(cost_usd, (int, float)):
            state["cost_usd"] = float(cost_usd)
        duration_ms = cost.get("total_duration_ms")
        if isinstance(duration_ms, (int, float)):
            state["duration_ms"] = int(duration_ms)

    # Optional: context window
    ctx_window = payload.get("context_window")
    if isinstance(ctx_window, dict):
        used = ctx_window.get("used")
        total = ctx_window.get("total")
        if isinstance(used, (int, float)) and isinstance(total, (int, float)) and total > 0:
            state["context_used"] = int(used)
            state["context_total"] = int(total)

    # Optional: added_dirs
    added_dirs = payload.get("added_dirs")
    if isinstance(added_dirs, list):
        state["added_dirs"] = added_dirs

    # Optional: worktree
    worktree = payload.get("worktree")
    if isinstance(worktree, bool):
        state["is_worktree"] = worktree

    # Optional: current_usage
    current_usage = payload.get("current_usage")
    if isinstance(current_usage, dict):
        state["current_usage"] = current_usage

    # Optional: agent_id
    agent_id = payload.get("agent_id")
    if isinstance(agent_id, str) and agent_id:
        state["agent_id"] = agent_id

    return state


# --- Renderer ---

def _sanitize_fragment(text: str) -> str:
    """Remove newlines and control characters from a fragment."""
    return text.replace("\n", " ").replace("\r", "").replace("\t", " ").strip()


def _format_cost(cost_usd: float) -> str:
    """Format cost with appropriate precision."""
    if cost_usd < 0.01:
        return f"${cost_usd:.4f}"
    return f"${cost_usd:.2f}"


def _format_duration(duration_ms: int) -> str:
    """Format duration in human-readable form."""
    seconds = duration_ms // 1000
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    remaining_s = seconds % 60
    if minutes < 60:
        if remaining_s:
            return f"{minutes}m{remaining_s}s"
        return f"{minutes}m"
    hours = minutes // 60
    remaining_m = minutes % 60
    if remaining_m:
        return f"{hours}h{remaining_m}m"
    return f"{hours}h"


def _format_context(used: int, total: int) -> str:
    """Format context window usage with threshold indicators."""
    pct = (used * 100) // total
    if pct >= CONTEXT_CRITICAL_PCT:
        return f"ctx:{pct}%!"
    if pct >= CONTEXT_WARN_PCT:
        return f"ctx:{pct}%~"
    return f"ctx:{pct}%"


def render(state: dict[str, Any]) -> str:
    """Render a single status line from normalized state.

    Module order: model -> dir -> context -> cost -> duration
    Separator: ' | '
    Omits absent modules.
    """
    parts: list[str] = []

    # Module: model
    model_name = state.get("model_name")
    if model_name:
        parts.append(_sanitize_fragment(model_name))

    # Module: dir
    dir_basename = state.get("dir_basename")
    if dir_basename:
        parts.append(_sanitize_fragment(dir_basename))

    # Module: context
    if "context_used" in state and "context_total" in state:
        parts.append(_format_context(state["context_used"], state["context_total"]))

    # Module: cost
    if "cost_usd" in state:
        parts.append(_format_cost(state["cost_usd"]))

    # Module: duration
    if "duration_ms" in state:
        parts.append(_format_duration(state["duration_ms"]))

    if not parts:
        return ""

    line = " | ".join(parts)
    # Final sanitization: ensure single line, no newlines
    return _sanitize_fragment(line)


# --- Entrypoint ---

def main() -> None:
    """Status-line entrypoint. Read, normalize, render, emit."""
    payload = read_stdin_bounded()
    if payload is None:
        return
    state = normalize(payload)
    line = render(state)
    if line:
        print(line)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
