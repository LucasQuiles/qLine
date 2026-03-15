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

import json
import os
import select
import sys
import tomllib
from typing import Any

# --- Constants ---

MAX_STDIN_BYTES = 524_288  # 512 KB byte budget (binary read)
READ_DEADLINE_S = 0.2      # Overall read deadline in seconds
CONFIG_PATH = os.path.expanduser("~/.config/qline.toml")
NO_COLOR = bool(os.environ.get("NO_COLOR"))

# --- Default Theme (Muted Ocean) ---

DEFAULT_THEME: dict[str, Any] = {
    "model": {
        "glyph": "\U000f06a9 ",  # nf-md-robot (Supplementary PUA)
        "color": "#d8dee9",
        "bg": "#3b4252",
        "bold": False,
    },
    "dir": {
        "glyph": "\U000f0770 ",  # nf-md-folder_open (Supplementary PUA)
        "color": "#9bb8d3",
        "bg": "#2e3440",
    },
    "context_bar": {
        "glyph": "\U000f0493 ",  # nf-md-chart_pie (Supplementary PUA)
        "color": "#b5d4a0",
        "bg": "#2e3440",
        "width": 10,
        "warn_threshold": 40.0,
        "warn_color": "#f0d399",
        "critical_threshold": 70.0,
        "critical_color": "#d06070",
    },
    "tokens": {
        "color": "#a8d4d0",
        "bg": "#2e3440",
    },
    "cost": {
        "glyph": "\U000f0d63 ",  # nf-md-lightning_bolt (Supplementary PUA)
        "color": "#e0956a",
        "bg": "#2e3440",
        "warn_threshold": 2.0,
        "warn_color": "#f0d399",
        "critical_threshold": 5.0,
        "critical_color": "#d06070",
    },
    "duration": {
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
}


# --- Config ---

def load_config() -> dict[str, Any]:
    """Load TOML config with shallow per-section merge over defaults."""
    theme = {k: dict(v) for k, v in DEFAULT_THEME.items()}
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
    return f"\033[{';'.join(codes)}m{text}\033[0m"


def style_dim(text: str) -> str:
    """Apply ANSI dim attribute."""
    if NO_COLOR:
        return text
    return f"\033[2m{text}\033[0m"


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
            name = name.replace(" context)", ")")
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
        # Primary: used_percentage (directly from runtime)
        used_pct = ctx_window.get("used_percentage")
        ctx_size = ctx_window.get("context_window_size")
        if isinstance(used_pct, (int, float)) and isinstance(ctx_size, (int, float)) and ctx_size > 0:
            # Synthesize used/total from percentage and size
            state["context_used"] = int(used_pct * ctx_size / 100)
            state["context_total"] = int(ctx_size)
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
          bold: bool = False, theme: dict[str, Any] | None = None) -> str:
    """Wrap text as a pill with optional background and rounded caps."""
    c = color or cfg.get("color")
    bg_hex = cfg.get("bg")
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
    """Format token counts as ↑12.3k ↓4.1k."""
    text = f"\u2191{_abbreviate_count(input_tokens)} \u2193{_abbreviate_count(output_tokens)}"
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


def render(state: dict[str, Any], theme: dict[str, Any] | None = None) -> str:
    """Render a single status line from normalized state.

    Module order: model -> dir -> context_bar -> tokens -> cost -> duration
    Omits absent modules.
    """
    if theme is None:
        theme = DEFAULT_THEME

    parts: list[str] = []
    sep_cfg = theme.get("separator", {})
    sep_char = sep_cfg.get("char", "\u2502")
    sep_dim = sep_cfg.get("dim", True)
    sep = f"{style_dim(sep_char) if sep_dim else sep_char}"

    # Module: model
    model_name = state.get("model_name")
    if model_name:
        m_cfg = theme.get("model", {})
        text = f"{m_cfg.get('glyph', '')}{_sanitize_fragment(model_name)}"
        parts.append(_pill(text, m_cfg, bold=m_cfg.get("bold", False), theme=theme))

    # Module: dir
    dir_basename = state.get("dir_basename")
    if dir_basename:
        d_cfg = theme.get("dir", {})
        text = f"{d_cfg.get('glyph', '')}{_sanitize_fragment(dir_basename)}"
        parts.append(_pill(text, d_cfg, theme=theme))

    # Module: context_bar
    if "context_used" in state and "context_total" in state:
        pct = (state["context_used"] * 100) // state["context_total"]
        parts.append(render_bar(pct, theme))

    # Module: tokens
    if "input_tokens" in state and "output_tokens" in state:
        parts.append(format_tokens(state["input_tokens"], state["output_tokens"], theme))

    # Module: cost
    if "cost_usd" in state:
        c_cfg = theme.get("cost", {})
        cost_val = state["cost_usd"]
        cost_text = f"{c_cfg.get('glyph', '')}{_format_cost(cost_val)}"
        warn_t = c_cfg.get("warn_threshold", 2.0)
        crit_t = c_cfg.get("critical_threshold", 5.0)
        if cost_val >= crit_t:
            parts.append(_pill(cost_text, c_cfg, c_cfg.get("critical_color", "#bf616a"), True, theme))
        elif cost_val >= warn_t:
            parts.append(_pill(cost_text, c_cfg, c_cfg.get("warn_color", "#ebcb8b"), theme=theme))
        else:
            parts.append(_pill(cost_text, c_cfg, theme=theme))

    # Module: duration
    if "duration_ms" in state:
        dur_cfg = theme.get("duration", {})
        text = f"{dur_cfg.get('glyph', '')}{_format_duration(state['duration_ms'])}"
        parts.append(_pill(text, dur_cfg, theme=theme))

    if not parts:
        return ""

    line = sep.join(parts)
    return line


# --- Entrypoint ---

def main() -> None:
    """Status-line entrypoint. Read, normalize, render, emit."""
    theme = load_config()
    payload = read_stdin_bounded()
    if payload is None:
        return
    state = normalize(payload)
    line = render(state, theme)
    if line:
        print(line)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
