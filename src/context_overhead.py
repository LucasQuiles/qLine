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
from datetime import datetime, timezone
from typing import Any

# ── Parse Diagnostic Sidecar (OPP-14) ───────────────────────────────
#
# When transcript JSONL lines fail JSON parsing, write a diagnostic record
# to {package_root}/native/statusline/diagnostics.jsonl for post-mortem.
# Max 10 writes per invocation to prevent unbounded growth.

_DIAG_MAX_PER_INVOCATION = 10
_diag_write_count = 0  # module-level counter, reset per process lifetime


def _write_parse_diag(diag_root: str, source: str, error: str, line_preview: str) -> None:
    """Atomically append one parse-failure record to diagnostics.jsonl.

    Fail-open: any OS/IO error is silently swallowed.
    Hard cap: at most _DIAG_MAX_PER_INVOCATION writes per process.
    """
    global _diag_write_count
    if _diag_write_count >= _DIAG_MAX_PER_INVOCATION:
        return
    try:
        diag_dir = os.path.join(diag_root, "native", "statusline")
        os.makedirs(diag_dir, exist_ok=True)
        diag_path = os.path.join(diag_dir, "diagnostics.jsonl")
        ts = datetime.now(tz=timezone.utc).isoformat()
        record = json.dumps({
            "ts": ts,
            "source": source,
            "error": error,
            "line_preview": line_preview[:100],
        })
        fd = os.open(diag_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, (record + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        _diag_write_count += 1
    except Exception:
        pass  # Strictly fail-open

# ── Overhead Monitor: Static Estimation (Phase 1) ───────────────────
#
# Constants verified against Claude Code v2.1.92 decompiled source.
# Key source functions:
#   dR_(usage, windowSize) → {used, remaining}  (context percentage)
#   iLH(usage) → total tokens  (input + cache_create + cache_read + output)
#   EH_(model, customWindow) → autocompact threshold
#   nU(model, customWindow) → effective window after output reserve
#   dYH(tokens, model, window) → context health status

_TOKENS_PER_BYTE = 0.325
_SYSTEM_PROMPT_TOKENS = 6200        # Measured via /context: ~6.2k (was 4k)
_SYSTEM_TOOLS_TOKENS = 11600        # Measured: ~11.6k undeferred, ~968 deferred
_SYSTEM_TOOLS_DEFERRED_TOKENS = 968 # Post-deferral (name-only stubs)
_TOKENS_PER_DEFERRED_TOOL = 12
_TOKENS_PER_SKILL_STUB = 30
# MCP tool overhead: measured averages per server
_MCP_TOKENS_PER_SERVER_DEFERRED = 240   # name stubs only
_MCP_TOKENS_PER_SERVER_FULL = 1500      # full schemas
# System-reminder injection overhead
_DEFERRED_TOOL_LISTING_TOKENS = 16  # per tool, in system-reminder block
_MCP_INSTRUCTION_TOKENS = 300       # per server, usage guidance injected
_SYSTEM_REMINDER_FRAMING = 650      # XML tags, formatting overhead
_SESSION_START_OVERHEAD = 3500      # hook skill expansions + framing

# ── Internal CC Constants (from v2.1.92 source) ─────────────────────
#
# used_percentage formula (CONFIRMED from dR_ source):
#   used = round((input_tokens + cache_creation + cache_read) / window * 100)
#   NOTE: output_tokens are EXCLUDED from used_percentage
#   But iLH (total tokens) DOES include output_tokens
#
# exceeds_200k formula (from FrH source):
#   iLH(lastAssistantUsage) > 200000
#   Where iLH = input + cache_creation + cache_read + output
#
# Context health thresholds (from dYH, EH_, nU source):
CC_OUTPUT_RESERVE = 20_000     # Ha1: max output tokens reserved from window
CC_AUTOCOMPACT_BUFFER = 13_000 # W68: reserved for compaction request
CC_WARNING_OFFSET = 20_000     # _a1: offset below effective for warning
CC_ERROR_OFFSET = 20_000       # qa1: offset below effective for error
CC_BLOCKING_BUFFER = 3_000     # R68: hard blocking limit buffer
# CC internal estimation: Cs6 = 4 chars per token (0.25 tokens/char).
# Our _TOKENS_PER_BYTE = 0.325 is more accurate vs real tokenizer output.
CC_CHARS_PER_TOKEN = 4         # Cs6: CC's internal rough estimate
# Per-tool maxResultSizeChars (from tool definitions, verified):
CC_TOOL_BUDGET_BASH = 30_000   # chars, before persisting to disk
CC_TOOL_BUDGET_GREP = 20_000   # chars, before persisting to disk
CC_TOOL_BUDGET_DEFAULT = 1     # other tools use 2000-char preview path
CC_PERSISTED_PREVIEW = 2_000   # Fy6: preview chars for persisted output
# MicroCompact: per-message-group tool result budget
CC_MESSAGE_TOOL_BUDGET = 200_000  # AR4: chars per message group
# Feature flag: tengu_hawthorn_steeple gates MicroCompact


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

    # Tool deferral (VERIFIED from CC v2.1.92 npm source, isDeferredTool):
    # - ALL MCP tools are ALWAYS deferred (isMcp === true → deferred)
    # - Built-in tools have static shouldDefer boolean
    # - There is NO dynamic percentage threshold — deferral is structural
    # So MCP tools always use deferred cost, built-in tools are split.
    total += _SYSTEM_TOOLS_DEFERRED_TOKENS  # Built-in deferred stubs
    total += n_mcp_servers * _MCP_TOKENS_PER_SERVER_DEFERRED
    # Deferred tool listing: all deferred tool names injected as system-reminder.
    # ~20 tools per MCP server + ~25 built-in deferred tools.
    n_deferred_tools = n_mcp_servers * 20 + 25
    total += n_deferred_tools * _DEFERRED_TOOL_LISTING_TOKENS

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


_extract_usage_full = None
try:
    # hooks/ dir may already be on sys.path (statusline.py adds it).
    # If not, add it so obs_utils is importable.
    import sys as _sys
    _hooks_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
    if _hooks_dir not in _sys.path:
        _sys.path.insert(0, _hooks_dir)
    from obs_utils import extract_usage_full as _extract_usage_full
except ImportError:
    pass


def _extract_usage(entry: dict) -> tuple[dict | None, str | None]:
    """Extract usage dict and requestId from a transcript entry.

    Delegates to obs_utils.extract_usage_full, returning (usage, request_id).
    Falls back to inline extraction if obs_utils is unavailable.
    """
    if _extract_usage_full is not None:
        usage, _model, request_id, _entry_id = _extract_usage_full(entry)
        return usage, request_id

    # Inline fallback (obs_utils not importable — e.g. isolated test runner)
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


def _read_transcript_tail(path: str, window_size: int = 5, diag_root: str | None = None) -> dict | None:
    """Read trailing turns from a session transcript JSONL.

    Returns dict with turn_1_anchor, trailing_turns, cache_hit_rate.
    Or None if no usable data found.

    Args:
        path: Path to transcript JSONL file.
        window_size: Number of trailing turns for cache hit rate (default 5).
            Adaptive callers scale this with session length.
        diag_root: Optional package root for parse diagnostic sidecar (OPP-14).

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
        except (json.JSONDecodeError, ValueError) as exc:
            if diag_root:
                _write_parse_diag(diag_root, "transcript_tail", f"JSONDecodeError: {exc}", line)
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
    # These show as outlier spikes where cache_read >> median of the window.
    # Cap at 3x median to catch spikes without clipping normal growth.
    reads = sorted(t["cache_read"] for t in trailing)
    median_read = reads[len(reads) // 2] if reads else 0
    read_cap = max(median_read * 3, 1) if median_read > 0 else float("inf")
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


def _read_transcript_anchor(path: str, diag_root: str | None = None) -> int | None:
    """Read the first-turn cache_creation from the start of a transcript.

    Reads first 128KB — transcripts start with metadata entries
    (permission-mode, file-history-snapshot, user messages, attachments)
    before the first assistant message with usage data appears.
    Attachments alone can be 35KB+, pushing first API response past 64KB.
    Returns cache_creation_input_tokens or None.

    Args:
        path: Path to transcript JSONL file.
        diag_root: Optional package root for parse diagnostic sidecar (OPP-14).
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            chunk = f.read(131072)
    except OSError:
        return None

    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError) as exc:
            if diag_root:
                _write_parse_diag(diag_root, "transcript_anchor", f"JSONDecodeError: {exc}", line)
            continue
        usage, _rid = _extract_usage(entry)
        if usage is None:
            continue
        cc = usage.get("cache_creation_input_tokens")
        if cc is not None and int(cc) > 0:
            return int(cc)
    return None


def _read_transcript_anchor_with_read(path: str, diag_root: str | None = None) -> int | None:
    """Read the first-turn system overhead from cache_read on warm restarts.

    When a session starts with a warm cache (cache_creation < 5000),
    the real system overhead is in cache_read_input_tokens — that's what
    the API read from the existing cache. Reads first 128KB to find it
    (transcript starts with metadata entries + attachments before first API response).

    Args:
        path: Path to transcript JSONL file.
        diag_root: Optional package root for parse diagnostic sidecar (OPP-14).
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            chunk = f.read(131072)
    except OSError:
        return None

    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError) as exc:
            if diag_root:
                _write_parse_diag(diag_root, "transcript_anchor_with_read", f"JSONDecodeError: {exc}", line)
            continue
        usage, _rid = _extract_usage(entry)
        if usage is None:
            continue
        cr = usage.get("cache_read_input_tokens")
        if cr is not None and int(cr) > 0:
            return int(cr)
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
    result = _read_transcript_tail(path, window_size=window, diag_root=package_root)
    if result is None:
        return False

    # Anchor priority: transcript file start (accurate) > manifest (fallback) > tail window
    # The transcript's first-turn cache_creation is the real system overhead (~37k-52k).
    # The manifest's cache_anchor stores per-turn cache_create deltas (~973-2406),
    # which are far too small — using them poisons overhead computation.
    if "turn_1_anchor" not in session_cache:
        file_anchor = _read_transcript_anchor(path, diag_root=package_root)
        if file_anchor is not None:
            session_cache["turn_1_anchor"] = file_anchor

    if "turn_1_anchor" not in session_cache:
        manifest_anchor = _read_manifest_anchor(package_root)
        if manifest_anchor is not None:
            session_cache["turn_1_anchor"] = manifest_anchor

    if "turn_1_anchor" not in session_cache:
        if result["turn_1_anchor"] is not None and result["turn_1_anchor"] > 0:
            session_cache["turn_1_anchor"] = result["turn_1_anchor"]
    anchor = session_cache.get("turn_1_anchor", 0)
    # Warm cache detection: on resumed sessions or sessions started after
    # another session warmed the cache, cache_creation on turn 1 is tiny
    # (just the delta for new content). The real overhead is in cache_read.
    # Threshold: if anchor < 5000, it's almost certainly a warm restart —
    # the system prompt alone is 6.2k tokens, so anything below that
    # means most content was read from cache, not created.
    _WARM_CACHE_THRESHOLD = 5000
    if anchor < _WARM_CACHE_THRESHOLD:
        # Read the actual first turn from the file start (not tail window).
        # On a warm restart, turn 1's cache_read IS the system overhead.
        path = state.get("transcript_path") or payload.get("transcript_path")
        if path:
            first_anchor = _read_transcript_anchor_with_read(path, diag_root=package_root)
            if first_anchor and first_anchor > _WARM_CACHE_THRESHOLD:
                anchor = first_anchor
                session_cache["turn_1_anchor"] = anchor
                session_cache["sys_overhead_source"] = "measured"
            else:
                anchor = _estimate_static_overhead()
                session_cache["turn_1_anchor"] = anchor
                session_cache["sys_overhead_source"] = "estimated"
        else:
            anchor = _estimate_static_overhead()
            session_cache["turn_1_anchor"] = anchor
            session_cache["sys_overhead_source"] = "estimated"
    else:
        # Calibration: compare measured anchor to static estimate.
        # Computes once per session when measured anchor is available.
        if "calibration_ratio" not in session_cache:
            estimate = _estimate_static_overhead()
            if estimate > 0:
                ratio = round(anchor / estimate, 3)
                accuracy = round(min(estimate, anchor) / max(estimate, anchor) * 100, 1)
                session_cache["calibration_ratio"] = ratio
                session_cache["calibration_accuracy"] = accuracy
                session_cache["calibration_estimate"] = estimate

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
        session_cache["last_cache_read"] = latest["cache_read"]
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
                abs_drop = prev - latest["cache_create"]
                # MicroCompact: >50% drop AND absolute drop > 5000 tokens.
                # Small fluctuations (246→101) are normal noise, not clearing.
                # Real MicroCompact drops are 30k→500 (tool results wiped).
                session_cache["microcompact_suspected"] = drop_ratio < 0.5 and abs_drop > 5000
            else:
                session_cache["microcompact_suspected"] = False
        else:
            session_cache["prev_cache_create"] = 0
            session_cache["microcompact_suspected"] = False

    # Context growth rate: average cache_read delta per turn over trailing window.
    # Combined with autocompact threshold, gives "turns until compaction".
    if len(trailing) >= 2:
        deltas = []
        for j in range(1, len(trailing)):
            d = trailing[j]["cache_read"] - trailing[j - 1]["cache_read"]
            if d > 0:
                deltas.append(d)
        if deltas:
            avg_growth = sum(deltas) // len(deltas)
            session_cache["context_growth_per_turn"] = avg_growth
            # Estimate turns until autocompact from current usage
            ctx_total = state.get("context_total", 0)
            ctx_used = state.get("context_used_corrected", state.get("context_used", 0))
            if ctx_total > 0 and avg_growth > 0:
                thresholds = compute_context_thresholds(ctx_total)
                remaining = thresholds["autocompact_at"] - ctx_used
                if remaining > 0:
                    session_cache["turns_until_compact"] = remaining // avg_growth

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


def compute_context_thresholds(context_window: int) -> dict[str, int]:
    """Compute exact CC context thresholds from verified source constants.

    Mirrors the logic of EH_(model, window), nU(model, window), and
    dYH(tokens, model, window) from Claude Code v2.1.92.
    """
    if context_window <= 0:
        return {
            "effective_window": 0, "autocompact_at": 0, "warning_at": 0,
            "error_at": 0, "blocking_at": 0, "autocompact_pct": 0,
            "blocking_pct": 0,
        }
    effective = context_window - CC_OUTPUT_RESERVE
    autocompact = effective - CC_AUTOCOMPACT_BUFFER
    warning = effective - CC_WARNING_OFFSET
    error = autocompact - CC_ERROR_OFFSET
    blocking = effective - CC_BLOCKING_BUFFER
    return {
        "effective_window": effective,
        "autocompact_at": autocompact,
        "warning_at": warning,
        "error_at": error,
        "blocking_at": blocking,
        # Percentages of the full context window
        "autocompact_pct": round(autocompact / context_window * 100, 1),
        "blocking_pct": round(blocking / context_window * 100, 1),
    }


def _apply_overhead_from_cache(state: dict[str, Any], session_cache: dict) -> None:
    """Copy overhead fields from session cache into renderer state."""
    _FIELDS = (
        "sys_overhead_tokens", "sys_overhead_source", "cache_hit_rate",
        "cache_busting", "cache_degraded", "cache_expired",
        "last_cache_create", "last_cache_read", "prev_cache_create", "microcompact_suspected",
        "calibration_accuracy", "context_growth_per_turn", "turns_until_compact",
        "session_turn_count",
    )
    for key in _FIELDS:
        if key in session_cache:
            state[key] = session_cache[key]

    # Inject context thresholds for the renderer
    ctx_total = state.get("context_total")
    if ctx_total and ctx_total > 0:
        thresholds = compute_context_thresholds(ctx_total)
        state["cc_autocompact_pct"] = thresholds["autocompact_pct"]
        state["cc_blocking_pct"] = thresholds["blocking_pct"]


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
        resolve_package_root_env: callable or None
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
        resolve_package_root_env = cache_ctx.get("resolve_package_root_env")

        cache = load_cache()
        obs_cache = cache.get("_obs", {})
        session_cache = obs_cache.get(session_id, {})
        now = time.time()

        if now - session_cache.get("overhead_ts", 0) < 5:
            _apply_overhead_from_cache(state, session_cache)
            return

        package_root: str | None = None
        if obs_available and resolve_package_root_env is not None:
            package_root = resolve_package_root_env(session_id)

        # Derive transcript path if not in payload (CC's statusline payload
        # built by x05/liY does NOT include transcript_path).
        # Transcripts live at: ~/.claude/projects/<project-hash>/<session-id>.jsonl
        if not state.get("transcript_path") and not payload.get("transcript_path"):
            projects_dir = os.path.expanduser("~/.claude/projects")
            if os.path.isdir(projects_dir):
                tp_name = f"{session_id}.jsonl"
                # Check cached path first (avoids re-scanning every 30s)
                cached_tp = session_cache.get("_transcript_path")
                if cached_tp and os.path.isfile(cached_tp):
                    state["transcript_path"] = cached_tp
                else:
                    # Scan project dirs for this session's transcript
                    for d in os.listdir(projects_dir):
                        candidate = os.path.join(projects_dir, d, tp_name)
                        if os.path.isfile(candidate):
                            state["transcript_path"] = candidate
                            session_cache["_transcript_path"] = candidate
                            break

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
