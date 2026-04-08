# qLine Optimization Session Handoff — 2026-04-07

## Session Summary

Single-session research-to-implementation cycle covering accuracy fixes, freshness improvements, duplicate consolidation, and layout redesign. All work landed on `main` at `/Users/q/LAB/qLine`.

---

## What Was Done

### 1. Research Phase (7 tracks, spec-reviewed)

Full research tree at `docs/superpowers/specs/2026-04-07-qline-optimization/`:

| Track | Deliverable | Key Finding |
|-------|-------------|-------------|
| T0 | Baseline & repo truth | 38 test failures classified (14 harness, 9 fixture, 7 rendering, 6 logic, 2 path). 7 must-fix items gating further work. |
| TX | Data contracts | 5 hook event names were wrong in the spec (corrected against source). stdin fields verified against `normalize()`. `session_inventory.json` added to package layout contract. |
| T1 | Accuracy audit | 8 accuracy gaps found. **AG-01 is critical**: `obs-stop-cache.py` writes per-turn `cache_create` (973-2406 tokens) as `cache_anchor` in manifest, but `_read_manifest_anchor()` treats it as system overhead (~37k tokens). Replay dataset built (58 files in `tests/replay/`). |
| T2 | Real-time freshness | Pipeline completes in **under 4ms** even on XL sessions (2440 events, 1.2MB JSONL). The 30-second cache TTL was the sole meaningful freshness limiter — not transcript reading. Strategy A-prime (reduce TTL to 5s) recommended. |
| T3 | Observability expansion | 32 data sources inventoried (was 17 in spec). 15 visibility gaps identified. 8 schema proposals with dependency classifications. Highest-ROI: session resume signal (10 lines, uses existing `session.reentry` events). |
| T4 | External scan | 24 surfaces classified: 17 supported, 1 observed-stable, 4 fragile, 2 speculative. 18 relevant GitHub issues found. Transcript JSONL schema is undocumented (UR-01, highest risk). |
| T5 | Experiment matrix | 27 opportunities ranked and scored. Implementation backlog: 7 Tier 1 (safe additive), 15 Tier 2 (needs migration), 4 Tier 3 (upstream dependent). 3 recommended paths produced. |

### 2. Implementation (4 fixes)

| Fix | File | Change | Impact |
|-----|------|--------|--------|
| **AG-01**: Manifest anchor priority | `context_overhead.py:494-510` | Swap priority: `_read_transcript_anchor()` checked first, `_read_manifest_anchor()` as fallback | Critical: anchor was 973-2406 (wrong) → 37k-52k (correct) |
| **AG-02**: Warning threshold formula | `context_overhead.py:699` | `warning = effective - CC_WARNING_OFFSET` (was `autocompact`) | Major: warning==error (both 147k) → 13k gap restored |
| **MV-10**: Session resume signal | `statusline.py:1922-1927` | Detect `session.reentry` count increase, clear `overhead_ts` and `turn_1_anchor` | Eliminates 30s+ stale data on resume |
| **A-prime**: Cache TTL 30s→5s | `statusline.py:1905`, `context_overhead.py:769` | Two constants changed | 6x freshness, sub-4ms cost proven |

### 3. Duplicate Consolidation (9 tasks, ~150 lines removed)

Full report at `docs/superpowers/specs/2026-04-07-qline-optimization/duplicate-report.md`.
Implementation plan at `docs/superpowers/plans/2026-04-07-qline-dedup-consolidation.md`.

**Shared functions created:**

| Function | Location | Replaces |
|----------|----------|----------|
| `resolve_task_list_id(session_id)` | `hook_utils.py:116` | Exact clones in precompact-preserve + session-end-summary |
| `find_latest_plan()` | `hook_utils.py:128` | Near-clones in same two files |
| `iter_open_tasks(session_id)` | `hook_utils.py:144` | Two independent task-dir-reading implementations |
| `hash16(s)` | `hook_utils.py:172` | 1 function + 4 inline `sha256[:16]` copies |
| `now_iso()` | `hook_utils.py:18` | 6 inline `datetime.now(timezone.utc).isoformat()` calls |
| `resolve_package_root_env(session_id)` | `obs_utils.py:216` | 14-site 3-line OBS_ROOT boilerplate |
| `load_manifest(package_root)` | `obs_utils.py:384` | Local `_load_manifest` in obs-session-end |
| `extract_usage_full(entry)` | `obs_utils.py:562` | Semantic dup between context_overhead + obs-stop-cache |

**Dependency direction:** `hook_utils` is primitive (no imports from obs_utils at module level). `obs_utils` imports `now_iso` from `hook_utils`. One lazy import: `_write_ledger_record` tries `obs_utils._atomic_jsonl_append` with direct-write fallback.

### 4. Simplify Pass

Post-consolidation cleanup from 4-agent review:
- Hoisted `glob`, `hashlib` imports to module level (was per-call deferred)
- Hoisted `_atomic_jsonl_append` import to module level with `try/except ImportError`
- Renamed `_now_iso` → `now_iso` (was private-named but cross-module public)
- Removed unused `log_hook_diagnostic` import from `precompact-preserve.py`
- Added PEP 8 blank line before `extract_usage_full`
- Simplified `resolve_package_root_env`: direct call instead of kwargs dict
- `obs-session-end.py`: load manifest once, pass to `validate_finalization` and `generate_session_summary`

### 5. Layout Redesign (compact 3-line)

New default layout:

```
Line 1: 󰚩 Opus4.6[1M]│▲71.4k│▼484k│█▓▓▓▓▓▓▓▓▓▓░░░░░░󰋑79%│󰓅99%│󰥔3h30m
Line 2: 󰑖17.1k™│©307k™|󰍻 +454™│󰑇475│®84%│󰙏207│󰆍349│󰅺31│󰌘20│󰀦35│󰕥│󰔠x516│$68.37|19.47/hr
Line 3: 󰝰 qLine│main@30edbac│󰓌 ░░░░░7%│󰍛 ██░░░55%│󰋊 █░░░░24%
```

Changes from prior layout:
- Model: full name + context window size `[1M]`
- Token counts: `▲input│▼output` before bar (was pills after)
- Context bar: unbracketed, dual-fill `█▓░` (overhead/conversation/free)
- Cache rate `󰓅` on line 1
- Duration compact: `3h30m` (no spaces, no leading 0)
- Line 2: all obs + overhead + cost on one line, tight `│` separators
- Two `|` (pipe) separators: after cache read, after cost
- Line 3: system bars tight `░░░░░7%` (no space before %)
- Compactions glyph changed to `󰔠` (F0520)

---

## What's Left / Unfinished / Deferred

### From T5 Backlog — Not Yet Implemented

**Tier 1 (Safe Additive) — 7 items remaining:**
- OPP-15: Package schema version in manifest (`schema_version: "1.0.0"`)
- OPP-18: Hook fault surfacing (surface `~/.claude/logs/lifecycle-hook-faults.jsonl` in statusline)
- OPP-12: Hook performance sidecar (`hook_perf.jsonl`)
- OPP-16: Compaction anchor invalidation event (`compact.anchor_invalidated`)
- OPP-17: Hook coverage report (additive section in `session_inventory.json`)
- OPP-14: Parse diagnostic sidecar (`native/statusline/diagnostics.jsonl`)
- OPP-25: Transcript schema validation in tests

**Tier 2 (Needs Migration) — 11 items remaining:**
- OPP-06: MCP server fallback to 0 (currently defaults to 5 when unreadable)
- OPP-05: Configurable context correction (CC vs qLine divergence)
- OPP-07: Tune cache decay constant (re-evaluate after AG-01 fix)
- OPP-03: Static overhead calibration (8.5% underestimate, apply 1.08x factor?)
- OPP-20: Remove `conversation` dict dependency (fragile, undocumented)
- OPP-21/22: CC internal constants version-tagging
- OPP-27: Stop hook reliability fallback
- OPP-10: Seq-based cache invalidation (Strategy B — Phase 2 follow-on after A-prime)
- OPP-13: Source freshness manifest keys
- OPP-24: `current_usage` top-level fallback documentation

**Tier 3 (Upstream Dependent) — 4 items:**
- OPP-19: Reduce transcript JSONL dependency (blocked by undocumented format)
- OPP-04: Manifest anchor staleness after compaction
- OPP-23: Compaction staleness marker for statusline
- OPP-26: Version-tagged transcript parsing

### From T0 — Test Failures Not Fixed

40 pre-existing test failures remain (was 43 at start, down to 40 after layout changes):
- 14 harness portability (bash 3.2 `$'\U...'` escapes, macOS `wc -l` padding, `mktemp --suffix`)
- 9 fixture drift (glyph changes `↑/↓` vs `▲/▼`, duration format, wrong function calls)
- 7 rendering regression (extra line, cache-busting suffix format, color formula)
- 6 logic defect (legacy stubs, calibration drift, threshold config) — **AG-01 and AG-02 were the top 2; both fixed**
- 2 path assumption (`obs_utils` not on sys.path, hardcoded hook location)

### From Duplicate Report — Not Consolidated

- **L3**: `render_obs_*` structural similarity — 7 nearly-identical counter renderers could use a factory pattern (~60 lines recoverable). Deferred as architectural.
- `generate_overhead_report` in `obs_utils.py` still has inline extraction that bypasses `extract_usage_full` — should be wired through the shared function.
- `statusline.py` has a compatibility shim for `resolve_package_root_env` (inline fallback if import fails) — can be removed once minimum obs_utils version is guaranteed.

### Alert/Warning System — Not Audited

The alert banner system in `render_context_bar()` (lines 826-946) has 8 triggers:
1. `cache_busting` — cache miss every turn
2. `cache_expired` — idle timeout
3. `microcompact_suspected` — tool results silently cleared
4. `bloat` — system overhead >50% of context
5. `heavy` — approaching autocompact
6. `compact` — ≤10 turns until compact
7. `turns` — ≤50 turns until compact
8. `cache_degraded` — partial cache misses

**Status:** Triggers are **more accurate now** because AG-01 (anchor) and AG-02 (thresholds) are fixed. But the trigger thresholds, message accuracy, and banner behavior have NOT been formally audited. The `turns_until_compact` calculation depends on `avg_growth` from trailing window, which may be noisy. The `microcompact_suspected` heuristic (drop ratio < 0.5 and abs_drop > 5000) is based on observed patterns, not verified against CC source.

The 5-second banner → glyph-only collapse uses `/tmp/qline-alert.json` for onset tracking (persists across statusline invocations). This file is never cleaned up.

---

## Key Nuances for Future Work

### Architecture

- **Single-file statusline**: `src/statusline.py` is the entire renderer (~2100 lines). No pip dependencies. `context_overhead.py` is the only import from `src/`. All hooks are separate Python scripts.
- **Deployment**: `~/.claude/statusline.py` is a standalone COPY (not symlink). Must be manually updated with `cp src/statusline.py ~/.claude/statusline.py`. Hooks use a symlink via `~/.claude/plugins/qline → /Users/q/LAB/qLine`.
- **Fail-open contract**: Every hook and the statusline itself must exit 0 always. Exceptions are caught and swallowed. Diagnostics go to fault ledger.
- **Two data paths**: Statusline reads stdin JSON → renders ANSI. Hooks write to session packages → statusline reads packages for obs data.

### Known Fragile Dependencies (from T4)

- **Transcript JSONL format** (UR-01, High risk): undocumented, could change without notice. `_read_transcript_tail()` and `_read_transcript_anchor()` depend on it.
- **CC internal constants** (UR-02): `CC_OUTPUT_RESERVE=20000`, `CC_AUTOCOMPACT_BUFFER=13000`, `CC_WARNING_OFFSET=20000`, `CC_ERROR_OFFSET=20000` extracted from decompiled CC v2.1.92. Any CC update can change these.
- **Stop hook reliability** (UR-05): Issues #29881, #33712, #40029 — Stop hook sometimes fails to fire.
- **Session ID resume stability** (UR-03): Not documented whether session_id persists on resume/continue.

### Context Overhead Subtleties

- **`context_used_corrected`** adds output tokens to CC's `used_percentage`-derived value. This can push the bar past 100% if the payload has contradictory values. The correction is intentional (CC's `used_percentage` may exclude output tokens) but can be surprising.
- **Warm cache detection**: If `turn_1_anchor < 5000`, qLine assumes a warm restart and looks for `cache_read_input_tokens` instead. This threshold is hardcoded.
- **Calibration ratio**: Compares static estimation vs measured anchor. After AG-01 fix, this should approach 1.0 for fresh sessions. If it drifts, the static estimation constants need updating.

### Test Infrastructure

- Test harness is `tests/test-statusline.sh` — a bash script with 235 assertions
- Replay dataset at `tests/replay/` — 58 files (12 from existing fixtures, 5 real sessions, 3 transcripts, 6 synthetic edge cases)
- Latency benchmark at `tests/t2_latency_benchmark.py` — measures per-segment pipeline timing
- Tests run with `NO_COLOR=1 QLINE_NO_COLLECT=1` to disable system collection and ANSI codes

### Config

All modules controlled via `~/.config/qline.toml`. Current config enables all obs modules. The `[layout]` section can override line composition. The `DEFAULT_LINE1/2/3` arrays in statusline.py define the default module ordering.

---

## Git State

- **Branch**: `main`
- **HEAD**: Latest merge commit with all research + implementation + consolidation + layout
- **Remote**: `https://github.com/LucasQuiles/qLine.git` — not pushed in this session
- **Stale clone**: `/Users/q/qline` on `experiment/apr04-overhead-cache-sharpening` — ignored, not synced
