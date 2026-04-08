#!/usr/bin/env python3
"""Claude Code status-line command — qLine.

Reads Claude status JSON from stdin, emits exactly one styled stdout
line (or empty output), exits 0 on recoverable failures.

Visual: ANSI truecolor, Nerd Font glyphs, threshold-based color
escalation, context progress bar, TOML-configurable theming.

Contract:
  - One bounded binary stdin read with overall deadline
  - Byte-capped (not char-capped) input
  - Sparse-safe normalizer: documented fields are baseline, runtime
    additions are optional
  - Styled renderer: fixed module order, ANSI truecolor, Nerd Font
    glyphs, NO_COLOR support
  - No stderr on normal execution
  - Exit 0 on all recoverable failures
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]  # pip install tomli (Python <3.11)
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]  # TOML config disabled; defaults used
from datetime import datetime, timezone
from typing import Any

from context_overhead import inject_context_overhead

# --- Observability integration (guarded import) ---
try:
    # Look for obs_utils next to this script first, then ~/.claude/scripts/
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    for _obs_path in [_script_dir, os.path.join(os.path.expanduser("~"), ".claude", "scripts")]:
        if _obs_path not in sys.path:
            sys.path.insert(0, _obs_path)
    from obs_utils import resolve_package_root_env, update_health, _atomic_jsonl_append
    _OBS_AVAILABLE = True
except Exception:
    _OBS_AVAILABLE = False

# --- Constants ---

MAX_STDIN_BYTES = 524_288  # 512 KB byte budget (binary read)
READ_DEADLINE_S = 0.2      # Overall read deadline in seconds
CONFIG_PATH = os.path.expanduser("~/.config/qline.toml")
NO_COLOR = bool(os.environ.get("NO_COLOR"))
PROC_DIR = os.environ.get("QLINE_PROC_DIR", "/proc")
CACHE_PATH = os.environ.get("QLINE_CACHE_PATH", "/tmp/qline-cache.json")
CACHE_MAX_AGE_S = 60.0
_alert_state: dict[str, Any] = {}  # in-process cache (reset per invocation)
# NOTE: Since the script runs once and exits per CC call, _alert_state
# must be loaded from / saved to the disk cache for persistence.
# The load/save happens in inject_context_overhead via cache_ctx.
CACHE_VERSION = 1
_FAULT_LEDGER_PATH = os.path.join(
    os.path.expanduser("~"), ".claude", "logs", "lifecycle-hook-faults.jsonl"
)
_FAULT_SCAN_BYTES = 32768  # fast reverse scan: read last 32KB

# --- Default Theme (Muted Ocean) ---

DEFAULT_THEME: dict[str, Any] = {
    "model": {
        "enabled": True,
        "glyph": "\U000f06a9 ",  # nf-md-robot (Supplementary PUA)
        "color": "#d8dee9",
        "bg": "#3b4252",
        "bold": False,
    },
    "dir": {
        "enabled": True,
        "glyph": "\U000f0770 ",  # nf-md-folder_open (Supplementary PUA)
        "color": "#9bb8d3",
        "bg": "#2e3440",
        "worktree_marker": "\u229b",
    },
    "context_bar": {
        "enabled": True,
        "glyph": "\U000f02d1 ",  # nf-md-heart (Supplementary PUA)
        "color": "#8fbcbb",     # nord7 — teal (healthy: cohesive with frost bar)
        "bg": "#2e3440",
        "width": 0,  # 0 = auto (fill available width on its own line)
        "warn_threshold": 40.0,
        "warn_color": "#ebcb8b",   # nord13 — yellow (warn: aurora accent)
        "critical_threshold": 70.0,
        "critical_color": "#bf616a", # nord11 — red (critical: aurora danger)
        # Bar segment colors derive from computed severity (see _darken_hex).
        # No sys_color/conv_color config — segments track health state.
        # Overhead monitor: system overhead thresholds (% of total context window)
        "sys_warn_threshold": 30.0,
        "sys_critical_threshold": 50.0,
        # Overhead monitor: cache health thresholds
        "cache_warn_rate": 0.8,
        "cache_critical_rate": 0.3,
        # Overhead monitor: data source control
        "overhead_source": "auto",
    },
    "tokens": {
        "enabled": True,
        "color": "#a8d4d0",
        "bg": "#2e3440",
    },
    "sys_overhead": {
        "enabled": True,
        "glyph": "\U000f0456 ",  # nf-md-file_alert
        "color": "#81a1c1",      # nord9 blue
        "bg": "#2e3440",
    },
    "cache_writes": {
        "enabled": True,
        "glyph": "",             # no glyph for normal, spike glyph inline
        "color": "#8fbcbb",      # nord7 teal (normal)
        "bg": "#2e3440",
        "spike_color": "#bf616a",     # nord11 red (spike)
        "notable_color": "#ebcb8b",   # nord13 yellow (notable)
        "spike_threshold": 5000,
        "notable_threshold": 1000,
    },
    "cost": {
        "enabled": True,
        "glyph": "$",
        "color": "#e0956a",
        "bg": "#2e3440",
        "warn_threshold": 2.0,
        "warn_color": "#f0d399",
        "critical_threshold": 5.0,
        "critical_color": "#d06070",
    },
    "duration": {
        "enabled": True,
        "glyph": "\U000f0954 ",  # nf-md-clock_outline (Supplementary PUA)
        "color": "#8eacb8",
        "bg": "#2e3440",
    },
    "separator": {
        "char": "\u2502",      # │
        "dim": True,
    },
    "pill": {
        "left": "",
        "right": "",
    },
    "layout": {
        "force_single_line": False,
        "max_width": 200,
        "line1": ["model", "token_counts", "token_out_counts", "context_bar",
                  "cache_rate", "duration"],
        "line2": ["sys_overhead_pill", "cache_read", "cache_delta",
                  "turns", "obs_reads", "obs_rereads", "obs_writes",
                  "obs_bash", "obs_failures", "obs_prompts", "obs_tasks",
                  "obs_subagents", "obs_health", "obs_compactions",
                  "obs_hook_faults", "cost"],
        "line3": ["dir", "git", "cpu", "memory", "disk"],
    },
    "git": {
        "enabled": True,
        "glyph": "\U000f04a9 ",
        "color": "#b48ead",
        "bg": "#2e3440",
        "dirty_marker": "*",
    },
    "cpu": {
        "enabled": True,
        "glyph": "\U000f04cc ",  # nf-md-chip (Supplementary PUA)
        "color": "#a8d4d0",
        "bg": "#2e3440",
        "width": 5,
        "warn_threshold": 60.0,
        "critical_threshold": 85.0,
        "warn_color": "#f0d399",
        "critical_color": "#d06070",
        "show_threshold": 0,
    },
    "memory": {
        "enabled": True,
        "glyph": "\U000f035b ",  # nf-md-memory (Supplementary PUA)
        "color": "#a8d4d0",
        "bg": "#2e3440",
        "width": 5,
        "warn_threshold": 70.0,
        "critical_threshold": 90.0,
        "warn_color": "#f0d399",
        "critical_color": "#d06070",
        "show_threshold": 0,
    },
    "disk": {
        "enabled": True,
        "glyph": "\U000f02ca ",  # nf-md-harddisk (Supplementary PUA)
        "color": "#a8d4d0",
        "bg": "#2e3440",
        "path": "/",
        "width": 5,
        "warn_threshold": 80.0,
        "critical_threshold": 95.0,
        "warn_color": "#f0d399",
        "critical_color": "#d06070",
        "show_threshold": 0,
    },
    "agents": {
        "enabled": False,
        "glyph": "\U000f04cc ",
        "color": "#b48ead",
        "bg": "#2e3440",
        "warn_threshold": 5,
        "critical_threshold": 8,
        "warn_color": "#f0d399",
        "critical_color": "#d06070",
        "show_threshold": 0,
    },
    "tmux": {
        "enabled": False,
        "glyph": "tmux ",
        "color": "#8eacb8",
        "bg": "#2e3440",
    },
    # --- Obs: I/O group ---
    "obs_reads": {
        "enabled": True,
        "glyph": "\U000f0447 ",  # nf-md-file_document (󰑇)
        "color": "#a5b4fc",
        "bg": "#2e3440",
    },
    "obs_rereads": {
        "enabled": True,
        "glyph": "\u00ae ",  # ® (registered sign)
        "color": "#a5b4fc",
        "bg": "#2e3440",
        "warn_threshold": 30,
        "critical_threshold": 50,
        "warn_color": "#f0d399",
        "critical_color": "#d06070",
    },
    "obs_writes": {
        "enabled": True,
        "glyph": "\U000f064f ",  # nf-md-lead_pencil
        "color": "#86efac",
        "bg": "#2e3440",
    },
    "obs_bash": {
        "enabled": True,
        "glyph": "\U000f018d ",  # nf-md-console
        "color": "#fcd34d",
        "bg": "#2e3440",
    },
    # --- Obs: Work group ---
    "obs_prompts": {
        "enabled": True,
        "glyph": "\U000f017a ",  # nf-md-comment_text
        "color": "#d8b4fe",
        "bg": "#2e3440",
    },
    "obs_tasks": {
        "enabled": True,
        "glyph": "\U000f0318 ",  # nf-md-checkbox_marked_circle
        "color": "#67e8f9",
        "bg": "#2e3440",
    },
    "obs_subagents": {
        "enabled": True,
        "glyph": "\U000f0026 ",  # nf-md-account_multiple
        "color": "#c4b5fd",
        "bg": "#2e3440",
    },
    # --- Obs: Health group ---
    "obs_failures": {
        "enabled": False,
        "glyph": "\U000f0029 ",  # nf-md-alert
        "color": "#fda4af",
        "bg": "#2e3440",
        "warn_threshold": 1,
        "critical_threshold": 5,
        "warn_color": "#f0d399",
        "critical_color": "#d06070",
    },
    "obs_compactions": {
        "enabled": True,
        "glyph": "\U000f0520 ",  # nf-md-timer (compactions)
        "color": "#a8a29e",
        "bg": "#2e3440",
    },
    "obs_health": {
        "enabled": True,
        "glyph": "\U000f0565 ",  # nf-md-shield_check
        "color": "#86efac",
        "bg": "#2e3440",
        "degraded_color": "#f0d399",
        "failed_color": "#d06070",
    },
    "obs_hook_faults": {
        "enabled": True,
        "glyph": "\U000f0029 ",  # nf-md-alert
        "color": "#fda4af",
        "bg": "#2e3440",
        "warn_threshold": 1,
        "critical_threshold": 5,
        "warn_color": "#f0d399",
        "critical_color": "#d06070",
    },
}


# --- Config ---

def load_config() -> dict[str, Any]:
    """Load TOML config with shallow per-section merge over defaults."""
    theme = {k: dict(v) for k, v in DEFAULT_THEME.items()}
    if tomllib is None:
        return theme
    try:
        with open(CONFIG_PATH, "rb") as f:
            user = tomllib.load(f)
        for section, defaults in theme.items():
            if section in user and isinstance(user[section], dict):
                defaults.update(user[section])
    except Exception:
        pass
    return theme


# --- ANSI Styling ---

def _parse_hex(hex_color: str) -> tuple[int, int, int] | None:
    """Parse #RRGGBB to (R, G, B) or None on failure."""
    if not isinstance(hex_color, str) or len(hex_color) != 7 or hex_color[0] != "#":
        return None
    try:
        return (int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16))
    except ValueError:
        return None


def style(text: str, hex_color: str | None = None, bold: bool = False,
          bg_color: str | None = None) -> str:
    """Wrap text in ANSI truecolor. Plain text if NO_COLOR or invalid color."""
    if NO_COLOR:
        return text
    codes: list[str] = []
    if bold:
        codes.append("1")
    if hex_color:
        rgb = _parse_hex(hex_color)
        if rgb:
            codes.append(f"38;2;{rgb[0]};{rgb[1]};{rgb[2]}")
    if bg_color:
        bg = _parse_hex(bg_color)
        if bg:
            codes.append(f"48;2;{bg[0]};{bg[1]};{bg[2]}")
    if not codes:
        return text
    # Full reset: \033[0m clears all, \033[49m explicitly clears bg
    # (Apple Terminal sometimes needs the explicit bg reset)
    reset = "\033[0m" if not bg_color else "\033[0;49m"
    return f"\033[{';'.join(codes)}m{text}{reset}"


def style_dim(text: str) -> str:
    """Apply ANSI dim attribute."""
    if NO_COLOR:
        return text
    return f"\033[2m{text}\033[0m"


_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _darken_hex(hex_color: str, factor: float = 0.55) -> str:
    """Darken a hex color by a factor (0=black, 1=unchanged)."""
    rgb = _parse_hex(hex_color)
    if not rgb:
        return hex_color
    r = int(rgb[0] * factor)
    g = int(rgb[1] * factor)
    b = int(rgb[2] * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


def _visible_len(text: str) -> int:
    """Return visible character count, stripping ANSI escape sequences."""
    return len(_ANSI_RE.sub("", text))


# --- Subprocess Helper ---

def _run_cmd(cmd: list[str], timeout: float = 0.05,
             env: dict[str, str] | None = None) -> str | None:
    """Run a command with timeout, return stdout or None on any failure."""
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=timeout, text=True, env=env,
        )
        if result.returncode != 0:
            return None
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


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
    """Create a normalized internal state from the raw payload."""
    state: dict[str, Any] = {}

    # Model name
    model = payload.get("model")
    if isinstance(model, dict):
        name = model.get("display_name")
        if isinstance(name, str) and name:
            # "Claude Opus 4.6 (1M context)" → "Opus4.6[1M]"
            if name.startswith("Claude "):
                name = name[7:]
            name = name.replace(" context)", ")")
            name = name.replace(" (", "[").replace(")", "]")
            # Remove spaces between name parts: "Opus 4.6[1M]" → "Opus4.6[1M]"
            bracket_idx = name.find("[")
            if bracket_idx >= 0:
                prefix = name[:bracket_idx].replace(" ", "")
                name = prefix + name[bracket_idx:]
            else:
                name = name.replace(" ", "")
            state["model_name"] = name
    elif isinstance(model, str) and model:
        # String model ID: "claude-opus-4-6" → "Opus4.6[1M]"
        name = model
        if name.startswith("claude-"):
            name = name[7:]
        # Strip date suffixes: "haiku-4-5-20251001" → "haiku-4-5"
        parts = name.split("-")
        clean = []
        for p in parts:
            if len(p) >= 8 and p.isdigit():
                break
            clean.append(p)
        if clean:
            clean[0] = clean[0].capitalize()
            name = clean[0]
            for i, p in enumerate(clean[1:]):
                name += p if i == 0 else f".{p}"
        # Append context window size if available: "Opus4.6[1M]"
        ctx_window = payload.get("context_window")
        if isinstance(ctx_window, dict):
            ctx_size = ctx_window.get("context_window_size")
            if isinstance(ctx_size, (int, float)) and ctx_size > 0:
                if ctx_size >= 1_000_000:
                    name += f"[{ctx_size // 1_000_000}M]"
                elif ctx_size >= 1_000:
                    name += f"[{ctx_size // 1_000}K]"
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

    # Cost fields — check both nested cost dict and top-level keys
    cost = payload.get("cost")
    if isinstance(cost, dict):
        cost_usd = cost.get("total_cost_usd")
        if isinstance(cost_usd, (int, float)):
            state["cost_usd"] = float(cost_usd)
        duration_ms = cost.get("total_duration_ms")
        if isinstance(duration_ms, (int, float)):
            state["duration_ms"] = int(duration_ms)
    # Fallback: top-level cost_usd and duration_ms (CC sends these directly)
    if "cost_usd" not in state:
        c = payload.get("cost_usd")
        if isinstance(c, (int, float)):
            state["cost_usd"] = float(c)
    if "duration_ms" not in state:
        d = payload.get("duration_ms")
        if isinstance(d, (int, float)):
            state["duration_ms"] = int(d)

    # Optional: context window
    ctx_window = payload.get("context_window")
    if isinstance(ctx_window, dict):
        # Primary: used_percentage (directly from runtime)
        used_pct = ctx_window.get("used_percentage")
        ctx_size = ctx_window.get("context_window_size")
        if isinstance(used_pct, (int, float)) and isinstance(ctx_size, (int, float)) and ctx_size > 0:
            # Synthesize used/total from percentage and size
            state["context_used"] = int(used_pct * ctx_size / 100)
            state["context_total"] = int(ctx_size)
            state["raw_used_pct"] = int(used_pct)
        else:
            # Fallback: used/total fields (older payloads, test fixtures)
            used = ctx_window.get("used")
            total = ctx_window.get("total")
            if isinstance(used, (int, float)) and isinstance(total, (int, float)) and total > 0:
                state["context_used"] = int(used)
                state["context_total"] = int(total)
        # Token counts (version-sensitive runtime fields)
        input_tok = ctx_window.get("total_input_tokens")
        output_tok = ctx_window.get("total_output_tokens")
        if isinstance(input_tok, (int, float)) and isinstance(output_tok, (int, float)):
            input_tok, output_tok = int(input_tok), int(output_tok)
            if input_tok > 0 or output_tok > 0:
                state["input_tokens"] = input_tok
                state["output_tokens"] = output_tok

        # Corrected context usage: CC's used_percentage excludes output tokens
        # (bug #28167) but the actual context limit DOES include them.
        # Only apply when used_percentage was the source (not used/total which
        # may already include output tokens in some payload versions).
        if used_pct is not None and "context_used" in state and "context_total" in state:
            out = state.get("output_tokens", 0)
            if out > 0:
                state["context_used_corrected"] = state["context_used"] + out

    # Optional: added_dirs
    added_dirs = payload.get("added_dirs")
    if isinstance(added_dirs, list):
        state["added_dirs"] = added_dirs

    # Optional: worktree
    worktree = payload.get("worktree")
    if isinstance(worktree, bool):
        state["is_worktree"] = worktree

    # Optional: current_usage (per-turn cache tokens from context_window)
    current_usage = None
    if isinstance(ctx_window, dict):
        current_usage = ctx_window.get("current_usage")
    if not isinstance(current_usage, dict):
        current_usage = payload.get("current_usage")
    if isinstance(current_usage, dict):
        state["current_usage"] = current_usage
        # Extract cache tokens for direct use (avoids transcript parsing)
        cc = current_usage.get("cache_creation_input_tokens")
        cr = current_usage.get("cache_read_input_tokens")
        if isinstance(cc, (int, float)):
            state["payload_cache_create"] = int(cc)
        if isinstance(cr, (int, float)):
            state["payload_cache_read"] = int(cr)

    # Optional: agent_id
    agent_id = payload.get("agent_id")
    if isinstance(agent_id, str) and agent_id:
        state["agent_id"] = agent_id

    # Transcript path (for overhead monitor Phase 2)
    transcript_path = payload.get("transcript_path")
    if isinstance(transcript_path, str) and transcript_path:
        state["transcript_path"] = transcript_path

    return state


# --- Renderer ---

def _sanitize_fragment(text: str) -> str:
    """Remove newlines and control characters from a fragment."""
    return text.replace("\n", " ").replace("\r", "").replace("\t", " ").strip()


def _format_cost(cost_usd: float) -> str:
    """Format cost with appropriate precision."""
    if cost_usd < 0.01:
        return f"{cost_usd:.4f}"
    return f"{cost_usd:.2f}"


def _format_duration(duration_ms: int, fmt: str = "auto") -> str:
    """Format duration in human-readable form.

    fmt options:
      "auto"  — smallest meaningful unit(s): 30s, 2m 30s, 1h 15m
      "hm"    — hours and minutes only: 0h 2m, 1h 15m
      "m"     — total minutes only: 2m, 75m
      "hms"   — hours, minutes, seconds: 0h 2m 30s, 1h 15m 0s
    """
    seconds = duration_ms // 1000
    minutes = seconds // 60
    hours = minutes // 60
    remaining_m = minutes % 60
    remaining_s = seconds % 60

    if fmt == "hms":
        return f"{hours}h {remaining_m:02d}m {remaining_s:02d}s"
    if fmt == "hm":
        return f"{hours}h {remaining_m:02d}m"
    if fmt == "m":
        return f"{minutes}m"

    # auto
    if seconds < 60:
        return f"{seconds}s"
    if minutes < 60:
        if remaining_s:
            return f"{minutes}m{remaining_s}s"
        return f"{minutes}m"
    if remaining_m:
        return f"{hours}h{remaining_m}m"
    return f"{hours}h"


def _abbreviate_count(n: int) -> str:
    """Abbreviate token counts: 1234 -> 1.2k, 1234567 -> 1.2M."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        val = n / 1000
        return f"{val:.1f}k" if val < 100 else f"{int(val)}k"
    val = n / 1_000_000
    return f"{val:.1f}M" if val < 100 else f"{int(val)}M"


def _pill(text: str, cfg: dict[str, Any], color: str | None = None,
          bold: bool = False, theme: dict[str, Any] | None = None,
          dim: bool = False) -> str:
    """Wrap text as a pill with optional background and rounded caps."""
    c = color or cfg.get("color")
    bg_hex = cfg.get("bg")
    if dim and not NO_COLOR:
        if bg_hex:
            inner = style(f" {text} ", c, bold, bg_hex)
            return f"\033[2m{inner}\033[0m"
        return style_dim(style(text, c, bold))
    if bg_hex and not NO_COLOR:
        inner = style(f" {text} ", c, bold, bg_hex)
        pill_cfg = (theme or {}).get("pill", {})
        left = pill_cfg.get("left", "")
        right = pill_cfg.get("right", "")
        if left and right:
            return style(left, bg_hex) + inner + style(right, bg_hex)
        return inner
    return style(text, c, bold)


def format_tokens(input_tokens: int, output_tokens: int, theme: dict[str, Any]) -> str:
    """Format token counts as ▲71.4k │ ▼484k."""
    text = f"\u25b2{_abbreviate_count(input_tokens)} \u2502 \u25bc{_abbreviate_count(output_tokens)}"
    tok_cfg = theme.get("tokens", {})
    return _pill(text, tok_cfg, theme=theme)


def render_bar(pct: int, theme: dict[str, Any]) -> str:
    """Render context progress bar with threshold coloring."""
    cfg = theme.get("context_bar", {})
    width = cfg.get("width", 10)
    filled = (pct * width) // 100
    bar = "\u2588" * filled + "\u2591" * (width - filled)

    warn_t = cfg.get("warn_threshold", 40.0)
    crit_t = cfg.get("critical_threshold", 70.0)

    if pct >= crit_t:
        suffix = f" {pct}%!"
        color = cfg.get("critical_color", "#bf616a")
        bold = True
    elif pct >= warn_t:
        suffix = f" {pct}%~"
        color = cfg.get("warn_color", "#ebcb8b")
        bold = False
    else:
        suffix = f" {pct}%"
        color = cfg.get("color", "#a3be8c")
        bold = False

    glyph = cfg.get("glyph", "")
    return _pill(f"{glyph}{bar}{suffix}", cfg, color, bold, theme)


# --- Module Renderers ---
# Each takes (state, theme) and returns str | None.


def render_model(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render model name module — plain text with glyph, no pill wrapper."""
    model_name = state.get("model_name")
    if not model_name:
        return None
    m_cfg = theme.get("model", {})
    glyph = m_cfg.get("glyph", "\U000f06a9 ")
    text = f"{glyph}{_sanitize_fragment(model_name)}"
    color = m_cfg.get("color", "#d8dee9")
    return style(text, color, m_cfg.get("bold", False))


def render_dir(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render directory pill (basename only, git is a separate module)."""
    dir_basename = state.get("dir_basename")
    if not dir_basename:
        return None
    d_cfg = theme.get("dir", {})
    text = _sanitize_fragment(dir_basename)
    if state.get("is_worktree"):
        marker = d_cfg.get("worktree_marker", "\u229b")
        text += marker
    glyph = d_cfg.get("glyph", "")
    is_stale = state.get("git_stale", False)
    return _pill(f"{glyph}{text}", d_cfg, theme=theme, dim=is_stale)


# ── Overhead Monitor: see src/context_overhead.py ───────────────────
# Constants and functions imported at module top via context_overhead import.


def render_context_bar(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render context health bar with severity computation.

    Renders: [bar 󰋑] [pct%]
    Also computes and stores shared severity state (_sev_color, _sev_bold,
    _cw_color) for token_in, token_out, cache_pill, and other line 2 modules.
    """
    if "context_used" not in state or "context_total" not in state:
        return None
    cfg = theme.get("context_bar", {})
    ctx_used = state.get("context_used_corrected", state["context_used"])
    ctx_total = state["context_total"]
    total_pct = (ctx_used * 100) // ctx_total if ctx_total > 0 else 0
    # CC's raw used_percentage is the authoritative source for alert decisions
    # (context_used_corrected can exceed 100% when output tokens are added).
    raw_used_pct = state.get("raw_used_pct", total_pct)
    # Cap visual percentage at 100 — bar can't overflow
    display_pct = min(total_pct, 100)
    width = cfg.get("width", 20)
    if width <= 0:
        import shutil as _shutil
        term_w = _shutil.get_terminal_size((120, 24)).columns
        width = max(10, term_w - 55)
    filled = (display_pct * width) // 100

    # Dual-bar: sys overhead vs conversation within filled portion
    has_overhead = "sys_overhead_tokens" in state
    sys_blocks = conv_blocks = 0
    raw_sys_pct = 0
    if has_overhead:
        sys_overhead = min(state["sys_overhead_tokens"], ctx_total)
        raw_sys_pct = (sys_overhead * 100) // ctx_total if ctx_total > 0 else 0
        if filled > 0 and ctx_used > 0:
            sys_ratio = min(sys_overhead / ctx_used, 1.0)
            sys_blocks = round(sys_ratio * filled) if sys_overhead > 0 else 0
            if sys_blocks == 0 and sys_overhead > 0 and filled > 0 and sys_ratio >= 0.5:
                sys_blocks = 1
            sys_blocks = min(sys_blocks, filled)
            conv_blocks = filled - sys_blocks
        free_blocks = width - filled
    else:
        sys_blocks = filled
        conv_blocks = 0
        free_blocks = width - filled

    # Severity from CC-verified autocompact threshold
    cc_compact_pct = state.get("cc_autocompact_pct")
    if cc_compact_pct:
        warn_t = round(cc_compact_pct * 0.80, 1)
        crit_t = cc_compact_pct
    else:
        warn_t = cfg.get("warn_threshold", 40.0)
        crit_t = cfg.get("critical_threshold", 70.0)
    sys_warn_t = cfg.get("sys_warn_threshold", 30.0)
    sys_crit_t = cfg.get("sys_critical_threshold", 50.0)

    total_sev = 2 if raw_used_pct >= crit_t else (1 if raw_used_pct >= warn_t else 0)
    sys_sev = 0
    if has_overhead:
        sys_sev = 2 if raw_sys_pct >= sys_crit_t else (1 if raw_sys_pct >= sys_warn_t else 0)
    sev = max(total_sev, sys_sev)

    # Cache health escalation
    source = state.get("sys_overhead_source", "")
    if source == "measured":
        if state.get("cache_busting") is True:
            sev = 2
        elif state.get("microcompact_suspected") is True:
            sev = max(sev, 1)
        elif state.get("cache_degraded") is True:
            sev = max(sev, 1)

    if sev == 2:
        color = cfg.get("critical_color", "#d06070")
        bold = True
    elif sev == 1:
        color = cfg.get("warn_color", "#f0d399")
        bold = False
    else:
        color = cfg.get("color", "#b5d4a0")
        bold = False

    glyph = cfg.get("glyph", "\U000f02d1").rstrip()  # 󰋑 heart (strip trailing space)

    # Percentage suffix
    # Show CC's raw percentage (not the corrected+capped one)
    if sev == 2:
        pct_text = f"{raw_used_pct}%!"
    elif sev == 1:
        pct_text = f"{raw_used_pct}%~"
    else:
        pct_text = f"{raw_used_pct}%"

    # ── Render as separate pills ──

    bg_hex = cfg.get("bg")
    oh_color = "#81a1c1"   # nord9 blue — system overhead
    rate_color = "#8fbcbb"  # nord7 teal — cache hit rate

    # Cache writes color by threshold
    last_cc = state.get("last_cache_create")
    cw_color = "#8fbcbb"  # default teal
    spike_t = cfg.get("spike_threshold", 5000)
    notable_t = cfg.get("notable_threshold", 1000)
    if last_cc and last_cc > spike_t:
        cw_color = "#bf616a"  # nord11 red
    elif last_cc and last_cc > notable_t:
        cw_color = "#ebcb8b"  # nord13 yellow

    # Store shared state for line 2 renderers
    state["_sev"] = sev
    state["_sev_color"] = color
    state["_sev_bold"] = bold
    state["_cw_color"] = cw_color

    # ── Alert detection (runs before color/no-color split) ──
    alert_color_hex = "#bf616a"   # nord11 red
    warn_color_hex = "#ebcb8b"    # nord13 yellow
    tuc = state.get("turns_until_compact")

    # (glyph, is_critical, "TITLE — inline description")
    _ALERT_DEFS = {
        "bust":     ("\U000f04bf", True,  "CACHE BUSTED \u2014 cache miss on every turn, 10-20x token cost until session restart"),
        "expired":  ("\U000f0150", False, "CACHE EXPIRED \u2014 idle timeout, rebuilds automatically on next turn"),
        "micro":    ("\U000f0456", False, "MICRO COMPACT \u2014 old tool results silently cleared, earlier file reads lost from context"),
        "bloat":    ("\U000f0cf2", True,  "SYSTEM BLOAT \u2014 system overhead consuming >50% of context window, reduce plugins or MCP servers"),
        "heavy":    ("\U000f02d1", True,  "HEAVY CONTEXT \u2014 approaching autocompact threshold, conversation will be summarized soon"),
        "compact":  ("\U000f0520", True,  None),  # dynamic
        "turns":    ("\U000f0520", False, None),   # dynamic
        "degraded": ("\U000f04c5", False, "CACHE DEGRADED \u2014 partial cache misses each turn, token efficiency reduced"),
    }

    alert_key = None
    if state.get("cache_busting") is True:
        alert_key = "bust"
    elif state.get("cache_expired") is True:
        alert_key = "expired"
    elif state.get("microcompact_suspected") is True:
        alert_key = "micro"
    elif has_overhead and raw_sys_pct >= sys_crit_t:
        alert_key = "bloat"
    elif raw_used_pct >= crit_t:
        alert_key = "heavy"
    elif tuc is not None and 0 < tuc <= 10:
        alert_key = "compact"
    elif tuc is not None and 0 < tuc <= 50:
        alert_key = "turns"
    elif state.get("cache_degraded") is True:
        alert_key = "degraded"

    # Track onset via disk file (script runs once per CC call, no in-memory state)
    _ALERT_FILE = "/tmp/qline-alert.json"
    alert_glyph_str = None
    alert_crit = False
    _sid = state.get("_session_id", "")

    def _load_alert():
        try:
            with open(_ALERT_FILE) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_alert(d):
        try:
            with open(_ALERT_FILE, "w") as f:
                json.dump(d, f)
        except Exception:
            pass

    if alert_key:
        now = time.time()
        persisted = _load_alert()
        # Treat stale session alert as new: different session_id means a new CC
        # process has started; the old onset time is irrelevant.
        if _sid and persisted.get("session_id", "") != _sid:
            persisted = {}
        if alert_key != persisted.get("key"):
            persisted = {"key": alert_key, "onset": now, "session_id": _sid}
            _save_alert(persisted)
        elapsed = now - persisted.get("onset", now)
        gdef = _ALERT_DEFS.get(alert_key, _ALERT_DEFS["degraded"])
        alert_glyph_str, alert_crit = gdef[0], gdef[1]

        if elapsed < 5.0:
            if alert_key == "compact":
                msg = f"COMPACT IN ~{tuc} TURNS \u2014 autocompact imminent, context will be summarized"
            elif alert_key == "turns":
                msg = f"~{tuc} TURNS LEFT \u2014 approaching autocompact threshold"
            else:
                msg = gdef[2]
            state["_alert_banner"] = f"{alert_glyph_str} {msg}"
    else:
        _save_alert({})

    if not NO_COLOR:
        pills = []
        sys_color_hex = color                    # bright — system overhead stands out
        conv_color_hex = _darken_hex(color, 0.55)  # dimmed — conversation content
        free_color_hex = "#4c566a"

        def _mkpill(text, c, bg=bg_hex, b=False):
            return style(text, c, b, bg)

        def _flash(text, c, critical=False):
            """Alert styling — visible in ALL terminals including Apple Terminal.

            SGR 5 blink only works in iTerm2/kitty/WezTerm. Apple Terminal
            ignores it. So we use reverse video (SGR 7) as the primary
            attention-getter — it works everywhere and is highly visible.
            SGR 5 is added as a bonus for terminals that support it.

            Critical: reverse + bold + blink (white-on-color box).
            Warn: bold + underline + blink (colored + underlined).
            """
            if NO_COLOR:
                return text
            rgb = _parse_hex(c)
            if not rgb:
                return text
            cc = f"38;2;{rgb[0]};{rgb[1]};{rgb[2]}"
            if critical:
                # Reverse video: renders as bright bg block — visible everywhere
                return f"\033[7;1;5;{cc}m {text} \033[0m"
            else:
                # Bold + underline: visible in Apple Terminal without blink
                return f"\033[1;4;5;{cc}m{text}\033[0m"

        # Inline alert glyph (flashing)
        if alert_glyph_str:
            ac = alert_color_hex if alert_crit else warn_color_hex
            pills.append(_flash(alert_glyph_str, ac, critical=alert_crit))
            # Colorize the banner too
            if "_alert_banner" in state:
                state["_alert_banner"] = _flash(state["_alert_banner"], ac, critical=alert_crit)
        # bar (no brackets): █▓░ 󰋑pct%
        bar_styled = ""
        if sys_blocks > 0:
            bar_styled += style("\u2588" * sys_blocks, sys_color_hex, bg_color=bg_hex)
        if conv_blocks > 0:
            bar_styled += style("\u2593" * conv_blocks, conv_color_hex, bg_color=bg_hex)
        if free_blocks > 0:
            bar_styled += style("\u2591" * free_blocks, free_color_hex, bg_color=bg_hex)
        pills.append(bar_styled)
        # 󰋑pct% — glyph directly before percentage, no spaces
        pills.append(_mkpill(f"{glyph}{pct_text}", color, b=bold))

        sep = style(" ", "#4c566a", bg_color=bg_hex)
        return sep.join(pills)

    # NO_COLOR fallback — no brackets, 󰋑pct% suffix, tight (no spaces)
    bar = "\u2588" * sys_blocks + "\u2593" * conv_blocks + "\u2591" * free_blocks
    parts = []
    if alert_glyph_str:
        parts.append(f"\u26a0")
    parts.append(f"{bar}{glyph}{pct_text}")
    return "".join(parts)


def render_tokens(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Legacy stub — tokens now rendered by token_counts/token_out_counts."""
    return None


def render_sys_overhead(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Legacy stub — overhead now rendered by sys_overhead_pill."""
    return None


def render_sys_overhead_pill(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render standalone system overhead: 󰑖17.1k™."""
    if "sys_overhead_tokens" not in state:
        return None
    cfg = theme.get("sys_overhead", {})
    color = cfg.get("color", "#81a1c1")
    glyph = cfg.get("glyph", "\U000f0456").rstrip()
    source = state.get("sys_overhead_source", "")
    suffix = "\u2248" if source == "estimated" else ""
    text = f"{glyph}{_abbreviate_count(state['sys_overhead_tokens'])}{suffix}\u2122"
    return _pill(text, cfg, color, theme=theme)


def render_token_counts(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render input token count only: ▲71.4k (output rendered separately)."""
    if "input_tokens" not in state or state["input_tokens"] <= 0:
        return None
    cfg = theme.get("tokens", {})
    color = state.get("_sev_color", cfg.get("color", "#a8d4d0"))
    bold = state.get("_sev_bold", False)
    return _pill(f"\u25b2{_abbreviate_count(state['input_tokens'])}", cfg, color, bold, theme)


def render_token_out_counts(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render output token count: ▼484k."""
    if "output_tokens" not in state or state["output_tokens"] <= 0:
        return None
    cfg = theme.get("tokens", {})
    color = state.get("_sev_color", cfg.get("color", "#a8d4d0"))
    bold = state.get("_sev_bold", False)
    return _pill(f"\u25bc{_abbreviate_count(state['output_tokens'])}", cfg, color, bold, theme)


def render_token_in(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Legacy alias for render_token_counts (layout compat)."""
    return render_token_counts(state, theme)


def render_token_out(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Legacy alias for render_token_out_counts (layout compat)."""
    return render_token_out_counts(state, theme)


def render_cache_pill(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Legacy stub — cache now rendered by cache_read + cache_delta."""
    return None


def render_cache_read(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render cache read: ©307k™."""
    last_cr = state.get("last_cache_read")
    if not last_cr or last_cr <= 0:
        return None
    cfg = theme.get("cache_writes", {})
    bg_hex = cfg.get("bg")
    if NO_COLOR:
        return f"\u00a9{_abbreviate_count(last_cr)}\u2122"
    return style(f"\u00a9{_abbreviate_count(last_cr)}\u2122", "#b48ead", bg_color=bg_hex)


def render_cache_delta(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render cache delta: 󰍻 +454™."""
    last_cc = state.get("last_cache_create")
    if not last_cc or last_cc <= 0:
        return None
    cfg = theme.get("cache_writes", {})
    bg_hex = cfg.get("bg")
    cw_color = state.get("_cw_color", "#8fbcbb")
    if NO_COLOR:
        return f"\U000f037b +{_abbreviate_count(last_cc)}\u2122"
    return style(f"\U000f037b +{_abbreviate_count(last_cc)}\u2122", cw_color, bg_color=bg_hex)


def render_cache_rate(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render cache hit rate: 󰓅99%."""
    hit_rate = state.get("cache_hit_rate")
    if hit_rate is None:
        # Also check integer percentage form
        hit_rate_int = state.get("cache_hit_rate_pct")
        if isinstance(hit_rate_int, (int, float)) and hit_rate_int > 0:
            cfg = theme.get("context_bar", {})
            rate_color = "#8fbcbb"  # nord7 teal
            return _pill(f"\U000f04c5{int(hit_rate_int)}%", cfg, rate_color, theme=theme)
        return None
    if not isinstance(hit_rate, (int, float)):
        return None
    rate_pct = int(hit_rate * 100) if hit_rate <= 1.0 else int(hit_rate)
    if rate_pct <= 0:
        return None
    cfg = theme.get("context_bar", {})
    rate_color = "#8fbcbb"  # nord7 teal
    return _pill(f"\U000f04c5{rate_pct}%", cfg, rate_color, theme=theme)


def render_turns_pill(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render turns-until-compact pill: [󰔠 ~N]."""
    tuc = state.get("turns_until_compact")
    if tuc is None or tuc <= 0:
        return None
    cfg = theme.get("context_bar", {})
    tuc_color = "#a3be8c" if tuc > 50 else ("#ebcb8b" if tuc > 10 else "#bf616a")
    return _pill(f"\U000f0520 ~{tuc}", cfg, tuc_color, theme=theme)


def render_cost(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render cost module: total + $/hr rate."""
    if "cost_usd" not in state:
        return None
    c_cfg = theme.get("cost", {})
    cost_val = state["cost_usd"]
    glyph = c_cfg.get("glyph", "$")

    # Compute $/hr from total cost and duration
    dur_ms = state.get("duration_ms", 0)
    rate_str = ""
    if dur_ms > 60000 and cost_val > 0:  # need at least 1 min for meaningful rate
        hours = dur_ms / 3_600_000
        rate = cost_val / hours
        rate_str = f"|{_format_cost(rate)}/hr"

    cost_text = f"{glyph}{_format_cost(cost_val)}{rate_str}"
    warn_t = c_cfg.get("warn_threshold", 2.0)
    crit_t = c_cfg.get("critical_threshold", 5.0)
    if cost_val >= crit_t:
        return _pill(cost_text, c_cfg, c_cfg.get("critical_color", "#bf616a"), True, theme)
    if cost_val >= warn_t:
        return _pill(cost_text, c_cfg, c_cfg.get("warn_color", "#ebcb8b"), theme=theme)
    return _pill(cost_text, c_cfg, theme=theme)


def render_duration(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render duration module — compact: 󰥔3h30m, 󰥔45s, 󰥔2m30s."""
    if "duration_ms" not in state:
        return None
    dur_cfg = theme.get("duration", {})
    fmt = dur_cfg.get("format", "auto")
    glyph = dur_cfg.get("glyph", "\U000f0954").rstrip()
    text = f"{glyph}{_format_duration(state['duration_ms'], fmt)}"
    return _pill(text, dur_cfg, theme=theme)


# --- System Collectors ---


def _collect_cpu_proc(state: dict[str, Any]) -> bool:
    """Linux/WSL: CPU load from /proc/loadavg."""
    try:
        with open(os.path.join(PROC_DIR, "loadavg")) as f:
            content = f.read()
        if not content.strip():
            return False
        load1 = float(content.split()[0])
        cpus = os.cpu_count()
        if cpus is None or cpus <= 0:
            return False
        pct = int((load1 / cpus) * 100)
        state["cpu_percent"] = max(0, min(999, pct))
        return True
    except Exception:
        return False


def _collect_cpu_sysctl(state: dict[str, Any]) -> bool:
    """macOS: CPU load from sysctl."""
    try:
        import subprocess
        out = subprocess.check_output(
            ["sysctl", "-n", "vm.loadavg"], timeout=1, stderr=subprocess.DEVNULL
        ).decode().strip()
        # Output: "{ 1.23 1.45 1.67 }"
        parts = out.strip("{ }").split()
        if not parts:
            return False
        load1 = float(parts[0])
        cpus = os.cpu_count()
        if cpus is None or cpus <= 0:
            return False
        pct = int((load1 / cpus) * 100)
        state["cpu_percent"] = max(0, min(999, pct))
        return True
    except Exception:
        return False


def collect_cpu(state: dict[str, Any]) -> None:
    """Collect CPU load — /proc on Linux/WSL, sysctl on macOS."""
    if not _collect_cpu_proc(state):
        # Only use macOS fallback when /proc is genuinely unavailable
        # (not when tests override PROC_DIR to a fake path)
        if PROC_DIR == "/proc":
            _collect_cpu_sysctl(state)


def _collect_memory_proc(state: dict[str, Any]) -> bool:
    """Linux/WSL: memory from /proc/meminfo."""
    try:
        with open(os.path.join(PROC_DIR, "meminfo")) as f:
            content = f.read()
        if not content.strip():
            return False
        fields: dict[str, int] = {}
        for line in content.splitlines():
            parts = line.split(":")
            if len(parts) != 2:
                continue
            key = parts[0].strip()
            val_parts = parts[1].strip().split()
            if not val_parts:
                continue
            try:
                fields[key] = int(val_parts[0])
            except ValueError:
                continue
        if "MemTotal" not in fields or fields["MemTotal"] <= 0:
            return False
        total = fields["MemTotal"]
        if "MemAvailable" in fields:
            available = fields["MemAvailable"]
        elif "MemFree" in fields:
            available = fields["MemFree"] + fields.get("Buffers", 0) + fields.get("Cached", 0)
        else:
            return False
        used = total - available
        pct = (used * 100) // total
        state["memory_percent"] = max(0, min(100, pct))
        return True
    except Exception:
        return False


def _collect_memory_sysctl(state: dict[str, Any]) -> bool:
    """macOS: memory from vm_stat + sysctl."""
    try:
        import subprocess
        # Total memory
        total_bytes = int(subprocess.check_output(
            ["sysctl", "-n", "hw.memsize"], timeout=1, stderr=subprocess.DEVNULL
        ).decode().strip())
        # Page size and usage from vm_stat
        vm = subprocess.check_output(
            ["vm_stat"], timeout=1, stderr=subprocess.DEVNULL
        ).decode()
        pages: dict[str, int] = {}
        for line in vm.splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            v = v.strip().rstrip(".")
            try:
                pages[k.strip()] = int(v)
            except ValueError:
                continue
        page_size = 16384  # default on Apple Silicon
        for line in vm.splitlines():
            if "page size" in line.lower():
                try:
                    page_size = int("".join(c for c in line if c.isdigit()))
                except ValueError:
                    pass
                break
        free = pages.get("Pages free", 0)
        inactive = pages.get("Pages inactive", 0)
        speculative = pages.get("Pages speculative", 0)
        available_bytes = (free + inactive + speculative) * page_size
        used_bytes = total_bytes - available_bytes
        pct = (used_bytes * 100) // total_bytes if total_bytes > 0 else 0
        state["memory_percent"] = max(0, min(100, pct))
        return True
    except Exception:
        return False


def collect_memory(state: dict[str, Any]) -> None:
    """Collect memory usage — /proc on Linux/WSL, vm_stat on macOS."""
    if not _collect_memory_proc(state):
        if PROC_DIR == "/proc":
            _collect_memory_sysctl(state)


def collect_disk(state: dict[str, Any]) -> None:
    """Collect disk usage percentage via os.statvfs."""
    try:
        path = getattr(collect_disk, "_path", "/")
        st = os.statvfs(path)
        total = st.f_blocks * st.f_frsize
        available = st.f_bavail * st.f_frsize
        if total <= 0:
            return
        used = total - available
        pct = (used * 100) // total
        state["disk_percent"] = max(0, min(100, pct))
    except Exception:
        return


# --- Subprocess-based collectors ---


def collect_git(state: dict[str, Any]) -> None:
    """Collect git branch, SHA, and dirty status."""
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    sha_out = _run_cmd(["git", "rev-parse", "--short", "HEAD"], timeout=0.025, env=env)
    if sha_out is None:
        check = _run_cmd(["git", "rev-parse", "--git-dir"], timeout=0.025, env=env)
        if check is not None:
            state["git_branch"] = "init"
        return
    sha = sha_out.strip()
    state["git_sha"] = sha
    status_out = _run_cmd(["git", "status", "--porcelain", "--branch"], timeout=0.025, env=env)
    if status_out is None:
        state["git_branch"] = "HEAD"
        state["git_dirty"] = False
        return
    lines = status_out.splitlines()
    branch = "HEAD"
    if lines and lines[0].startswith("## "):
        branch_part = lines[0][3:].split("...")[0]
        if "HEAD (no branch)" in branch_part or "No commits yet" in branch_part:
            branch = "HEAD" if "no branch" in branch_part else "init"
        else:
            branch = branch_part
    if len(branch) > 20:
        branch = branch[:19] + "\u2026"
    state["git_branch"] = branch
    state["git_dirty"] = len(lines) > 1


def collect_agents(state: dict[str, Any]) -> None:
    """Count running Codex instances via pgrep."""
    count = 0
    codex_out = _run_cmd(["pgrep", "-x", "codex"], timeout=0.05)
    if codex_out:
        codex_lines = [l for l in codex_out.splitlines() if l.strip()]
        count += len(codex_lines)
    if count > 0:
        state["agent_count"] = count


def collect_tmux(state: dict[str, Any]) -> None:
    """Collect tmux session and pane counts."""
    sessions_out = _run_cmd(["tmux", "list-sessions"], timeout=0.025)
    if sessions_out is None:
        return
    session_lines = [l for l in sessions_out.splitlines() if l.strip()]
    if not session_lines:
        return
    state["tmux_sessions"] = len(session_lines)
    panes_out = _run_cmd(["tmux", "list-panes", "-a"], timeout=0.025)
    if panes_out is not None:
        pane_lines = [l for l in panes_out.splitlines() if l.strip()]
        state["tmux_panes"] = len(pane_lines)
    else:
        state["tmux_panes"] = 0


# --- Cache Layer ---


def load_cache() -> dict[str, Any]:
    """Load cache file, return empty dict on any failure."""
    try:
        with open(CACHE_PATH) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        if data.get("version") != CACHE_VERSION:
            return {}
        return data.get("modules", {})
    except Exception:
        return {}


def save_cache(cache: dict[str, Any]) -> None:
    """Atomically save cache to disk. Silent on failure."""
    try:
        data = {"version": CACHE_VERSION, "modules": cache}
        fd = tempfile.NamedTemporaryFile(
            mode="w", dir="/tmp", prefix="qline-", suffix=".tmp", delete=False,
        )
        try:
            json.dump(data, fd)
            fd.flush()
            os.fsync(fd.fileno())
            fd.close()
            os.rename(fd.name, CACHE_PATH)
        except Exception:
            fd.close()
            try:
                os.unlink(fd.name)
            except OSError:
                pass
    except Exception:
        pass


_CACHE_KEYS: dict[str, list[str]] = {
    "git": ["git_branch", "git_sha", "git_dirty"],
    "cpu": ["cpu_percent"],
    "memory": ["memory_percent"],
    "disk": ["disk_percent"],
    "agents": ["agent_count"],
    "tmux": ["tmux_sessions", "tmux_panes"],
}


def _cache_module(cache: dict, state: dict, name: str, now: float) -> None:
    """Save module data to cache dict."""
    keys = _CACHE_KEYS.get(name, [])
    values = {k: state[k] for k in keys if k in state}
    if values:
        cache[name] = {"value": values, "timestamp": now}


def _apply_cached(state: dict, cache: dict, name: str, now: float) -> None:
    """Apply cached data if fresh enough, marking as stale."""
    entry = cache.get(name)
    if not isinstance(entry, dict):
        return
    ts = entry.get("timestamp", 0)
    if now - ts > CACHE_MAX_AGE_S:
        return
    values = entry.get("value", {})
    if isinstance(values, dict):
        state.update(values)
        state[f"{name}_stale"] = True


# --- System Data Orchestrator ---


def collect_system_data(state: dict[str, Any], theme: dict[str, Any]) -> None:
    """Run all enabled system collectors with cache fallback.

    Respects QLINE_NO_COLLECT=1 to skip all collection (testing/CI).
    """
    if os.environ.get("QLINE_NO_COLLECT") == "1":
        return
    cache = load_cache()
    now = time.time()
    new_cache: dict[str, Any] = {}

    # Preserve obs namespace across cache rebuilds
    if "_obs" in cache:
        new_cache["_obs"] = cache["_obs"]

    collectors = [
        ("git", collect_git),
        ("cpu", collect_cpu),
        ("memory", collect_memory),
        ("disk", collect_disk),
        ("agents", collect_agents),
        ("tmux", collect_tmux),
    ]

    for name, fn in collectors:
        cfg = theme.get(name, {})
        if not cfg.get("enabled", True):
            continue
        if name == "disk":
            collect_disk._path = cfg.get("path", "/")
        try:
            fn(state)
            _cache_module(new_cache, state, name, now)
        except Exception:
            _apply_cached(state, cache, name, now)

    save_cache(new_cache)


# --- Module Renderers (system) ---


def _render_system_metric(state: dict[str, Any], theme: dict[str, Any],
                          state_key: str, theme_key: str,
                          compact_label: str = "") -> str | None:
    """Shared renderer for system metric modules (cpu, memory, disk).

    Renders a mini progress bar with percentage, e.g. '󰓬 ███░░ 64%'
    """
    if state_key not in state:
        return None
    cfg = theme.get(theme_key, {})
    pct = state[state_key]
    show_t = cfg.get("show_threshold", 0)
    if pct < show_t:
        return None
    warn_t = cfg.get("warn_threshold", 60.0)
    crit_t = cfg.get("critical_threshold", 85.0)

    # Mini progress bar
    width = cfg.get("width", 5)
    filled = (pct * width) // 100
    bar = "\u2588" * filled + "\u2591" * (width - filled)

    if state.get("_compact") and compact_label:
        text = f"{compact_label}{bar}{pct}%"
    else:
        glyph = cfg.get("glyph", "")
        # Preserve trailing space in glyph (e.g. "󰓌 " → "󰓌 ░░░7%")
        text = f"{glyph}{bar}{pct}%"

    is_stale = state.get(f"{theme_key}_stale", False)
    if pct >= crit_t:
        return _pill(text, cfg, cfg.get("critical_color", "#d06070"), True, theme, dim=is_stale)
    if pct >= warn_t:
        return _pill(text, cfg, cfg.get("warn_color", "#f0d399"), theme=theme, dim=is_stale)
    return _pill(text, cfg, theme=theme, dim=is_stale)


# --- Subprocess-based module renderers ---


def render_git(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render git branch@sha with dirty marker."""
    if "git_branch" not in state:
        return None
    g_cfg = theme.get("git", {})
    branch = state["git_branch"]
    max_len = 12 if state.get("_compact") else 20
    if len(branch) > max_len:
        branch = branch[:max_len - 1] + "\u2026"
    dirty = state.get("git_dirty", False)
    dirty_marker = g_cfg.get("dirty_marker", "*") if dirty else ""
    sha = state.get("git_sha", "")
    if sha:
        text = f"{branch}@{sha}{dirty_marker}"
    else:
        text = f"{branch}{dirty_marker}"
    is_stale = state.get("git_stale", False)
    return _pill(text, g_cfg, theme=theme, dim=is_stale)


def render_cpu(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render CPU usage module."""
    return _render_system_metric(state, theme, "cpu_percent", "cpu", compact_label="C:")


def render_memory(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render memory usage module."""
    return _render_system_metric(state, theme, "memory_percent", "memory", compact_label="M:")


def render_disk(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render disk usage module."""
    return _render_system_metric(state, theme, "disk_percent", "disk", compact_label="D:")


def render_agents(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render active agents count module."""
    if "agent_count" not in state or state["agent_count"] <= 0:
        return None
    cfg = theme.get("agents", {})
    count = state["agent_count"]
    show_t = cfg.get("show_threshold", 0)
    if count <= show_t:
        return None
    text = f"{cfg.get('glyph', '')}{count}"
    warn_t = cfg.get("warn_threshold", 5)
    crit_t = cfg.get("critical_threshold", 8)
    is_stale = state.get("agents_stale", False)
    if count >= crit_t:
        return _pill(text, cfg, cfg.get("critical_color", "#d06070"), True, theme, dim=is_stale)
    elif count >= warn_t:
        return _pill(text, cfg, cfg.get("warn_color", "#f0d399"), theme=theme, dim=is_stale)
    return _pill(text, cfg, theme=theme, dim=is_stale)


def render_tmux(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render tmux session info module."""
    if "tmux_sessions" not in state or state["tmux_sessions"] <= 0:
        return None
    cfg = theme.get("tmux", {})
    sessions = state["tmux_sessions"]
    panes = state.get("tmux_panes", 0)
    if panes > 0:
        text = f"{cfg.get('glyph', 'tmux ')}{sessions}s/{panes}p"
    else:
        text = f"{cfg.get('glyph', 'tmux ')}{sessions}s"
    is_stale = state.get("tmux_stale", False)
    return _pill(text, cfg, theme=theme, dim=is_stale)


# --- Observability Module Renderers ---


def _render_obs_counter(
    state: dict[str, Any],
    theme: dict[str, Any],
    state_key: str,
    theme_key: str,
    *,
    default_glyph: str = "",
    prefix: str = "",
    display_key: str | None = None,
    suffix: str = "",
) -> str | None:
    """Data-driven obs counter renderer."""
    n = state.get(state_key)
    if not n:
        return None
    cfg = theme.get(theme_key, {})
    glyph = cfg.get("glyph", default_glyph).rstrip()
    display = state.get(display_key, n) if display_key else n
    text = f"{glyph}{prefix}{display}{suffix}"
    crit_t = cfg.get("critical_threshold")
    warn_t = cfg.get("warn_threshold")
    if crit_t is not None and n >= crit_t:
        return _pill(text, cfg, cfg.get("critical_color", "#d06070"), True, theme)
    if warn_t is not None and n >= warn_t:
        return _pill(text, cfg, cfg.get("warn_color", "#f0d399"), theme=theme)
    return _pill(text, cfg, theme=theme)


def render_obs_reads(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    return _render_obs_counter(state, theme, "obs_reads", "obs_reads", default_glyph="\U000f0447")


def render_obs_rereads(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    rr = state.get("obs_reread_count")
    if not rr:
        return None
    cfg = theme.get("obs_rereads", {})
    re_pct = state.get("obs_reread_pct", 0)
    glyph = cfg.get("glyph", "\u00ae ").rstrip()  # ® registered sign
    text = f"{glyph}{re_pct}%"
    crit_t = cfg.get("critical_threshold", 50)
    warn_t = cfg.get("warn_threshold", 30)
    if re_pct >= crit_t:
        return _pill(text, cfg, cfg.get("critical_color", "#d06070"), True, theme)
    if re_pct >= warn_t:
        return _pill(text, cfg, cfg.get("warn_color", "#f0d399"), theme=theme)
    return _pill(text, cfg, theme=theme)


def render_obs_writes(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    return _render_obs_counter(state, theme, "obs_writes", "obs_writes", default_glyph="\U000f064f")


def render_obs_bash(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    return _render_obs_counter(state, theme, "obs_bash", "obs_bash", default_glyph="\U000f018d")


def render_obs_failures(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    return _render_obs_counter(state, theme, "obs_failures", "obs_failures", default_glyph="\U000f0029 ")


def render_obs_subagents(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    return _render_obs_counter(state, theme, "obs_subagents", "obs_subagents", default_glyph="\U000f0026")


def render_obs_tasks(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    return _render_obs_counter(state, theme, "obs_tasks", "obs_tasks", default_glyph="\U000f0318")


def render_obs_compactions(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    return _render_obs_counter(state, theme, "obs_compactions", "obs_compactions", default_glyph="\U000f0520", prefix="x")


def render_obs_prompts(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    return _render_obs_counter(state, theme, "obs_prompts", "obs_prompts", default_glyph="\U000f017a")


def render_obs_hook_faults(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render hook fault count from the lifecycle fault ledger (last hour).

    Warn at 1 fault, critical at 5 — hook crashes are always notable.
    """
    return _render_obs_counter(
        state, theme, "obs_hook_faults", "obs_hook_faults",
        default_glyph="\U000f0029 ", suffix="",
    )


def render_turns(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render session turn count: 󰐕475."""
    n = state.get("session_turn_count")
    if not n or n <= 0:
        return None
    cfg = theme.get("tokens", {})
    return _pill(f"\U000f0415{n}", cfg, theme=theme)


def render_obs_health(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    h = state.get("obs_health")
    cfg = theme.get("obs_health", {})
    if not h or h == "unknown":
        # Show dimmed indicator only if we have a session (obs is expected)
        if state.get("_has_session_id"):
            return _pill(f"\U000f0565 \u2015", cfg, theme=theme, dim=True)
        return None
    glyph = cfg.get("glyph", "\U000f0565 ")  # nf-md-shield_check
    if h == "healthy":
        return _pill(glyph.rstrip(), cfg, cfg.get("color", "#86efac"), theme=theme)
    if h == "degraded":
        return _pill(glyph.rstrip(), cfg, cfg.get("degraded_color", "#f0d399"), True, theme)
    return _pill(glyph.rstrip(), cfg, cfg.get("failed_color", "#d06070"), True, theme)


MODULE_RENDERERS: dict[str, Any] = {
    "model": render_model,
    "dir": render_dir,
    "context_bar": render_context_bar,
    "tokens": render_tokens,
    "sys_overhead": render_sys_overhead,
    "sys_overhead_pill": render_sys_overhead_pill,
    "token_counts": render_token_counts,
    "token_out_counts": render_token_out_counts,
    "token_in": render_token_in,
    "token_out": render_token_out,
    "cache_pill": render_cache_pill,
    "cache_read": render_cache_read,
    "cache_delta": render_cache_delta,
    "cache_rate": render_cache_rate,
    "turns_pill": render_turns_pill,
    "cache_writes": render_cache_delta,
    "cost": render_cost,
    "duration": render_duration,
    "git": render_git,
    "cpu": render_cpu,
    "memory": render_memory,
    "disk": render_disk,
    "agents": render_agents,
    "tmux": render_tmux,
    "obs_reads": render_obs_reads,
    "obs_rereads": render_obs_rereads,
    "obs_writes": render_obs_writes,
    "obs_bash": render_obs_bash,
    "obs_failures": render_obs_failures,
    "obs_subagents": render_obs_subagents,
    "obs_tasks": render_obs_tasks,
    "obs_compactions": render_obs_compactions,
    "obs_prompts": render_obs_prompts,
    "obs_health": render_obs_health,
    "obs_hook_faults": render_obs_hook_faults,
    "turns": render_turns,
}

DEFAULT_LINE1 = ["model", "token_counts", "token_out_counts", "context_bar",
                 "cache_rate", "duration"]
DEFAULT_LINE2 = ["sys_overhead_pill", "cache_read", "cache_delta",
                 "turns", "obs_reads", "obs_rereads", "obs_writes",
                 "obs_bash", "obs_failures", "obs_prompts", "obs_tasks",
                 "obs_subagents", "obs_health", "obs_compactions",
                 "obs_hook_faults", "cost"]
DEFAULT_LINE3 = ["dir", "git", "cpu", "memory", "disk"]

# PIPE separator positions on line 2 (module names after which a PIPE | is used
# instead of BOX │).  Only two: after cache_read and within cost (handled by
# the cost renderer itself).
LINE2_PIPE_AFTER = {"cache_read"}


def render_line(state: dict[str, Any], theme: dict[str, Any],
                modules: list[str], sep_override: str | None = None) -> str:
    """Render a single line from a list of module names.

    Iterates modules, looks up each in MODULE_RENDERERS, skips unknown
    or disabled modules, calls each renderer, collects non-None results,
    and joins with the theme separator.
    """
    parts: list[str] = []
    if sep_override is not None:
        sep = sep_override
    else:
        sep_cfg = theme.get("separator", {})
        sep_char = sep_cfg.get("char", "\u2502")
        sep_dim = sep_cfg.get("dim", True)
        sep = style_dim(sep_char) if sep_dim else sep_char

    for name in modules:
        renderer = MODULE_RENDERERS.get(name)
        if renderer is None:
            continue
        mod_cfg = theme.get(name, {})
        if not mod_cfg.get("enabled", True):
            continue
        result = renderer(state, theme)
        if result is not None:
            parts.append(result)

    if not parts:
        return ""
    return sep.join(parts)


def _render_wrapped(state: dict[str, Any], theme: dict[str, Any],
                    modules: list[str], sep_override: str | None = None) -> str:
    """Render modules into auto-wrapped rows that fit terminal width."""
    if sep_override is not None:
        sep = sep_override
    else:
        sep_cfg = theme.get("separator", {})
        sep_char = sep_cfg.get("char", "\u2502")
        sep_dim = sep_cfg.get("dim", True)
        sep = style_dim(sep_char) if sep_dim else sep_char
    sep_width = _visible_len(sep)

    # Render all modules, keep only non-None results
    parts: list[str] = []
    for name in modules:
        renderer = MODULE_RENDERERS.get(name)
        if renderer is None:
            continue
        mod_cfg = theme.get(name, {})
        if not mod_cfg.get("enabled", True):
            continue
        result = renderer(state, theme)
        if result is not None:
            parts.append(result)

    if not parts:
        return ""

    # Get terminal width — layout.max_width overrides auto-detection
    # (Claude Code runs without a TTY, so auto-detect falls back to 80)
    layout_cfg = theme.get("layout", {})
    term_width = layout_cfg.get("max_width") or shutil.get_terminal_size((200, 24)).columns

    # Pack modules into rows
    rows: list[list[str]] = []
    current_row: list[str] = []
    current_width = 0

    for part in parts:
        part_width = _visible_len(part)
        if current_row:
            needed = sep_width + part_width
        else:
            needed = part_width

        if current_row and current_width + needed > term_width:
            rows.append(current_row)
            current_row = [part]
            current_width = part_width
        else:
            current_row.append(part)
            current_width += needed

    if current_row:
        rows.append(current_row)

    return "\n".join(sep.join(row) for row in rows)


def _render_line2_piped(state: dict[str, Any], theme: dict[str, Any],
                       modules: list[str], box_sep: str) -> str:
    """Render line 2 with │ separators and PIPE | after cache_read.

    All modules joined by │ (box drawing, no spaces) except after
    cache_read which uses | (pipe, no spaces).
    """
    # Render all modules, keeping track of names for pipe-after logic
    rendered: list[tuple[str, str]] = []  # (module_name, rendered_text)
    for name in modules:
        renderer = MODULE_RENDERERS.get(name)
        if renderer is None:
            continue
        mod_cfg = theme.get(name, {})
        if not mod_cfg.get("enabled", True):
            continue
        result = renderer(state, theme)
        if result is not None:
            rendered.append((name, result))

    if not rendered:
        return ""

    # Join with appropriate separators
    pipe = style_dim("|") if not NO_COLOR else "|"
    parts = [rendered[0][1]]
    for i in range(1, len(rendered)):
        prev_name = rendered[i - 1][0]
        if prev_name in LINE2_PIPE_AFTER:
            parts.append(pipe)
        else:
            parts.append(box_sep)
        parts.append(rendered[i][1])

    return "".join(parts)


def render(state: dict[str, Any], theme: dict[str, Any] | None = None) -> str:
    """Render status output from normalized state using layout config.

    Layout lines (line1, line2, line3, ...) are rendered in order.
    Empty lines are suppressed. If force_single_line is True, all
    layout lines are merged into one (compact mode).
    """
    if theme is None:
        theme = DEFAULT_THEME

    layout = theme.get("layout", {})
    force_single = layout.get("force_single_line", False)

    # Collect all configured lines (line1, line2, line3, ...)
    has_any_line_key = any(layout.get(f"line{i}") is not None for i in range(1, 6))
    layout_lines: list[list[str]] = []
    if has_any_line_key:
        for key in ("line1", "line2", "line3", "line4", "line5"):
            modules = layout.get(key)
            if isinstance(modules, list) and modules:
                layout_lines.append(modules)
            elif modules is not None and not isinstance(modules, list):
                default = {"line1": DEFAULT_LINE1, "line2": DEFAULT_LINE2, "line3": DEFAULT_LINE3}.get(key)
                if default:
                    layout_lines.append(default)
        # If user set line keys but all were empty arrays, respect that (empty output)
    else:
        layout_lines = [DEFAULT_LINE1, DEFAULT_LINE2, DEFAULT_LINE3]

    state["_compact"] = force_single

    if force_single:
        # Compact: merge all into one auto-wrapped line
        merged: list[str] = []
        for modules in layout_lines:
            merged.extend(modules)
        return _render_wrapped(state, theme, merged)

    # Multi-line: render each layout line separately, enforce line breaks
    # All lines use │ (BOX DRAWING) with NO spaces as the default separator.
    # Line 2 uses PIPE | after specific modules (cache_read, cost rate).
    sep_cfg = theme.get("separator", {})
    sep_char = sep_cfg.get("char", "\u2502")
    sep_dim = sep_cfg.get("dim", True)
    box_sep = style_dim(sep_char) if sep_dim else sep_char

    rendered_lines: list[str] = []
    for idx, modules in enumerate(layout_lines):
        if idx == 1:
            # Line 2: custom join with PIPE after cache_read
            line = _render_line2_piped(state, theme, modules, box_sep)
        else:
            line = _render_wrapped(state, theme, modules, sep_override=box_sep)
        if line:
            rendered_lines.append(line)

    # Alert banner: when active, replace lines 2+ with the banner text.
    # Line 1 (the health bar with inline glyph) always shows.
    banner = state.get("_alert_banner")
    if banner and rendered_lines:
        return rendered_lines[0] + "\n" + banner

    return "\n".join(rendered_lines)


# --- Observability snapshot ---


def _compute_context_pct(state: dict) -> float | None:
    used = state.get("context_used")
    total = state.get("context_total")
    if isinstance(used, (int, float)) and isinstance(total, (int, float)) and total > 0:
        return round(used / total * 100, 1)
    return None


def _count_obs_events(package_root: str) -> dict[str, int]:
    """Fast line-scan of hook_events.jsonl for event type counts."""
    ledger = os.path.join(package_root, "metadata", "hook_events.jsonl")
    counts: dict[str, int] = {}
    try:
        with open(ledger) as f:
            for line in f:
                idx = line.find('"event": "')
                if idx >= 0:
                    start = idx + 10
                    end = line.find('"', start)
                    if end > start:
                        event = line[start:end]
                        counts[event] = counts.get(event, 0) + 1
    except Exception:
        pass
    return counts


def _count_rereads(package_root: str) -> tuple[int, int]:
    """Returns (total_reads, reread_count) from reads.jsonl."""
    reads_path = os.path.join(package_root, "custom", "reads.jsonl")
    total = reread = 0
    try:
        with open(reads_path) as f:
            for line in f:
                total += 1
                if '"is_reread": true' in line:
                    reread += 1
    except Exception:
        pass
    return total, reread


def _read_obs_health(package_root: str) -> str:
    """Read overall health from manifest."""
    manifest = os.path.join(package_root, "manifest.json")
    try:
        with open(manifest) as f:
            m = json.load(f)
        return m.get("health", {}).get("overall", "unknown")
    except Exception:
        return "unknown"


def _count_recent_faults(max_age_s: float = 3600) -> int:
    """Count fault-level hook fault ledger entries from the last max_age_s seconds.

    Fast reverse scan: reads last _FAULT_SCAN_BYTES of the ledger, parses JSONL
    lines, counts entries where level == 'fault' and ts is within max_age_s.
    Returns 0 on any error (never raises).
    """
    try:
        file_size = os.path.getsize(_FAULT_LEDGER_PATH)
        if file_size == 0:
            return 0
        seek_pos = max(0, file_size - _FAULT_SCAN_BYTES)
        with open(_FAULT_LEDGER_PATH, "rb") as f:
            f.seek(seek_pos)
            raw = f.read()
        # Decode and split into lines; skip partial first line if we sought mid-file
        lines = raw.decode("utf-8", errors="replace").splitlines()
        if seek_pos > 0 and lines:
            lines = lines[1:]  # discard potentially truncated first line
        cutoff = time.time() - max_age_s
        count = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if rec.get("level") != "fault":
                continue
            ts_str = rec.get("ts", "")
            if not ts_str:
                continue
            try:
                ts_val = datetime.fromisoformat(ts_str).timestamp()
                if ts_val >= cutoff:
                    count += 1
            except (ValueError, OSError):
                continue
        return count
    except Exception:
        return 0


def _count_parse_errors(package_root: str) -> int:
    """Count entries in the parse diagnostic sidecar. Returns 0 if file absent or unreadable."""
    try:
        diag_path = os.path.join(package_root, "native", "statusline", "diagnostics.jsonl")
        count = 0
        with open(diag_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    count += 1
        return count
    except Exception:
        return 0


def _inject_obs_counters(state: dict, payload: dict) -> None:
    """Inject obs event counters into state for module renderers. Never raises."""
    if not _OBS_AVAILABLE:
        return
    try:
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return
        state["_has_session_id"] = True

        package_root = resolve_package_root_env(session_id)
        if package_root is None:
            return

        cache = load_cache()
        obs_cache = cache.get("_obs", {})
        session_cache = obs_cache.get(session_id, {})
        now = time.time()

        # Refresh counts if stale (>5s)
        if now - session_cache.get("last_count_ts", 0) >= 5:
            event_counts = _count_obs_events(package_root)
            total_reads, reread_count = _count_rereads(package_root)
            obs_health = _read_obs_health(package_root)
            session_cache["event_counts"] = event_counts
            session_cache["total_reads"] = total_reads
            session_cache["reread_count"] = reread_count
            session_cache["obs_health"] = obs_health
            session_cache["last_count_ts"] = now
            obs_cache[session_id] = session_cache
            cache["_obs"] = obs_cache
            save_cache(cache)

        # Inject into state from cache
        ec = session_cache.get("event_counts", {})

        # Session resume detection: clear stale overhead/anchor caches
        reentry_count = ec.get("session.reentry", 0)
        if reentry_count > session_cache.get("last_known_reentry_count", 0):
            session_cache.pop("overhead_ts", None)
            session_cache.pop("turn_1_anchor", None)
            session_cache["last_known_reentry_count"] = reentry_count
            session_cache["resume_detected"] = True
            obs_cache[session_id] = session_cache
            cache["_obs"] = obs_cache
            save_cache(cache)

        # Compaction anchor invalidation: clear overhead/anchor caches when
        # a new compact.anchor_invalidated event has been emitted.
        anchor_inval_count = ec.get("compact.anchor_invalidated", 0)
        if anchor_inval_count > session_cache.get("last_known_anchor_inval_count", 0):
            session_cache.pop("overhead_ts", None)
            session_cache.pop("turn_1_anchor", None)
            session_cache["last_known_anchor_inval_count"] = anchor_inval_count
            obs_cache[session_id] = session_cache
            cache["_obs"] = obs_cache
            save_cache(cache)

        # Refresh fault count and parse errors if stale (same 5s TTL as other obs data)
        if now - session_cache.get("last_fault_ts", 0) >= 5:
            session_cache["hook_fault_count"] = _count_recent_faults()
            session_cache["parse_error_count"] = _count_parse_errors(package_root)
            session_cache["last_fault_ts"] = now
            obs_cache[session_id] = session_cache
            cache["_obs"] = obs_cache
            save_cache(cache)

        tr = session_cache.get("total_reads", 0)
        rr = session_cache.get("reread_count", 0)
        state["obs_reads"] = tr
        state["obs_reread_count"] = rr
        state["obs_reread_pct"] = round(rr / tr * 100) if tr > 0 else 0
        state["obs_writes"] = ec.get("file.write.diff", 0)
        state["obs_bash"] = ec.get("bash.executed", 0)
        state["obs_failures"] = ec.get("tool.failed", 0)
        state["obs_subagents"] = ec.get("subagent.stopped", 0)
        state["obs_tasks"] = ec.get("task.completed", 0)
        state["obs_compactions"] = ec.get("compact.started", 0)
        state["obs_prompts"] = ec.get("prompt.observed", 0)
        state["obs_health"] = session_cache.get("obs_health", "unknown")
        hook_faults = session_cache.get("hook_fault_count", 0)
        if hook_faults > 0:
            state["obs_hook_faults"] = hook_faults
        parse_errors = session_cache.get("parse_error_count", 0)
        if parse_errors > 0:
            state["obs_parse_errors"] = parse_errors
    except Exception:
        pass


def _try_obs_snapshot(payload: dict, state: dict) -> None:
    """Append status snapshot to session package. Never raises."""
    if not _OBS_AVAILABLE:
        return
    package_root = None
    try:
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return

        package_root = resolve_package_root_env(session_id)
        if package_root is None:
            return

        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "cost_usd": state.get("cost_usd"),
            "duration_ms": state.get("duration_ms"),
            "context_pct": _compute_context_pct(state),
            "context_used": state.get("context_used"),
            "context_total": state.get("context_total"),
            "input_tokens": state.get("input_tokens"),
            "output_tokens": state.get("output_tokens"),
            "model_name": state.get("model_name"),
            "dir_basename": state.get("dir_basename"),
        }

        # Throttle + dedupe via per-session qLine cache
        cache = load_cache()
        obs_cache = cache.get("_obs", {})
        session_cache = obs_cache.get(session_id, {})
        now = time.time()
        last_ts = session_cache.get("last_snapshot_ts", 0)

        # Content hash (exclude ts — it always changes)
        hash_fields = {k: v for k, v in record.items() if k != "ts"}
        content_hash = hashlib.sha256(
            json.dumps(hash_fields, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

        # Skip if under throttle AND content unchanged
        if now - last_ts < 30 and content_hash == session_cache.get("last_snapshot_hash", ""):
            return

        snapshot_path = os.path.join(
            package_root, "native", "statusline", "snapshots.jsonl"
        )
        os.makedirs(os.path.dirname(snapshot_path), exist_ok=True)
        success = _atomic_jsonl_append(snapshot_path, record)

        if success:
            update_health(package_root, "statusline_capture", "healthy")
            session_cache["last_snapshot_ts"] = now
            session_cache["last_snapshot_hash"] = content_hash
            obs_cache[session_id] = session_cache
            cache["_obs"] = obs_cache
            save_cache(cache)
        else:
            update_health(package_root, "statusline_capture", "degraded",
                         warning={"code": "STATUSLINE_APPEND_FAILED"})

    except Exception:
        try:
            if package_root:
                update_health(package_root, "statusline_capture", "degraded",
                             warning={"code": "STATUSLINE_APPEND_FAILED"})
        except Exception:
            pass


# --- Entrypoint ---

def main() -> None:
    """Status-line entrypoint. Read, normalize, collect, render, emit."""
    theme = load_config()
    payload = read_stdin_bounded()
    if payload is None:
        return
    state = normalize(payload)
    collect_system_data(state, theme)
    _inject_obs_counters(state, payload)
    _cache_ctx = {
        "load_cache": load_cache,
        "save_cache": save_cache,
        "cache_max_age": CACHE_MAX_AGE_S,
        "obs_available": _OBS_AVAILABLE,
        "resolve_package_root_env": resolve_package_root_env if _OBS_AVAILABLE else None,
    }
    inject_context_overhead(state, payload, theme, _cache_ctx)
    line = render(state, theme)
    _try_obs_snapshot(payload, state)
    if line:
        # Trailing reset prevents bg color bleeding into CC's UI
        if not NO_COLOR:
            line += "\033[0m"
        print(line)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
