# qLine Next Phase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address remaining Tier 2 backlog items, resolve known code quality debt, and harden the cache/overhead pipeline.

**Architecture:** Three independent tracks: (A) cache layer consolidation to eliminate the 3x load + 5x save per invocation, (B) Tier 2 accuracy/fragility improvements, (C) dead code cleanup. Each track produces working, testable software independently.

**Tech Stack:** Python 3.10+, bash test harness, no external dependencies.

---

## Current State (post 2026-04-08 session)

- **47 commits** on main, **300/300 tests**, **41 modules**, **191 functions**, 0 duplicates
- All Tier 1 OPP items (7/7) implemented
- Alert system audited, thresholds corrected (75/90% fallback)
- Runtime invariant checker active with `QLINE_DEBUG=1`
- Stale import safeguards in place
- Width-aware line wrapping with overflow distribution

## Remaining Backlog

### Track A: Cache Layer Consolidation (3 tasks)

The cache is loaded 3 times and saved up to 5 times per invocation. This adds ~10 unnecessary filesystem syncs.

### Task 1: Single load_cache per invocation

**Files:**
- Modify: `src/statusline.py` — `main()`, `collect_system_data()`, `_inject_obs_counters()`, `_try_obs_snapshot()`

**Current:** Each function calls `load_cache()` independently. The cache dict is read from `/tmp/qline-cache.json` 3 times per invocation.

**Change:** Load cache once in `main()`, pass as parameter to all consumers.

- [ ] **Step 1:** Add `cache` parameter to `collect_system_data(state, theme, cache=None)`
- [ ] **Step 2:** Add `cache` parameter to `_inject_obs_counters(state, payload, cache=None)`
- [ ] **Step 3:** Add `cache` parameter to `_try_obs_snapshot(payload, state, cache=None)`
- [ ] **Step 4:** In `main()`, call `cache = load_cache()` once and pass to all three
- [ ] **Step 5:** Each function uses passed cache if provided, falls back to `load_cache()` for backward compat
- [ ] **Step 6:** Run tests: `bash tests/test-statusline.sh` → 300/300
- [ ] **Step 7:** Commit

### Task 2: Single save_cache at end of _inject_obs_counters

**Files:**
- Modify: `src/statusline.py` — `_inject_obs_counters()`

**Current:** 5 separate `save_cache(cache)` calls at lines ~2522, ~2537, ~2548, ~2557, ~2829.

**Change:** Remove intermediate saves. Single `save_cache(cache)` at the end of the function, after all mutations. The function is already wrapped in `try/except Exception: pass`, so a crash just drops the update — same outcome as not saving intermediate.

- [ ] **Step 1:** Remove all `save_cache(cache)` calls except the last one
- [ ] **Step 2:** Add single `save_cache(cache)` before the state injection block (before `tr = session_cache.get(...)`)
- [ ] **Step 3:** Run tests → 300/300
- [ ] **Step 4:** Commit

### Task 3: Extract _write_jsonl_with_fallback helper

**Files:**
- Modify: `hooks/hook_utils.py`

**Current:** `_write_ledger_record` (line 61) and `_write_hook_perf` (line 102) share identical 9-line fallback pattern (try `_atomic_jsonl_append`, fall back to direct `os.open/os.write`).

**Change:** Extract `_write_jsonl_to(path, record)` and call from both.

- [ ] **Step 1:** Create `_write_jsonl_to(path, record)` with the shared fallback logic
- [ ] **Step 2:** Rewrite `_write_ledger_record` to call `_write_jsonl_to(_LEDGER_PATH, record)`
- [ ] **Step 3:** Rewrite `_write_hook_perf` to call `_write_jsonl_to(perf_path, record)`
- [ ] **Step 4:** Run tests → 300/300
- [ ] **Step 5:** Commit

---

### Track B: Tier 2 Accuracy & Fragility (5 tasks)

### Task 4: OPP-06 — MCP server fallback to 0

**Files:**
- Modify: `src/context_overhead.py` — `_estimate_static_overhead()`

**Current:** When MCP server count can't be read from settings.json, defaults to 5 (line ~189). This overestimates overhead on machines without MCP servers.

**Change:** Default to 0. If settings.json is readable, use actual count.

- [ ] **Step 1:** Change fallback from 5 to 0
- [ ] **Step 2:** Add test: verify estimate with no settings.json uses 0 MCP servers
- [ ] **Step 3:** Run tests → 300+/300+
- [ ] **Step 4:** Commit

### Task 5: OPP-05 — Configurable context correction toggle

**Files:**
- Modify: `src/statusline.py` — `normalize()`
- Modify: `src/statusline.py` — `DEFAULT_THEME["context_bar"]`

**Current:** `context_used_corrected` always adds `output_tokens` to CC's `used_percentage`. This can push past 100% and causes confusion.

**Change:** Add `include_output_in_context = true` config key. When false, skip the correction.

- [ ] **Step 1:** Add `"include_output_in_context": True` to `DEFAULT_THEME["context_bar"]`
- [ ] **Step 2:** In `normalize()`, check `theme` is not available at that point — instead, read the config key from env: `QLINE_INCLUDE_OUTPUT=0` disables correction
- [ ] **Step 3:** Add test: with env var off, `context_used_corrected` is not set
- [ ] **Step 4:** Commit

### Task 6: OPP-07 — Tune cache decay constant

**Files:**
- Modify: `src/context_overhead.py` — `_CACHE_DECAY`

**Current:** Decay constant is 0.7. After AG-01 fix, the cache hit rate calculation may be too aggressive in marking sessions as degraded.

- [ ] **Step 1:** Analyze real sessions: compute hit rates with decay 0.5, 0.6, 0.7, 0.8 from replay data
- [ ] **Step 2:** If 0.7 produces false degraded flags, adjust. If not, document why 0.7 is correct.
- [ ] **Step 3:** Add test with boundary conditions
- [ ] **Step 4:** Commit

### Task 7: OPP-20 — Remove conversation dict dependency

**Files:**
- Modify: `src/statusline.py` — `normalize()`

**Current:** `normalize()` may read from an undocumented `conversation` field in the payload. This field is fragile and could change without notice.

- [ ] **Step 1:** Audit all references to `conversation` in normalize()
- [ ] **Step 2:** Replace with documented alternatives or remove
- [ ] **Step 3:** Add test: payload without `conversation` produces same result
- [ ] **Step 4:** Commit

### Task 8: OPP-27 — Stop hook reliability fallback

**Files:**
- Modify: `src/statusline.py` — `_inject_obs_counters()`
- Modify: `src/context_overhead.py`

**Current:** When the Stop hook fails to fire (known CC bug), cache metrics go stale. No detection or mitigation.

**Change:** In `_inject_obs_counters`, detect stale cache by comparing `context_window` changes vs `cache.observed` event count. If context grew but no cache events, log a warning.

- [ ] **Step 1:** Add stale-cache detection: if `context_used` changed by >10k but `cache.observed` count hasn't changed, set `state["cache_stale_suspected"] = True`
- [ ] **Step 2:** Add visual indicator: dim the cache_rate module when stale suspected
- [ ] **Step 3:** Add test
- [ ] **Step 4:** Commit

---

### Track C: Dead Code & Quality Cleanup (3 tasks)

### Task 9: Remove dead render_bar function

**Files:**
- Modify: `src/statusline.py`
- Modify: `tests/test-statusline.sh`

**Current:** `render_bar` (line ~841) is superseded by `render_context_bar`. It's registered in `MODULE_RENDERERS` but never called from the layout. Only tests call it.

- [ ] **Step 1:** Remove `render_bar` function
- [ ] **Step 2:** Remove its `MODULE_RENDERERS` entry
- [ ] **Step 3:** Update tests that call `render_bar` to call `render_context_bar` instead
- [ ] **Step 4:** Run tests → 300/300
- [ ] **Step 5:** Commit

### Task 10: Hoist constants from _estimate_static_overhead

**Files:**
- Modify: `src/context_overhead.py`

**Current:** `_TOKENS_PER_SKILL_ITEM`, `_TOKENS_PER_AGENT_ITEM`, `_TOKENS_PER_COMMAND_ITEM` are defined as local variables inside the function, recreated on every call.

- [ ] **Step 1:** Move to module level alongside other `_TOKENS_PER_*` constants
- [ ] **Step 2:** Run tests → 300/300
- [ ] **Step 3:** Commit

### Task 11: Consolidate settings.json reads in _estimate_static_overhead

**Files:**
- Modify: `src/context_overhead.py`

**Current:** `settings.json` is opened twice in the same function — once for MCP servers, once for plugin counts.

- [ ] **Step 1:** Read and parse once, reuse the dict
- [ ] **Step 2:** Run tests → 300/300
- [ ] **Step 3:** Commit

---

## Deferred (Tier 3 — upstream dependent)

These cannot be done without CC changes or upstream format documentation:
- OPP-19: Reduce transcript JSONL dependency
- OPP-04: Manifest anchor staleness after compaction
- OPP-23: Compaction staleness marker
- OPP-26: Version-tagged transcript parsing

## Estimated Scope

| Track | Tasks | Risk | Est. Lines |
|-------|-------|------|------------|
| A: Cache consolidation | 3 | Low | -40 net (removes duplication) |
| B: Tier 2 accuracy | 5 | Medium | ~100 net |
| C: Dead code cleanup | 3 | Very low | -30 net |
| **Total** | **11** | | **~30 net** |
