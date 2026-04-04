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
# System-reminder injection: deferred tool listing + MCP instructions
# These are injected into every API call as <system-reminder> blocks.
# Deferred tool list: ~50 chars per tool name * 0.325 = ~16 tokens/tool
# MCP instructions: ~300 tokens per server (auth info, usage guidance)
# Framing/tags: ~650 tokens (XML tags, formatting)
_DEFERRED_TOOL_LISTING_TOKENS = 16  # per tool, in system-reminder block
_MCP_INSTRUCTION_TOKENS = 300       # per server, usage guidance injected
_SYSTEM_REMINDER_FRAMING = 650      # XML tags, formatting overhead
# Session-start overhead: skills with SessionStart hooks get their full
# content expanded into system-reminders. Plus plugin hook instructions,
# MCP connection status messages, and per-block XML tag framing.
_SESSION_START_OVERHEAD = 3500      # Measured: ~3.5k from hook expansions + framing


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
    total = _SYSTEM_PROMPT_TOKENS + _SESSION_START_OVERHEAD

    if claude_md_paths is None:
        candidates = [os.path.expanduser("~/.claude/CLAUDE.md")]
        cwd_claude = os.path.join(os.getcwd(), ".claude", "CLAUDE.md")
        if os.path.isfile(cwd_claude):
            candidates.append(cwd_claude)
        cwd_root = os.path.join(os.getcwd(), "CLAUDE.md")
        if os.path.isfile(cwd_root):
            candidates.append(cwd_root)
        claude_md_paths = candidates

    # Auto-memory index: measure actual MEMORY.md if found, else 1.6k baseline.
    # Claude injects first 200 lines of MEMORY.md into every system-reminder.
    memory_found = False
    memory_dir = os.path.expanduser("~/.claude/projects")
    if os.path.isdir(memory_dir):
        # Find the project-specific memory dir for cwd
        import hashlib as _hashlib
        cwd_hash = os.getcwd().replace("/", "-")
        mem_path = os.path.join(memory_dir, cwd_hash, "memory", "MEMORY.md")
        if not os.path.isfile(mem_path):
            # Fallback: check all project memory dirs
            for d in os.listdir(memory_dir):
                candidate = os.path.join(memory_dir, d, "memory", "MEMORY.md")
                if os.path.isfile(candidate):
                    mem_path = candidate
                    break
        if os.path.isfile(mem_path):
            try:
                size = os.path.getsize(mem_path)
                total += int(size * _TOKENS_PER_BYTE)
                memory_found = True
            except OSError:
                pass
    if not memory_found:
        total += 1600  # Conservative fallback

    for path in claude_md_paths:
        try:
            size = os.path.getsize(path)
            total += int(size * _TOKENS_PER_BYTE)
        except OSError:
            pass

    # Count MCP servers from all configuration sources.
    # CC reads servers from: ~/.mcp.json, ~/.claude/.mcp.json,
    # project-level .mcp.json, and settings.json mcpServers (rare).
    mcp_server_names: set[str] = set()
    mcp_sources = [
        os.path.expanduser("~/.mcp.json"),
        os.path.expanduser("~/.claude/.mcp.json"),
        os.path.join(os.getcwd(), ".mcp.json"),
    ]
    for mcp_path in mcp_sources:
        try:
            with open(mcp_path) as f:
                mcp_data = json.load(f)
            for name in mcp_data.get("mcpServers", {}):
                mcp_server_names.add(name)
        except Exception:
            pass
    # Also check settings.json (legacy location)
    settings_path = os.path.expanduser("~/.claude/settings.json")
    try:
        with open(settings_path) as f:
            settings = json.load(f)
        for name in settings.get("mcpServers", {}) or {}:
            mcp_server_names.add(name)
    except Exception:
        pass
    n_mcp_servers = len(mcp_server_names) if mcp_server_names else 5  # Fallback

    # Deferral detection: CC defers tools when MCP schema total exceeds
    # 10% of context window. Estimate undeferred cost to check.
    undeferred_mcp = n_mcp_servers * _MCP_TOKENS_PER_SERVER_FULL
    deferral_threshold = context_window * 0.10
    tools_deferred = (undeferred_mcp + _SYSTEM_TOOLS_TOKENS) > deferral_threshold

    if tools_deferred:
        total += _SYSTEM_TOOLS_DEFERRED_TOKENS
        total += n_mcp_servers * _MCP_TOKENS_PER_SERVER_DEFERRED
        # Deferred tool listing: all tool names are injected as a
        # system-reminder block. Estimate ~20 tools per MCP server +
        # ~25 built-in deferred tools.
        n_deferred_tools = n_mcp_servers * 20 + 25
        total += n_deferred_tools * _DEFERRED_TOOL_LISTING_TOKENS
    else:
        total += _SYSTEM_TOOLS_TOKENS
        total += undeferred_mcp

    # MCP server instructions: injected regardless of deferral mode.
    # Each server contributes auth info + usage guidance as system-reminder.
    total += n_mcp_servers * _MCP_INSTRUCTION_TOKENS
    total += _SYSTEM_REMINDER_FRAMING

    # Count actual skill/agent/command stubs from enabled plugins.
    # Each item is injected into system-reminders with name + description
    # + formatting. Measured from actual frontmatter + rendered output:
    # Skills: ~183 chars FM + ~60 chars formatting = ~243 chars avg
    # Agents: ~286 chars FM + ~80 chars formatting (tool list) = ~366 chars avg
    # Commands: ~60 chars name + formatting = ~60 chars avg
    _TOKENS_PER_SKILL_ITEM = 79     # ~243 chars * 0.325
    _TOKENS_PER_AGENT_ITEM = 119    # ~366 chars * 0.325
    _TOKENS_PER_COMMAND_ITEM = 20   # ~60 chars * 0.325
    n_skills = n_agents = n_commands = 0
    try:
        with open(settings_path) as f:
            settings = json.load(f)
        enabled_plugins = settings.get("enabledPlugins", {})
        plugins_dir = os.path.expanduser("~/.claude/plugins/cache")
        import glob as _glob
        for key, val in enabled_plugins.items():
            if not val:
                continue
            parts = key.split("@")
            if len(parts) != 2:
                continue
            pname, mkt = parts
            search_base = os.path.join(plugins_dir, mkt, pname)
            if not os.path.isdir(search_base):
                search_base = os.path.join(plugins_dir, mkt)
            if not os.path.isdir(search_base):
                continue
            # Count skill/agent/command definitions from latest version.
            # Layout: plugins/cache/<marketplace>/<plugin>/<version>/
            # Skills: skills/<name>/SKILL.md (subdirectory style)
            # Agents: agents/<name>.md (flat style)
            # Commands: commands/<name>.md or commands/<name>/COMMAND.md
            version_dirs = [
                d for d in _glob.glob(os.path.join(search_base, "*"))
                if os.path.isdir(d)
            ]
            if version_dirs:
                # Sort by semver: split on '.', compare numerically
                def _ver_key(p):
                    v = os.path.basename(p)
                    try:
                        return tuple(int(x) for x in v.split("."))
                    except (ValueError, AttributeError):
                        return (0,)
                latest = max(version_dirs, key=_ver_key)
            else:
                latest = search_base
            for md in _glob.glob(os.path.join(latest, "skills", "*", "SKILL.md")):
                n_skills += 1
            for md in _glob.glob(os.path.join(latest, "agents", "*.md")):
                n_agents += 1
            for md in _glob.glob(os.path.join(latest, "commands", "*.md")):
                n_commands += 1
    except Exception:
        pass

    if n_skills + n_agents + n_commands > 0:
        total += n_skills * _TOKENS_PER_SKILL_ITEM
        total += n_agents * _TOKENS_PER_AGENT_ITEM
        total += n_commands * _TOKENS_PER_COMMAND_ITEM
    else:
        # Fallback: rough estimate from plugin directory count
        plugins_dir = os.path.expanduser("~/.claude/plugins/cache")
        try:
            plugin_count = sum(1 for d in os.listdir(plugins_dir) if os.path.isdir(os.path.join(plugins_dir, d)))
            total += plugin_count * 3 * _TOKENS_PER_SKILL_STUB
        except OSError:
            total += 10 * _TOKENS_PER_SKILL_STUB

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


def _read_transcript_tail(path: str, window_size: int = 5) -> dict | None:
    """Read trailing turns from a session transcript JSONL.

    Returns dict with turn_1_anchor, trailing_turns, cache_hit_rate.
    Or None if no usable data found.

    Args:
        path: Path to transcript JSONL file.
        window_size: Number of trailing turns for cache hit rate (default 5).
            Adaptive callers scale this with session length.

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

        # Skip sidechain entries (subagent forks have separate cache state)
        if entry.get("isSidechain") is True:
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
    trailing = turns[-window_size:]

    # Exponential-decay weighted cache hit rate:
    # Most recent turn gets weight 1.0, previous gets _CACHE_DECAY, etc.
    #
    # Server-side tool inflation guard: web_search and web_fetch accumulate
    # internal API cache_reads that aren't real conversation cache hits.
    # These show as outlier spikes where cache_read >> anchor value.
    # Cap per-turn cache_read at 3x anchor to prevent distortion.
    anchor_val = turn_1_anchor or 0
    read_cap = anchor_val * 3 if anchor_val > 0 else float("inf")
    weighted_read = 0.0
    weighted_total = 0.0
    n = len(trailing)
    for i, t in enumerate(trailing):
        w = _CACHE_DECAY ** (n - 1 - i)  # newest=1.0, oldest=decay^(n-1)
        capped_read = min(t["cache_read"], read_cap)
        weighted_read += capped_read * w
        weighted_total += (capped_read + t["cache_create"]) * w
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

    # Adaptive trailing window: scale with session length for better signal.
    # Short sessions (<9 turns): minimum window of 3 (avoid noise from 1-2 turns).
    # Long sessions (24+ turns): up to 8 turns for smoother rolling average.
    # Middle ground: grow linearly (session_turns // 3).
    prev_turns = session_cache.get("session_turn_count", 0)
    window = min(max(3, prev_turns // 3), 8)
    result = _read_transcript_tail(path, window_size=window)
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
    else:
        # Calibration: compare measured anchor to static estimate.
        # Ratio >1 means static underestimates; <1 means overestimates.
        # This is informational — helps tune _TOKENS_PER_BYTE et al.
        if "calibration_ratio" not in session_cache:
            estimate = _estimate_static_overhead()
            if estimate > 0:
                session_cache["calibration_ratio"] = round(anchor / estimate, 3)

    session_cache["sys_overhead_tokens"] = anchor
    if session_cache.get("sys_overhead_source") != "estimated":
        session_cache["sys_overhead_source"] = "measured"
    session_cache["cache_hit_rate"] = result["cache_hit_rate"]
    session_cache["trailing_turns"] = result["trailing_turns"][-window:]

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

    # Cache TTL expiry detection: if the most recent turn shows a full rebuild
    # (cache_create close to anchor, cache_read near zero) but previous turns
    # were healthy, this is likely a TTL expiry (5-min Pro/API, 1-hour Max),
    # not genuine cache busting. Flag it separately and don't escalate severity.
    cache_expired = False
    trailing = result["trailing_turns"]
    if anchor > 0 and len(trailing) >= 2:
        latest = trailing[-1]
        prev_healthy = any(
            t["cache_read"] > t["cache_create"] for t in trailing[:-1]
        )
        # "Full rebuild" heuristic: cache_create >= 80% of anchor AND
        # cache_read < 20% of cache_create (mostly misses this turn)
        full_rebuild = (
            latest["cache_create"] >= anchor * 0.8
            and (latest["cache_read"] < latest["cache_create"] * 0.2)
        )
        if full_rebuild and prev_healthy:
            cache_expired = True
    session_cache["cache_expired"] = cache_expired

    n_turns = len(result["trailing_turns"])
    if cache_expired:
        # TTL expiry: don't flag as busting — it will self-heal next turn
        session_cache["cache_busting"] = False
        session_cache["cache_degraded"] = False
    elif n_turns >= 3 and result["cache_hit_rate"] < cache_critical_rate:
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
        "cache_busting", "cache_degraded", "cache_expired",
        "last_cache_create", "prev_cache_create", "microcompact_suspected",
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
