# Context Overhead Monitor — Design Spec

**Date:** 2026-04-04
**Status:** Approved (revised after council review)
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

**Edge case — system critical, conversation zero (turn 1):** When system overhead >= 50% but conversation is 0, the bar renders as all-`█` (full blocks) with no `▓` segments, using the `!` suffix. Example: `󰋑 █████░░░░░ 50%!`

### Cache Health Indicator

Cache health overlays the threshold behavior using a **compound suffix** when multiple conditions are active:

- `%⚡` — cache busting detected, thresholds normal
- `%~⚡` — cache busting AND warn threshold exceeded
- `%!⚡` — cache busting AND critical threshold exceeded

Cache health indicators are **only shown when `source == "measured"`** (Phase 2 data available). During Phase 1 (static estimate), no cache health indicator is displayed — there is no cache data to evaluate.

### Display Examples

```
󰋑 █▓░░░░░░░░  8%      healthy: small system footprint, light conversation
󰋑 ███▓▓░░░░░ 22%      normal: moderate system, growing conversation
󰋑 ████▓▓▓░░░ 42%~     warn: total usage crossing 40%
󰋑 ██████▓░░░ 38%~     warn: system alone is 35% (sys_warn_threshold)
󰋑 ██████▓▓░░ 65%!     critical: system eating most of the window
󰋑 █████░░░░░ 50%!     critical: system alone at 50%, no conversation yet
󰋑 ███▓▓▓░░░░ 31%⚡    cache busting detected, usage normal
󰋑 ██████▓▓░░ 72%!⚡   cache busting AND critical usage — worst case
```

### Bar Segment Allocation Formula

Given `width` (default 10), compute segments using fill-last-segment to prevent rounding drift:

```python
total_pct = (context_used * 100) // context_total
sys_pct = (sys_overhead * 100) // context_total  # clamped to [0, total_pct]
conv_pct = total_pct - sys_pct

filled = (total_pct * width) // 100
sys_blocks = (sys_pct * width) // 100
sys_blocks = min(sys_blocks, filled)              # can never exceed filled
conv_blocks = filled - sys_blocks                 # remainder of filled portion
free_blocks = width - filled                      # always exact via subtraction
```

`conv_blocks` is derived by subtraction, never by independent rounding. This guarantees `sys_blocks + conv_blocks + free_blocks == width` in all cases.

When `context_used == 0`: `filled = 0`, `sys_blocks = 0`, `conv_blocks = 0`, `free_blocks = width`. The bar renders as all-`░`. No division by `context_used` occurs anywhere — the system ratio is computed against `context_total`, not `context_used`.

When `sys_overhead > context_total` (estimator over-count): clamp `sys_overhead` to `context_total` before computing `sys_pct`.

## Data Architecture

### Phase 1 — Static Bootstrap (Turn 0)

Before any API response is available, estimate system overhead from measurable sources on the local filesystem.

| Source | Method | Typical Tokens |
|--------|--------|---------------|
| CLAUDE.md files | `os.stat()` byte size × 0.325 (tokens/byte) | 1k-28k |
| Claude Code system prompt | Fixed constant (validated against source leak) | ~4k |
| Deferred tool names | Count names × 12 tokens/name (empirical average) | 2k-5k |
| Active MCP tool schemas | Count MCP servers × avg schema tokens (empirical) | 5k-50k |
| Skill stubs | Count stubs × 30 tokens/stub (empirical average) | 2k-4k |

The byte-to-token ratio of 0.325 (≈1 token per 3.1 bytes) accounts for subword tokenization overhead. Count-based sources (deferred tools, skill stubs) use empirical per-item averages instead — the byte ratio does not apply to them.

This estimate is a **lower bound**. Real overhead includes content we cannot measure externally (anti-distillation injected tools, internal scaffolding, attestation data).

The static estimate is computed once and **cached in `_obs[session_id]`** with a 60-second TTL. The underlying files (CLAUDE.md, MCP schemas) do not change mid-session, so re-computation is unnecessary.

Stored as `state["sys_overhead_estimate"]`.

### Phase 2 — Measured Steady-State (Turn 1+)

#### Data Source

Read the session transcript JSONL. The path is obtained from the `transcript_path` field in the status line payload (confirmed present in `valid-full.json` fixture). If `transcript_path` is absent from the payload, fall back to constructing the path as `~/.claude/projects/<project>/<session_id>.jsonl`.

Extract `transcript_path` in `normalize()`:

```python
transcript_path = payload.get("transcript_path")
if isinstance(transcript_path, str) and transcript_path:
    state["transcript_path"] = transcript_path
```

#### Transcript Entry Format

Each API response in the transcript contains usage fields:

```json
{
  "cache_read_input_tokens": 95000,
  "cache_creation_input_tokens": 250,
  "input_tokens": 1200,
  "output_tokens": 443,
  "cache_creation": {
    "ephemeral_1h_input_tokens": 250,
    "ephemeral_5m_input_tokens": 0
  }
}
```

**Important transcript parsing rules:**

1. **Two entries per logical turn.** The transcript emits a streaming stub (`stop_reason: null`) followed by a final entry (`stop_reason: "end_turn"` or other non-null value). Only process entries with non-null `stop_reason`.

2. **Two usage locations.** Usage appears at `entry.message.usage` for direct assistant turns and at `entry.toolUseResult.usage` for subagent completions. The reader must check both paths.

#### Why `cache_read_input_tokens` Is NOT System Overhead

**Critical correction from council review:** The cached prefix grows every turn because conversation history is cached alongside system content. Real data from GitHub #34629:

```
Turn 1: cache_read = 13,997    (system only — cold start)
Turn 2: cache_read = 32,849    (system + turn 1 conversation)
Turn 3: cache_read = 36,846    (system + turns 1-2)
Turn 4: cache_read = 37,295    (system + turns 1-3)
```

Using `cache_read` directly as system overhead would progressively over-report system tokens and under-report conversation — the exact opposite of the intended display.

#### First-Turn Anchoring

The correct approach: **capture the system overhead measurement once on turn 1, hold it constant for the session.**

On the first API response (turn 1), `cache_creation_input_tokens` represents the full prompt prefix being cached for the first time. At turn 1, conversation content is minimal (just the first user message), so this value closely approximates system overhead.

```
sys_overhead = turn_1_cache_creation_input_tokens  (captured once, held as session constant)
conv_tokens  = context_used - sys_overhead
```

This value is stored in the cache and never updated — system overhead does not change mid-session (tool definitions, CLAUDE.md, and skills are loaded at startup and remain constant).

**Turn 1 includes the first user message** (~50-200 tokens typically). This means the anchored value slightly over-estimates system overhead. This is acceptable — the error is small (< 1% of typical overhead) and consistent.

#### Derived Metrics

Computed per status update from the trailing window of available turns:

| Metric | Derivation |
|--------|-----------|
| `sys_overhead` | `turn_1_cache_creation` (anchored constant for session) |
| `conv_tokens` | `context_used - sys_overhead` (clamped to >= 0) |
| `cache_hit_rate` | `sum(cache_read) / sum(cache_read + cache_creation)` over trailing 5 turns |
| `cache_busting` | `True` when `cache_hit_rate < cache_critical_rate` (default 0.3) AND at least 3 turns of data exist |

**Unified cache busting definition:** Cache busting is determined solely by `cache_hit_rate < cache_critical_rate` over the trailing window. The earlier "3 consecutive turns with `cache_creation > cache_read`" formulation is removed — a single threshold on the aggregate rate is simpler and avoids definition conflicts.

#### Cold-Start Behavior

- **Fewer than 2 turns:** No cache health indicator displayed. Insufficient data for meaningful rate calculation.
- **2-4 turns:** Cache hit rate computed over available turns. Cache busting flag requires at least 3 turns of data before it can activate (debounce against turn-1 cold cache).
- **5+ turns:** Full trailing window active.

#### Compaction Handling

When a compaction occurs, the context window resets. `cache_read_input_tokens` drops to near-zero and rebuilds over 2-3 turns. This looks identical to cache busting but is expected, legitimate behavior.

Detection: if `obs_compactions` (already available in state from obs counters) increased since the last status update, reset the trailing window and suppress cache health indicators for 3 turns. This prevents false `⚡` alarms after every compaction.

### Fallback Cascade

1. Transcript JSONL available with cache fields → Phase 2 (measured values)
2. Transcript JSONL missing or cache fields absent → Phase 1 (static estimate, no cache health indicator)
3. Neither available → render single-color bar (current behavior, no degradation)

### Caching

Transcript metrics are read on the same 30-second interval as existing obs modules. Parsed values are stored in `/tmp/qline-cache.json` **inside the `_obs[session_id]` namespace** alongside existing obs counters. This shares the cache load/save round-trip with `_inject_obs_counters`, avoiding a second atomic rename.

Cache entry structure within `_obs[session_id]`:

```json
{
  "overhead_ts": 1712234567.0,
  "sys_overhead_tokens": 42000,
  "sys_overhead_source": "measured",
  "turn_1_anchor": 42000,
  "cache_hit_rate": 0.91,
  "cache_busting": false,
  "compaction_suppress_until_turn": 0,
  "trailing_turns": [
    {"cache_read": 95000, "cache_create": 250, "input": 1200, "turn": 12},
    {"cache_read": 95200, "cache_create": 0, "input": 1800, "turn": 13}
  ],
  "session_accum": {
    "total_cache_read": 4465000,
    "total_cache_create": 12500,
    "total_fresh_input": 56400,
    "cache_busting_turns": [12, 13, 14],
    "peak_usage_pct": 72.4,
    "peak_sys_pct": 41.0,
    "total_turns": 47
  }
}
```

The `session_accum` object provides running session-level aggregates for the forensics report. This data survives crashes — even if `session-end` never runs, the most recent cache entry contains enough data to generate a partial report.

Staleness threshold: 60 seconds. If cached data is older, re-read transcript.

## Cache Health Detection

Three states, derived from `cache_hit_rate` over the trailing turn window:

### Healthy (`cache_hit_rate >= 0.8`)

System prefix is stable and being cached. Dual-bar renders normally. No additional indicator.

Note: threshold uses `>=` (not `>`) — a hit rate of exactly 0.8 is healthy.

### Degraded (`0.3 <= cache_hit_rate < 0.8`)

Something is intermittently invalidating the cache — possibly tool definition changes, skill loads mid-session, or MCP server reconnections. Suffix uses the warn convention (`~`). The system overhead segment uses warn color.

### Cache Busting (`cache_hit_rate < 0.3`, with at least 3 turns of data)

Active, sustained cache invalidation. Known causes from the March 2026 bugs:
- Attestation data changing per request
- Anti-distillation fake tool injection varying between requests
- Bun fork sentinel string replacement hitting conversation content

Suffix includes `⚡` (compounded with threshold suffix if applicable). Entire bar uses critical color. This is the "your tokens are burning 10-20x faster" alarm.

### State Machine Preconditions

- **Phase 1 (estimated data):** No cache health indicator. The `⚡`, `~` (cache), and degraded states are all suppressed.
- **Fewer than 2 turns of Phase 2 data:** No cache health indicator.
- **Within 3 turns of a compaction event:** Cache health indicator suppressed (compaction resets are expected).

## Post-Session Forensics

When the session ends, the existing `obs-session-end.py` hook generates an overhead report as a derived artifact in the session package:

```
~/.claude/observability/sessions/<date>/<session_id>/derived/overhead_report.json
```

The report is generated by **re-reading the full transcript JSONL** (not from the trailing window cache). This makes it crash-tolerant — the transcript is the source of truth and persists regardless of whether session-end runs. If session-end does not run (crash), the `session_accum` data from the qline cache serves as a partial fallback.

Contents:

```json
{
  "session_id": "abc123",
  "total_turns": 47,
  "system_overhead_tokens": 42000,
  "system_overhead_source": "first_turn_anchor",
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

## Architecture

### Separation of Concerns

**Renderers are pure functions.** Following the existing pattern where `render_*` functions receive `(state, theme)` and return strings with no I/O, all data collection happens before rendering:

- `_inject_context_overhead(state, payload)` — new function called from `main()` between `collect_system_data()` and `render()`. Handles transcript tailing, static estimation, cache health computation. Populates state keys consumed by the renderer.
- `render_context_bar(state, theme)` — modified to read pre-populated state keys (`sys_overhead_tokens`, `cache_busting`, `cache_hit_rate`, `sys_overhead_source`) and render the dual-bar. No I/O.

This preserves test isolation: the existing test harness tests renderers by feeding pre-built state dicts with `QLINE_NO_COLLECT=1`.

### State Keys Populated by `_inject_context_overhead`

| Key | Type | Source | Description |
|-----|------|--------|-------------|
| `sys_overhead_tokens` | int | Phase 1 or 2 | System overhead token count |
| `sys_overhead_source` | str | — | `"measured"` or `"estimated"` |
| `cache_hit_rate` | float \| None | Phase 2 only | 0.0-1.0, None if insufficient data |
| `cache_busting` | bool | Phase 2 only | True when rate < critical threshold |
| `transcript_path` | str \| None | payload | Path to session transcript JSONL |

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
- `normalize()` — extract `transcript_path` from payload into state
- `render_context_bar()` — rewrite to render dual-color bar with three segments using pre-populated state keys (remains a pure function, no I/O)
- New function: `_inject_context_overhead(state, payload)` — called from `main()`, handles Phase 1/2 data collection, cache health computation
- New function: `_read_transcript_cache_metrics(transcript_path, session_cache)` — tail JSONL, extract cache fields, compute trailing window
- New function: `_estimate_static_overhead(state)` — measure file sizes, count tools/skills
- `DEFAULT_THEME["context_bar"]` — add new config keys

**`src/obs_utils.py`:**
- New function: `generate_overhead_report(package_root, transcript_path)` — called by session-end hook, re-reads full transcript
- Writes `derived/overhead_report.json`

### Files Created

None. All changes integrate into existing modules.

**Note on file growth:** `statusline.py` will grow by approximately 150-200 lines (from ~1548 to ~1750). If it exceeds 1800 lines after implementation, extract `_inject_context_overhead` and its helpers into `src/context_overhead.py` as a dedicated module.

### Test Additions

New fixture files:
- `tests/fixtures/statusline/valid-with-cache-metrics.json` — payload with `transcript_path` + simulated cache data in state
- `tests/fixtures/statusline/valid-cache-busting.json` — cache miss scenario
- `tests/fixtures/statusline/valid-overhead-estimated.json` — Phase 1 estimated state (no cache health keys)

New test cases:
- Dual-bar rendering at 0%, 25%, 50%, 75%, 100% system overhead ratios
- Bar segment formula: `sys_blocks + conv_blocks + free_blocks == width` for all inputs
- `sys_blocks` never exceeds `filled`; `conv_blocks` never negative
- `context_used == 0` produces all-`░` bar (no division errors)
- `sys_overhead > context_total` clamped correctly
- Threshold state selection: system critical + total normal → critical wins
- Edge case: system 50%, conversation 0 → all-`█`, `!` suffix
- Cache health state transitions: healthy → degraded → busting
- Compound suffixes: `%⚡`, `%~⚡`, `%!⚡` all render correctly
- Cache health suppressed during Phase 1 (`source == "estimated"`)
- Cache health suppressed with fewer than 2 turns of data
- Compaction suppression: `⚡` not shown for 3 turns after compaction
- Fallback cascade: Phase 2 → Phase 1 → single-color
- Static estimator with missing files (graceful degradation)
- Static estimator cached at 60s TTL (not re-run every invocation)
- Transcript tailing: only process entries with non-null `stop_reason`
- Transcript tailing: handle both `message.usage` and `toolUseResult.usage` paths
- Transcript tailing with truncated last line (mid-write) — skip, don't crash
- Transcript tailing with malformed JSONL lines — skip, don't crash
- 30-second cache respects staleness threshold
- `_inject_context_overhead` populates state; `render_context_bar` has no I/O (test isolation)
- Config override for all new keys
- `overhead_source = "off"` produces identical output to current behavior
- `overhead_source = "measured"` with no transcript → single-color fallback
- Phase 1 → Phase 2 transition: bar updates smoothly, cache health appears
- `⚡` with NO_COLOR=1: UTF-8 literal renders in plain text mode
- First-turn anchoring: `turn_1_anchor` captured once and held constant
- Concurrent session isolation: different `session_id` keys don't interfere

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
| Transcript file locked by Claude Code during writes | Read failure or partial data | Read with `O_RDONLY`, handle truncated last line as partial JSON (skip, cache last-good values) |
| Static estimate diverges significantly from measured values | Misleading display on turn 0 | Cross-validate when Phase 2 data arrives; log drift for calibration |
| Cache fields absent in transcript (older Claude Code versions) | No cache health data | Graceful fallback to single-color bar; `overhead_source = "off"` escape hatch |
| Performance impact of JSONL tailing on large transcripts | Status line exceeds 200ms budget | Read only tail of file (seek to last 50KB); 30s cache prevents repeated reads |
| Compaction events trigger false cache-busting alarm | Misleading `⚡` indicator | Check `obs_compactions` delta; suppress cache health for 3 turns post-compaction |
| Concurrent status hook invocations for parallel sessions | Cache write race on `/tmp/qline-cache.json` | Existing `os.rename()` atomic replace semantics on Linux are sufficient; data is scoped by `session_id` keys |
| Turn-1 anchor slightly over-estimates overhead (includes first user message) | System bar ~50-200 tokens too wide | Acceptable error (< 1% of typical overhead); consistent bias is preferable to noisy estimation |
| `transcript_path` absent from payload | Cannot locate transcript for Phase 2 | Fall back to path construction from `session_id` + known directory pattern; then to Phase 1 |

## Council Review Log

Revised 2026-04-04 based on review by 4 specialist agents:

1. **Architecture reviewer** — identified renderer purity violation, unnecessary path resolver, compaction false alarms, cache namespace scoping, static estimator caching need
2. **Transcript format verifier** — confirmed cache fields exist in real transcripts, discovered two-entry-per-turn streaming pattern, dual usage paths (`message.usage` / `toolUseResult.usage`), additional fields (`cache_creation.ephemeral_*`)
3. **Edge case reviewer** — identified `⚡` hiding critical threshold (now compound suffix), Phase 1 false alarms (now suppressed), cache state boundary errors (now `>=`), bar rounding formula gaps (now specified), forensics crash resilience (now re-reads transcript)
4. **Cache metrics validator** — **identified fundamental flaw**: `cache_read_input_tokens` grows with conversation history, not system-only. Redesigned Phase 2 around first-turn anchoring using `cache_creation_input_tokens` at turn 1.

## References

- [Anthropic prompt caching docs](https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching)
- [Claude Code source leak analysis (March 31, 2026)](https://venturebeat.com/technology/claude-codes-source-code-appears-to-have-leaked-heres-what-we-know)
- [Cache busting bug analysis](https://smartscope.blog/en/blog/claude-code-token-consumption-cache-bug/)
- [Claude Code cache regression (GitHub #34629)](https://github.com/anthropics/claude-code/issues/34629)
- [MCP token overhead measurements (GitHub #3406)](https://github.com/anthropics/claude-code/issues/3406)
- [Compaction death spiral (GitHub #24677)](https://github.com/anthropics/claude-code/issues/24677)
- [Cache read overhead analysis (GitHub #24147)](https://github.com/anthropics/claude-code/issues/24147)
- [Anthropic advanced tool use engineering blog](https://www.anthropic.com/engineering/advanced-tool-use)
- qLine existing specs: `docs/superpowers/specs/2026-03-15-qline-visual-design.md`, `2026-03-15-qline-expansion-design.md`
- Token optimization audit: `/home/q/docs/specs/2026-03-30-token-optimization-design.md`
