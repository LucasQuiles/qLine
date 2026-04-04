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
_SYSTEM_PROMPT_TOKENS = 6200        # Measured via /context: ~6.2k (was 4k)
_SYSTEM_TOOLS_TOKENS = 11600        # Measured: ~11.6k undeferred, ~968 deferred
_SYSTEM_TOOLS_DEFERRED_TOKENS = 968 # Post-deferral (name-only stubs)
_TOKENS_PER_DEFERRED_TOOL = 12
_TOKENS_PER_SKILL_STUB = 30
# MCP tool overhead: measured averages per server
# Deferred: ~240 tokens/server (name stubs only)
# Undeferred: ~1500 tokens/server (full schemas)
_MCP_TOKENS_PER_SERVER_DEFERRED = 240
_MCP_TOKENS_PER_SERVER_FULL = 1500


def _estimate_static_overhead(
    claude_md_paths: list[str] | None = None,
    context_window: int = 200_000,
) -> int:
    """Estimate system token overhead from measurable local sources.

    Includes: system prompt, CLAUDE.md files, built-in tool definitions,
    MCP server tool schemas, and skill stubs from plugins.

    Detects whether tool deferral is likely active (threshold: MCP tools
    exceed 10% of context window) and uses appropriate per-server cost.

    Returns a lower-bound token count.
    """
    total = _SYSTEM_PROMPT_TOKENS  # ~6.2k measured

    if claude_md_paths is None:
        candidates = [os.path.expanduser("~/.claude/CLAUDE.md")]
        cwd_claude = os.path.join(os.getcwd(), ".claude", "CLAUDE.md")
        if os.path.isfile(cwd_claude):
            candidates.append(cwd_claude)
        cwd_root = os.path.join(os.getcwd(), "CLAUDE.md")
        if os.path.isfile(cwd_root):
            candidates.append(cwd_root)
        claude_md_paths = candidates

    # Auto-memory index (first 200 lines of MEMORY.md): ~1.6k tokens
    memory_md = os.path.expanduser("~/.claude/projects")
    # Simple heuristic: if memory dir exists, add baseline
    if os.path.isdir(memory_md):
        total += 1600

    for path in claude_md_paths:
        try:
            size = os.path.getsize(path)
            total += int(size * _TOKENS_PER_BYTE)
        except OSError:
            pass

    # Count MCP servers and estimate total undeferred tool cost
    settings_path = os.path.expanduser("~/.claude/settings.json")
    n_mcp_servers = 0
    try:
        with open(settings_path) as f:
            settings = json.load(f)
        mcp_servers = settings.get("mcpServers", {})
        n_mcp_servers = len(mcp_servers)
    except Exception:
        n_mcp_servers = 5  # Conservative fallback

    # Deferral detection: CC defers tools when MCP schema total exceeds
    # 10% of context window. Estimate undeferred cost to check.
    undeferred_mcp = n_mcp_servers * _MCP_TOKENS_PER_SERVER_FULL
    deferral_threshold = context_window * 0.10
    tools_deferred = (undeferred_mcp + _SYSTEM_TOOLS_TOKENS) > deferral_threshold

    if tools_deferred:
        total += _SYSTEM_TOOLS_DEFERRED_TOKENS
        total += n_mcp_servers * _MCP_TOKENS_PER_SERVER_DEFERRED
    else:
        total += _SYSTEM_TOOLS_TOKENS
        total += undeferred_mcp

    # Skill stubs from plugins (~250 chars = ~30 tokens each, ~3 skills/plugin)
    plugins_dir = os.path.expanduser("~/.claude/plugins/cache")
    try:
        plugin_count = sum(1 for d in os.listdir(plugins_dir) if os.path.isdir(os.path.join(plugins_dir, d)))
        total += plugin_count * 3 * _TOKENS_PER_SKILL_STUB
    except OSError:
        total += 10 * _TOKENS_PER_SKILL_STUB  # Fallback

    return total


# ── Overhead Monitor: Transcript Tailing (Phase 2) ──────────────────

_TRANSCRIPT_TAIL_BYTES = 50 * 1024


def _extract_usage(entry: dict) -> tuple[dict | None, str | None]:
    """Extract usage dict and requestId from a transcript entry.

    Handles two paths: message.usage (direct turn) and toolUseResult.usage (subagent).
    Skips streaming stubs (stop_reason=null) for the message path.
    Returns (usage_dict, request_id) or (None, None).
    """
    msg = entry.get("message")
    if isinstance(msg, dict):
        stop = msg.get("stop_reason")
        if stop is not None:
            usage = msg.get("usage")
            if isinstance(usage, dict):
                req_id = msg.get("requestId") or entry.get("requestId")
                return usage, req_id

    tur = entry.get("toolUseResult")
    if isinstance(tur, dict):
        usage = tur.get("usage")
        if isinstance(usage, dict):
            req_id = tur.get("requestId") or entry.get("requestId")
            return usage, req_id

    return None, None


# Exponential decay weight for cache hit rate calculation.
# Weight = _CACHE_DECAY ** (distance_from_most_recent).
# 0.7 means each older turn counts ~70% as much as the next newer one,
# so the most recent turn dominates while still smoothing noise.
_CACHE_DECAY = 0.7


def _read_transcript_tail(path: str) -> dict | None:
    """Read trailing turns from a session transcript JSONL.

    Returns dict with turn_1_anchor, trailing_turns, cache_hit_rate.
    Or None if no usable data found.

    Deduplicates PRELIM entries from extended thinking by requestId —
    multiple entries from the same API call (identical requestId) are
    collapsed to the last one seen, preventing 2-5x inflation.

    Cache hit rate uses exponential decay weighting over trailing turns
    for faster response to sudden cache breaks or recoveries.
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

    # Phase 1: collect raw entries, deduplicating by requestId.
    # For entries sharing a requestId (PRELIM + FINAL from same API call),
    # keep only the last one (FINAL has definitive usage).
    seen_req_ids: dict[str, int] = {}  # requestId -> index in raw_turns
    raw_turns: list[dict] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        usage, req_id = _extract_usage(entry)
        if usage is None:
            continue

        cache_create = usage.get("cache_creation_input_tokens")
        cache_read = usage.get("cache_read_input_tokens")
        if cache_create is None and cache_read is None:
            continue

        turn_data = {
            "cache_read": int(cache_read or 0),
            "cache_create": int(cache_create or 0),
            "input": int(usage.get("input_tokens") or 0),
        }

        if req_id and req_id in seen_req_ids:
            # Replace the earlier PRELIM entry with this later one
            raw_turns[seen_req_ids[req_id]] = turn_data
        else:
            if req_id:
                seen_req_ids[req_id] = len(raw_turns)
            raw_turns.append(turn_data)

    # Filter out None placeholders (shouldn't happen, but defensive)
    turns = [t for t in raw_turns if t is not None]

    if not turns:
        return None

    turn_1_anchor = turns[0]["cache_create"] if turns[0]["cache_create"] > 0 else None
    trailing = turns[-5:]

    # Exponential-decay weighted cache hit rate:
    # Most recent turn gets weight 1.0, previous gets _CACHE_DECAY, etc.
    weighted_read = 0.0
    weighted_total = 0.0
    n = len(trailing)
    for i, t in enumerate(trailing):
        w = _CACHE_DECAY ** (n - 1 - i)  # newest=1.0, oldest=decay^(n-1)
        weighted_read += t["cache_read"] * w
        weighted_total += (t["cache_read"] + t["cache_create"]) * w
    cache_hit_rate = weighted_read / weighted_total if weighted_total > 0 else 0.0

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
        usage, _rid = _extract_usage(entry)
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

            # MicroCompact detection: a large drop in cache_create between
            # consecutive turns suggests silent content clearing (tool results
            # replaced with "[Old tool result content cleared]").
            # This is distinct from full compaction (tracked by obs_compactions)
            # and helps explain sudden cache_read drops.
            if prev > 0:
                drop_ratio = latest["cache_create"] / prev
                # >50% drop in cache creation suggests content was cleared
                session_cache["microcompact_suspected"] = drop_ratio < 0.5
            else:
                session_cache["microcompact_suspected"] = False
        else:
            session_cache["prev_cache_create"] = 0
            session_cache["microcompact_suspected"] = False

    # Monotonic session turn counter (does not saturate like trailing window)
    session_turn = session_cache.get("session_turn_count", 0) + 1
    session_cache["session_turn_count"] = session_turn

    n_turns = len(result["trailing_turns"])
    if n_turns >= 3 and result["cache_hit_rate"] < cache_critical_rate:
        prev_compactions = session_cache.get("prev_compactions", 0)
        current_compactions = state.get("obs_compactions", 0)
        suppress_until = session_cache.get("compaction_suppress_until_turn", 0)

        if current_compactions > prev_compactions:
            # Adaptive suppression: base 2 turns, scale with compaction count.
            # First compaction: 2 turns grace. Second: 3. Third+: 4.
            # Caps at 5 to avoid masking genuine busting.
            consecutive = current_compactions - session_cache.get("compaction_baseline", 0)
            grace = min(2 + consecutive, 5)
            session_cache["compaction_suppress_until_turn"] = session_turn + grace
            session_cache["prev_compactions"] = current_compactions

        if session_turn <= suppress_until:
            # Still in grace period — check if cache is already recovering.
            # If hit rate climbed above warn threshold, end suppression early.
            if result["cache_hit_rate"] >= cache_warn_rate:
                session_cache["compaction_suppress_until_turn"] = 0
                session_cache["cache_busting"] = False
                session_cache["cache_degraded"] = False
            else:
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
    _FIELDS = (
        "sys_overhead_tokens", "sys_overhead_source", "cache_hit_rate",
        "cache_busting", "cache_degraded", "last_cache_create",
        "prev_cache_create", "microcompact_suspected",
    )
    for key in _FIELDS:
        if key in session_cache:
            state[key] = session_cache[key]


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
