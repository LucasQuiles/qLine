# Context Overhead Monitor — Design Spec

**Date:** 2026-04-04
**Status:** Approved
**Scope:** qLine status-line module + post-session forensics report

## Problem

Claude Code's context window contains a large invisible layer of system tokens — tool definitions, CLAUDE.md files, skill stubs, MCP schemas, the system prompt itself, and injected content like anti-distillation fake tools. Users cannot see how much of their context window is consumed by this scaffolding vs their actual conversation.

The status line API provides only aggregate totals (`total_input_tokens`, `total_output_tokens`, `used_percentage`). No per-source breakdown is exposed.

Community measurements show the scale of the problem:

| Setup | System Overhead | % of 200k Window |
|-------|----------------|-------------------|
| Minimal (2 MCP servers) | ~15k tokens | 7.5% |
| Moderate (5 servers, 58 tools) | ~55k tokens | 27.5% |
| Heavy (enterprise integrations) | ~99k tokens | 49.3% |
| Worst documented case | ~173k tokens | 86.5% |

Additional risk: prompt cache invalidation bugs (confirmed in v2.1.76+) can cause 10-20x cost inflation without any visible signal to the user.

## Solution

Replace the single-color context progress bar in qLine with a dual-color stacked bar that visually splits system overhead from conversation content. Add cache health detection to alert when prompt caching breaks down.

## Display

### Dual-Bar Rendering

Current:
```
󰋑 █████░░░░░ 15%
```

New:
```
󰋑 ███▓▓░░░░░ 15%
```

Three segments:
- `█` (full block) — system overhead (tools, system prompt, CLAUDE.md, skills, MCP). Color: muted red/amber (`#d08070`).
- `▓` (medium shade) — conversation content (user messages, assistant responses, tool results). Color: muted blue/teal (`#80b0d0`).
- `░` (light shade) — free context remaining. Color: unchanged from current theme.

### Token Count Prefix

Unchanged: `↑281k↓141k` prefix remains, showing cumulative input/output totals.

### Threshold Behavior

Two independent threshold axes:

**System overhead thresholds** (percentage of total context window consumed by system tokens):
- Normal: system < 30% of total window
- Warn (`~` suffix, warn color): system >= 30%
- Critical (`!` suffix, critical color, bold): system >= 50%

**Total usage thresholds** (unchanged from current):
- Normal: total < 40%
- Warn: total >= 40%
- Critical: total >= 70%

The more severe of the two determines the displayed state.

### Cache Health Indicator

A fourth display state overlays the threshold behavior:

- Cache busting detected (`⚡` suffix): replaces the normal `%` / `%~` / `%!` suffix when cache invalidation is occurring. Takes precedence over threshold indicators because active cache busting is the highest-priority signal — it means tokens are being burned at 10-20x the normal rate.

### Display Examples

```
󰋑 █▓░░░░░░░░  8%     healthy: small system footprint, light conversation
󰋑 ███▓▓░░░░░ 22%     normal: moderate system, growing conversation
󰋑 ████▓▓▓░░░ 42%~    warn: total usage crossing 40%
󰋑 ██████▓░░░ 38%~    warn: system alone is 35% (sys_warn_threshold)
󰋑 ██████▓▓░░ 65%!    critical: system eating most of the window
󰋑 ███▓▓▓░░░░ 31%⚡   cache busting: creates >> reads for 3+ turns
```

## Data Architecture

### Phase 1 — Static Bootstrap (Turn 0)

Before any API response is available, estimate system overhead from measurable sources on the local filesystem.

| Source | Method | Typical Tokens |
|--------|--------|---------------|
| CLAUDE.md files | `os.stat()` byte size / 4 * 1.3 | 1k-28k |
| Claude Code system prompt | Fixed constant (validated against source leak) | ~4k |
| Deferred tool names | Count from `instructions_loaded.jsonl` or payload parsing | 2k-5k |
| Active MCP tool schemas | Count MCP servers * average schema size | 5k-50k |
| Skill stubs | Count skill entries if observable | 2k-4k |

The token estimate uses a ratio of ~1.3 tokens per 4-byte word, which accounts for subword tokenization overhead in Claude's tokenizer.

This estimate is a **lower bound**. Real overhead includes content we cannot measure externally (anti-distillation injected tools, internal scaffolding, attestation data).

Stored as `state["sys_overhead_estimate"]`.

### Phase 2 — Measured Steady-State (Turn 1+)

Tail the session transcript JSONL at:
```
~/.claude/projects/<project>/<session_id>.jsonl
```

Each API response in the transcript contains usage fields:

```json
{
  "cache_read_input_tokens": 95000,
  "cache_creation_input_tokens": 250,
  "input_tokens": 1200
}
```

Key insight: **`cache_read_input_tokens` IS the system overhead measurement.** It represents the exact size of the cached prefix that repeats every turn — the concatenation of tool definitions, system prompt, CLAUDE.md, skills, and all other injected content. When the cache is healthy, this number is stable and large. `input_tokens` represents fresh conversation content added after the last cache breakpoint.

Derived metrics computed per status update (trailing window of 5 turns):

| Metric | Derivation |
|--------|-----------|
| `sys_overhead` | `cache_read_input_tokens` from latest turn (when cache hitting) |
| `conv_tokens` | `context_used - sys_overhead` |
| `cache_hit_rate` | `sum(cache_read) / sum(cache_read + cache_creation)` over trailing 5 turns |
| `cache_busting` | `True` when `cache_creation > cache_read` for 3+ consecutive turns |

When cache is busting (no reads, all creates), `sys_overhead` falls back to `cache_creation_input_tokens` from the most recent turn, since that represents the full prefix being rewritten.

### Fallback Cascade

1. Transcript JSONL available with cache fields → Phase 2 (measured values)
2. Transcript JSONL missing or cache fields absent → Phase 1 (static estimate)
3. Neither available → render single-color bar (current behavior, no degradation)

### Caching

Transcript metrics are read on the same 30-second interval as existing obs modules. Parsed values are stored in `/tmp/qline-cache.json` alongside existing cached counters. The cache entry includes:

```json
{
  "overhead_ts": 1712234567.0,
  "sys_overhead_tokens": 42000,
  "conv_tokens": 68000,
  "cache_hit_rate": 0.91,
  "cache_busting": false,
  "source": "measured",
  "trailing_turns": [
    {"cache_read": 95000, "cache_create": 250, "input": 1200},
    {"cache_read": 95200, "cache_create": 0, "input": 1800}
  ]
}
```

Staleness threshold: 60 seconds. If cached data is older, re-read transcript.

## Cache Health Detection

Three states, derived from `cache_hit_rate` over the trailing 5-turn window:

### Healthy (`cache_hit_rate > 0.8`)

System prefix is stable and being cached. Dual-bar renders normally. No additional indicator.

### Degraded (`0.3 <= cache_hit_rate <= 0.8`)

Something is intermittently invalidating the cache — possibly tool definition changes, skill loads mid-session, or MCP server reconnections. Suffix uses the warn convention (`~`). The system overhead segment uses warn color.

### Cache Busting (`cache_hit_rate < 0.3`)

Active, sustained cache invalidation. Known causes from the March 2026 bugs:
- Attestation data changing per request
- Anti-distillation fake tool injection varying between requests
- Bun fork sentinel string replacement hitting conversation content

Suffix changes to `⚡`. Entire bar uses critical color. This is the "your tokens are burning 10-20x faster" alarm.

## Post-Session Forensics

When the session ends, the existing `obs-session-end.py` hook generates an overhead report as a derived artifact in the session package:

```
~/.claude/observability/sessions/<date>/<session_id>/derived/overhead_report.json
```

Contents:

```json
{
  "session_id": "abc123",
  "total_turns": 47,
  "system_overhead_avg_tokens": 42000,
  "system_overhead_pct_of_window": 4.2,
  "system_overhead_pct_of_used": 38.2,
  "conversation_tokens_final": 68000,
  "free_tokens_final": 890000,
  "cache_hit_rate_overall": 0.91,
  "cache_busting_events": 2,
  "cache_busting_turns": [12, 13, 14, 31, 32, 33],
  "overhead_breakdown_estimate": {
    "claude_code_system_prompt": 4000,
    "claude_md_files": 3200,
    "tool_definitions_loaded": 28000,
    "skill_stubs": 3400,
    "deferred_tool_names": 2600
  },
  "compaction_events": 1,
  "peak_usage_pct": 72.4,
  "peak_sys_overhead_pct": 41.0,
  "total_cache_read_tokens": 4465000,
  "total_cache_create_tokens": 12500,
  "total_fresh_input_tokens": 56400,
  "effective_cost_multiplier": 1.03
}
```

The `effective_cost_multiplier` compares actual token consumption against the theoretical minimum (perfect caching). A value of 1.0 means zero waste; values above 2.0 indicate significant cache problems.

## Configuration

New keys added to `context_bar` section of `DEFAULT_THEME` and `~/.config/qline.toml`:

```toml
[context_bar]
# Existing keys unchanged:
# enabled, glyph, color, bg, width, warn_threshold, critical_threshold,
# warn_color, critical_color

# New: dual-bar colors
sys_color = "#d08070"           # muted red/amber for system overhead
conv_color = "#80b0d0"          # muted blue/teal for conversation

# New: system overhead thresholds (% of total context window)
sys_warn_threshold = 30.0
sys_critical_threshold = 50.0

# New: cache health thresholds
cache_warn_rate = 0.8           # hit rate below this = degraded
cache_critical_rate = 0.3       # below this = cache busting alert

# New: data source control
overhead_source = "auto"        # "auto" | "measured" | "estimated" | "off"
```

`overhead_source` values:
- `auto` (default): Phase 2 when available, Phase 1 fallback
- `measured`: Phase 2 only, single-color fallback if transcript unavailable
- `estimated`: Phase 1 only, no transcript reading
- `off`: disable dual-bar, render single-color bar (current behavior)

## Implementation Scope

### Files Modified

**`src/statusline.py`:**
- `normalize()` — no changes (context_window parsing unchanged)
- `render_context_bar()` — rewrite to render dual-color bar with three segments
- New function: `_read_transcript_cache_metrics(session_id)` — tail JSONL, extract cache fields, compute trailing window
- New function: `_estimate_static_overhead(state)` — measure file sizes, count tools/skills
- New function: `_resolve_transcript_path(session_id)` — find the active transcript JSONL
- `DEFAULT_THEME["context_bar"]` — add new config keys

**`src/obs_utils.py`:**
- New function: `generate_overhead_report(package_root, transcript_path)` — called by session-end hook
- Writes `derived/overhead_report.json`

### Files Created

None. All changes integrate into existing modules.

### Test Additions

New fixture files:
- `tests/fixtures/statusline/valid-with-cache-metrics.json` — payload + simulated cache data
- `tests/fixtures/statusline/valid-cache-busting.json` — cache miss scenario

New test cases:
- Dual-bar rendering at 0%, 25%, 50%, 75%, 100% system overhead ratios
- Bar segment count matches width (no off-by-one in segment allocation)
- Threshold state selection (system vs total, whichever is more severe)
- Cache health state transitions (healthy → degraded → busting)
- `⚡` suffix rendering when cache_busting = true
- Fallback cascade: Phase 2 → Phase 1 → single-color
- Static estimator with missing files (graceful degradation)
- Transcript tailing with malformed JSONL lines (skip, don't crash)
- 30-second cache respects staleness threshold
- Config override for all new keys
- `overhead_source = "off"` produces identical output to current behavior

### Out of Scope

- No new MCP tools or servers
- No changes to existing obs hooks (they already capture needed data)
- No external dependencies
- No API calls to Anthropic's token counting endpoint
- No changes to the status line payload schema (we work with what Claude Code provides)
- No multi-line layout changes (this augments the existing context_bar pill)

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Transcript JSONL format changes between Claude Code versions | Phase 2 data becomes unavailable | Fallback cascade to Phase 1; defensive parsing with try/except per line |
| Transcript file locked by Claude Code during writes | Read failure or partial data | Read with `O_RDONLY`, handle truncated last line, cache last-good values |
| Static estimate diverges significantly from measured values | Misleading display on turn 0 | Cross-validate when Phase 2 data arrives; log drift for calibration |
| Cache fields absent in transcript (older Claude Code versions) | No cache health data | Graceful fallback to single-color bar; `overhead_source = "off"` escape hatch |
| Performance impact of JSONL tailing on large transcripts | Status line exceeds 200ms budget | Read only tail of file (seek to last 50KB); 30s cache prevents repeated reads |

## References

- [Anthropic prompt caching docs](https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching)
- [Claude Code source leak analysis (March 31, 2026)](https://venturebeat.com/technology/claude-codes-source-code-appears-to-have-leaked-heres-what-we-know)
- [Cache busting bug analysis](https://smartscope.blog/en/blog/claude-code-token-consumption-cache-bug/)
- [MCP token overhead measurements (GitHub #3406)](https://github.com/anthropics/claude-code/issues/3406)
- [Compaction death spiral (GitHub #24677)](https://github.com/anthropics/claude-code/issues/24677)
- [Cache read overhead analysis (GitHub #24147)](https://github.com/anthropics/claude-code/issues/24147)
- [Anthropic advanced tool use engineering blog](https://www.anthropic.com/engineering/advanced-tool-use)
- qLine existing specs: `docs/superpowers/specs/2026-03-15-qline-visual-design.md`, `2026-03-15-qline-expansion-design.md`
- Token optimization audit: `/home/q/docs/specs/2026-03-30-token-optimization-design.md`
