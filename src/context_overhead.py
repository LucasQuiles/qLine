"""Overhead monitor functions for qLine statusline.

Extracted from statusline.py when it exceeded 1800 lines.
Provides context overhead estimation and measurement from Claude transcripts.

Import pattern (avoids circular imports):
    statusline.py imports from context_overhead.
    context_overhead does NOT import from statusline.
    Cache utilities and obs references are passed via cache_ctx dict.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

# ── Overhead Monitor: Static Estimation (Phase 1) ───────────────────

_TOKENS_PER_BYTE = 0.325
_SYSTEM_PROMPT_TOKENS = 4000
_TOKENS_PER_DEFERRED_TOOL = 12
_TOKENS_PER_SKILL_STUB = 30


def _estimate_static_overhead(
    claude_md_paths: list[str] | None = None,
) -> int:
    """Estimate system token overhead from measurable local sources.

    Includes: system prompt, CLAUDE.md files, built-in tool definitions,
    and a baseline for deferred tool names and skill stubs.
    Returns a lower-bound token count.
    """
    total = _SYSTEM_PROMPT_TOKENS

    if claude_md_paths is None:
        candidates = [os.path.expanduser("~/.claude/CLAUDE.md")]
        cwd_claude = os.path.join(os.getcwd(), ".claude", "CLAUDE.md")
        if os.path.isfile(cwd_claude):
            candidates.append(cwd_claude)
        cwd_root = os.path.join(os.getcwd(), "CLAUDE.md")
        if os.path.isfile(cwd_root):
            candidates.append(cwd_root)
        claude_md_paths = candidates

    for path in claude_md_paths:
        try:
            size = os.path.getsize(path)
            total += int(size * _TOKENS_PER_BYTE)
        except OSError:
            pass

    # Built-in tool definitions (Read, Write, Edit, Bash, Grep, Glob, etc.)
    # ~968 tokens after deferral (v2.1.69+), ~11k before
    total += 968

    # Deferred tool names — count from settings.json MCP servers if available
    settings_path = os.path.expanduser("~/.claude/settings.json")
    try:
        import json as _json
        with open(settings_path) as f:
            settings = _json.load(f)
        mcp_servers = settings.get("mcpServers", {})
        # Each MCP server contributes ~15-30 deferred tool names
        total += len(mcp_servers) * 20 * _TOKENS_PER_DEFERRED_TOOL
    except Exception:
        # Fallback: assume ~5 MCP servers
        total += 5 * 20 * _TOKENS_PER_DEFERRED_TOOL

    # Skill stubs from plugins
    plugins_dir = os.path.expanduser("~/.claude/plugins/cache")
    try:
        plugin_count = sum(1 for d in os.listdir(plugins_dir) if os.path.isdir(os.path.join(plugins_dir, d)))
        total += plugin_count * 3 * _TOKENS_PER_SKILL_STUB  # ~3 skills per plugin avg
    except OSError:
        total += 10 * _TOKENS_PER_SKILL_STUB  # Fallback

    return total


# ── Overhead Monitor: Transcript Tailing (Phase 2) ──────────────────

_TRANSCRIPT_TAIL_BYTES = 50 * 1024


def _extract_usage(entry: dict) -> dict | None:
    """Extract usage dict from a transcript entry.

    Handles two paths: message.usage (direct turn) and toolUseResult.usage (subagent).
    Skips streaming stubs (stop_reason=null) for the message path.
    """
    msg = entry.get("message")
    if isinstance(msg, dict):
        stop = msg.get("stop_reason")
        if stop is not None:
            usage = msg.get("usage")
            if isinstance(usage, dict):
                return usage

    tur = entry.get("toolUseResult")
    if isinstance(tur, dict):
        usage = tur.get("usage")
        if isinstance(usage, dict):
            return usage

    return None


def _read_transcript_tail(path: str) -> dict | None:
    """Read trailing turns from a session transcript JSONL.

    Returns dict with turn_1_anchor, trailing_turns, cache_hit_rate.
    Or None if no usable data found.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            if size > _TRANSCRIPT_TAIL_BYTES:
                f.seek(size - _TRANSCRIPT_TAIL_BYTES)
                f.readline()  # Discard partial first line
            lines = f.readlines()
    except OSError:
        return None

    turns: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        usage = _extract_usage(entry)
        if usage is None:
            continue

        cache_create = usage.get("cache_creation_input_tokens")
        cache_read = usage.get("cache_read_input_tokens")
        if cache_create is None and cache_read is None:
            continue

        turns.append({
            "cache_read": int(cache_read or 0),
            "cache_create": int(cache_create or 0),
            "input": int(usage.get("input_tokens") or 0),
        })

    if not turns:
        return None

    turn_1_anchor = turns[0]["cache_create"] if turns[0]["cache_create"] > 0 else None
    trailing = turns[-5:]

    total_read = sum(t["cache_read"] for t in trailing)
    total_create = sum(t["cache_create"] for t in trailing)
    denom = total_read + total_create
    cache_hit_rate = total_read / denom if denom > 0 else 0.0

    return {
        "turn_1_anchor": turn_1_anchor,
        "trailing_turns": turns,
        "cache_hit_rate": cache_hit_rate,
    }


def _read_transcript_anchor(path: str) -> int | None:
    """Read the first-turn cache_creation from the start of a transcript.

    Reads first 4KB — the first completed entry is always near the start.
    Returns cache_creation_input_tokens or None.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            chunk = f.read(4096)
    except OSError:
        return None

    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        usage = _extract_usage(entry)
        if usage is None:
            continue
        cc = usage.get("cache_creation_input_tokens")
        if cc is not None and int(cc) > 0:
            return int(cc)
    return None


def _read_manifest_anchor(package_root: str | None) -> int | None:
    """Read cache_anchor from manifest if available."""
    if not package_root:
        return None
    manifest = os.path.join(package_root, "manifest.json")
    try:
        with open(manifest) as f:
            m = json.load(f)
        anchor = m.get("cache_anchor")
        if isinstance(anchor, (int, float)) and anchor > 0:
            return int(anchor)
    except Exception:
        pass
    return None


def _try_phase2_transcript(
    state: dict[str, Any], payload: dict, session_cache: dict,
    package_root: str | None = None,
    cache_warn_rate: float = 0.8,
    cache_critical_rate: float = 0.3,
) -> bool:
    """Attempt Phase 2 measured overhead from transcript. Returns True if successful."""
    path = state.get("transcript_path") or payload.get("transcript_path")
    if not path:
        return False

    result = _read_transcript_tail(path)
    if result is None:
        return False

    # Anchor priority: manifest (durable) > file start > tail window
    if "turn_1_anchor" not in session_cache:
        manifest_anchor = _read_manifest_anchor(package_root)
        if manifest_anchor is not None:
            session_cache["turn_1_anchor"] = manifest_anchor

    if "turn_1_anchor" not in session_cache:
        file_anchor = _read_transcript_anchor(path)
        if file_anchor is not None:
            session_cache["turn_1_anchor"] = file_anchor

    if "turn_1_anchor" not in session_cache:
        if result["turn_1_anchor"] is not None and result["turn_1_anchor"] > 0:
            session_cache["turn_1_anchor"] = result["turn_1_anchor"]
    anchor = session_cache.get("turn_1_anchor", 0)
    if anchor <= 0:
        # Warm cache restart: cache_creation was 0 on turn 1
        # Fall back to static estimate rather than showing 0 overhead
        anchor = _estimate_static_overhead()
        session_cache["turn_1_anchor"] = anchor
        session_cache["sys_overhead_source"] = "estimated"  # Downgrade source

    session_cache["sys_overhead_tokens"] = anchor
    if session_cache.get("sys_overhead_source") != "estimated":
        session_cache["sys_overhead_source"] = "measured"
    session_cache["cache_hit_rate"] = result["cache_hit_rate"]
    session_cache["trailing_turns"] = result["trailing_turns"][-5:]

    # Per-turn injection delta: what was written to cache THIS turn
    trailing = result["trailing_turns"]
    if trailing:
        latest = trailing[-1]
        session_cache["last_cache_create"] = latest["cache_create"]
        # Compute delta vs previous turn's cache_create
        if len(trailing) >= 2:
            prev = trailing[-2]["cache_create"]
            session_cache["prev_cache_create"] = prev
        else:
            session_cache["prev_cache_create"] = 0

    n_turns = len(result["trailing_turns"])
    if n_turns >= 3 and result["cache_hit_rate"] < cache_critical_rate:
        prev_compactions = session_cache.get("prev_compactions", 0)
        current_compactions = state.get("obs_compactions", 0)
        suppress_until = session_cache.get("compaction_suppress_until_turn", 0)

        if current_compactions > prev_compactions:
            session_cache["compaction_suppress_until_turn"] = n_turns + 3
            session_cache["prev_compactions"] = current_compactions

        if n_turns <= suppress_until:
            session_cache["cache_busting"] = False
        else:
            session_cache["cache_busting"] = True
        session_cache["cache_degraded"] = False
    elif n_turns >= 2 and result["cache_hit_rate"] < cache_warn_rate:
        session_cache["cache_busting"] = False
        session_cache["cache_degraded"] = True
    else:
        session_cache["cache_busting"] = False
        session_cache["cache_degraded"] = False

    return True


def _apply_overhead_from_cache(state: dict[str, Any], session_cache: dict) -> None:
    """Copy overhead fields from session cache into renderer state."""
    if "sys_overhead_tokens" in session_cache:
        state["sys_overhead_tokens"] = session_cache["sys_overhead_tokens"]
    if "sys_overhead_source" in session_cache:
        state["sys_overhead_source"] = session_cache["sys_overhead_source"]
    if "cache_hit_rate" in session_cache:
        state["cache_hit_rate"] = session_cache["cache_hit_rate"]
    if "cache_busting" in session_cache:
        state["cache_busting"] = session_cache["cache_busting"]
    if "cache_degraded" in session_cache:
        state["cache_degraded"] = session_cache["cache_degraded"]
    if "last_cache_create" in session_cache:
        state["last_cache_create"] = session_cache["last_cache_create"]
    if "prev_cache_create" in session_cache:
        state["prev_cache_create"] = session_cache["prev_cache_create"]


def inject_context_overhead(
    state: dict[str, Any],
    payload: dict,
    theme: dict,
    cache_ctx: dict,
) -> None:
    """Inject overhead monitor data into state. Never raises.

    cache_ctx must contain:
        load_cache:          callable() -> dict
        save_cache:          callable(dict) -> None
        cache_max_age:       float (seconds)
        obs_available:       bool
        resolve_package_root: callable or None
    """
    try:
        cfg_source = theme.get("context_bar", {}).get("overhead_source", "auto")
        if cfg_source == "off":
            return

        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return

        load_cache = cache_ctx["load_cache"]
        save_cache = cache_ctx["save_cache"]
        cache_max_age = cache_ctx["cache_max_age"]
        obs_available = cache_ctx["obs_available"]
        resolve_package_root = cache_ctx.get("resolve_package_root")

        cache = load_cache()
        obs_cache = cache.get("_obs", {})
        session_cache = obs_cache.get(session_id, {})
        now = time.time()

        if now - session_cache.get("overhead_ts", 0) < 30:
            _apply_overhead_from_cache(state, session_cache)
            return

        package_root: str | None = None
        if obs_available and resolve_package_root is not None:
            obs_root = os.environ.get("OBS_ROOT")
            kwargs = {"obs_root": obs_root} if obs_root else {}
            package_root = resolve_package_root(session_id, **kwargs)

        measured = False
        if cfg_source in ("auto", "measured"):
            ctx_cfg = theme.get("context_bar", {})
            cache_warn = ctx_cfg.get("cache_warn_rate", 0.8)
            cache_crit = ctx_cfg.get("cache_critical_rate", 0.3)
            measured = _try_phase2_transcript(
                state, payload, session_cache, package_root,
                cache_warn_rate=cache_warn, cache_critical_rate=cache_crit,
            )

        if not measured and cfg_source in ("auto", "estimated"):
            estimate = session_cache.get("overhead_estimate")
            if estimate is None or now - session_cache.get("overhead_estimate_ts", 0) >= cache_max_age:
                estimate = _estimate_static_overhead()
                session_cache["overhead_estimate"] = estimate
                session_cache["overhead_estimate_ts"] = now
            session_cache["sys_overhead_tokens"] = estimate
            session_cache["sys_overhead_source"] = "estimated"

        session_cache["overhead_ts"] = now
        obs_cache[session_id] = session_cache
        cache["_obs"] = obs_cache
        save_cache(cache)

        _apply_overhead_from_cache(state, session_cache)
    except Exception:
        pass
