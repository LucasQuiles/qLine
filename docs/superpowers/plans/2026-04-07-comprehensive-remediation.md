# qLine Comprehensive Remediation Plan — 2026-04-07

## Scope

Systematically address all 4 work tracks from the optimization session handoff:
1. **40 test failures** — fix tests and code to reach 235/235 passing
2. **Tier 1 backlog** — 7 safe additive OPP items
3. **Remaining dedup** — 3 unfinished consolidation tasks
4. **Alert system audit** — verify 8 triggers, fix issues, add tests

## Execution Strategy

5 phases, ordered by dependency. Each phase contains independent tasks suitable for parallel subagent execution. Tests are fixed first because they gate verification of everything else.

---

## Phase 1: Test Harness Fixes (40 failures → 0)

### Failure Classification

After analyzing every failing test against current source code:

#### Group A: Bash 3.2 Unicode Escapes (3 tests)
**Root cause:** `$'\U000fXXXX'` 8-digit Unicode escapes require bash 4.0+. macOS ships bash 3.2.

| Test | Expected | Issue |
|------|----------|-------|
| R-02a | `$'\U000f06a9 Opus'` | 8-digit `\U` not supported in bash 3.2 |
| R-02b | `$'\U000f0770 qLine'` | Same |
| R-02f | `$'\U000f0954 45s'` | Same |

**Fix:** Replace `$'\U000fXXXX'` with `$(printf '\U000fXXXX')` which works in Python-shelled tests, or use the actual UTF-8 byte sequences. Since `run_py` already runs Python, change these to Python-side assertions:

```bash
# Before (fails bash 3.2):
assert_contains "R-02a: model with glyph" "$OUT" $'\U000f06a9 Opus'
# After:
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
state = {'model_name': 'Opus', ...}
line = render(state, DEFAULT_THEME)
assert '\U000f06a9 Opus' in line, f'expected glyph+model, got: {line}'
print('OK')
")
assert_equals "R-02a: model with glyph" "$OUT" "OK"
```

#### Group B: Glyph/Format Drift (3 tests)
**Root cause:** Layout redesign changed `↑/↓` to `▲/▼` but tests still expect old glyphs.

| Test | Expected | Actual | Fix |
|------|----------|--------|-----|
| R-12a | `↑12.3k` | `▲12.3k` | Update test expectation |
| R-12b | `↓4.1k` | `▼4.1k` | Update test expectation |
| L-11b | `\u229b` (⊛) | Need to verify current worktree marker | Update test expectation |

**Fix:** Update test expectations to match current `format_tokens` (uses `\u25b2`/`\u25bc`) and worktree marker.

#### Group C: wc -l Whitespace Padding (2 tests)
**Root cause:** macOS `wc -l` pads output with leading spaces: `"       1"` vs `"1"`.

| Test | Issue |
|------|-------|
| R-13 | `assert_single_line` compares `$line_count = "1"` but gets `"       1"` |
| L-02 | Same pattern |

**Fix:** Patch `assert_single_line` to strip whitespace:
```bash
line_count=$(printf '%s\n' "$output" | wc -l | tr -d ' ')
```

Also fix L-01 if it uses the same pattern.

#### Group D: mktemp --suffix Portability (4 tests)
**Root cause:** `mktemp --suffix=.toml` may not work on all macOS versions.

| Test | Issue |
|------|-------|
| CF-03a | TOML config override not loaded → defaults returned |
| CF-04a, CF-04b, CF-04c | Same |

**Fix:** Replace `mktemp --suffix=.toml` with `mktemp /tmp/qline-test-XXXXXX` + `mv` to add suffix, or use Python `tempfile` to create the TOML file inside the `run_py` call.

#### Group E: Legacy Stub Tests (3 tests)
**Root cause:** `render_sys_overhead`, `render_cache_delta`, `render_tokens` are now legacy stubs that return `None`. Tests still call old API expecting rich output.

| Test | Function | Status |
|------|----------|--------|
| spike at spike | `render_cache_delta` | Stub returns None |
| sys_overhead module | `render_sys_overhead` | Stub returns None |
| phase2 anchor | `_read_transcript_tail` | Return shape may have changed |

**Fix:** Redirect tests to new functions (`render_sys_overhead_pill`, `render_cache_pill`) or delete tests for dead stubs and add new tests for the replacement functions.

#### Group F: Stale Dimming Under NO_COLOR (5 tests)
**Root cause:** `_pill()` dim behavior uses `\033[2m` ANSI. Tests run under NO_COLOR but check for ANSI dim. When `NO_COLOR=1`, `_pill` with `dim=True` calls `style_dim(style(text, c, bold))` — but `style()` under NO_COLOR returns plain text, and `style_dim()` wraps it with ANSI `\033[2m...\033[0m`. Need to check if style_dim respects NO_COLOR.

| Test | Issue |
|------|-------|
| STALE-01 | `render_cpu` with cpu_stale=True, checks for `\033[2m` |
| STALE-03 | `render_dir` with stale git |
| STALE-04 | `render_tmux` stale |
| STALE-05 | `render_agents` stale |
| STALE-06 | `render_memory` stale |

**Fix:** Either: (a) These tests need `run_py_color` not `run_py` since they check ANSI output, or (b) `_pill`/`style_dim` need to respect NO_COLOR for dim. Investigate which is the correct fix — likely (a) since the tests explicitly check for ANSI escape codes.

#### Group G: Obs Snapshot Tests (4 tests)
**Root cause:** Obs snapshot logic may have changed path handling or throttle behavior after consolidation.

| Test | Issue |
|------|-------|
| T-obs-1 | Snapshot not written (path or session_id logic changed) |
| T-obs-3 | Throttle detection logic wrong |
| T-obs-4 | Throttle bypass on change not working |
| T-obs-6 | Snapshot written even without session_id |

**Fix:** Trace `_try_obs_snapshot` logic against test setup. The OBS_ROOT env override and QLINE_CACHE_PATH may not be wiring through correctly after the `resolve_package_root_env` consolidation.

#### Group H: Context Bar Compound Assertions (3 tests)
**Root cause:** Tests check for `%!\U000f04bf` pattern but the alert glyph rendering changed in the layout redesign. The `!` suffix after `%` may no longer be adjacent to the bust glyph.

| Test | Expected pattern |
|------|-----------------|
| compound critical+bust | `%!\U000f04bf` (bust glyph directly after critical %) |
| compound warn+bust | `%!\U000f04bf` |
| compound normal+bust | bust glyph in output |

**Fix:** Verify what `render_context_bar` now produces with `cache_busting=True` and update assertions to match. The inline alert glyph is now prepended to the pills list (line 943), not appended to the % suffix.

#### Group I: Context Overhead / Color Tests (7 tests)
**Root cause:** Mix of API changes, color formula changes, and config parameter threading.

| Test | Issue |
|------|-------|
| cache busting not degraded | `\U000f04bf` assertion may fail due to bash unicode or render change |
| busting critical color | Color RGB values changed in darkening formula |
| config thresholds | `_try_phase2_transcript` signature changed (new params) |
| per-segment coloring | Darkening factor or color hex changed |
| forensics report | `generate_overhead_report` import path or return changed |
| A-01b | `run_statusline_color` may not produce ANSI for minimal payload |
| phase2 anchor | `_read_transcript_tail` return shape changed |

**Fix:** Each requires individual diagnosis. The common pattern: verify function signatures match test calls, verify color calculations match expected RGB, verify return shapes match destructured fields.

#### Group J: Hook Integration (1 test)
**Root cause:** Test expects hooks at `~/.claude/hooks/obs-stop-cache.py` but hooks live at `hooks/` in repo. Test needs to use the repo path.

**Fix:** Fix the hook path in the test to use `$REPO_DIR/hooks/obs-stop-cache.py`.

---

### Task Breakdown — Phase 1

**Task 1.1: Fix test harness helpers** (Group C)
- File: `tests/test-statusline.sh`
- Fix `assert_single_line` to strip whitespace from `wc -l`
- Fix any other helpers with macOS portability issues
- Tests fixed: R-13, L-01, L-02

**Task 1.2: Fix bash Unicode escape tests** (Group A)
- File: `tests/test-statusline.sh`
- Convert `$'\U...'` assertions to Python-side assertions
- Tests fixed: R-02a, R-02b, R-02f

**Task 1.3: Fix glyph drift tests** (Group B)
- File: `tests/test-statusline.sh`
- Update `↑/↓` → `▲/▼` in R-12a, R-12b
- Verify and update L-11b worktree marker
- Tests fixed: R-12a, R-12b, L-11b

**Task 1.4: Fix mktemp portability** (Group D)
- File: `tests/test-statusline.sh`
- Replace `mktemp --suffix=.toml` with portable alternative
- Tests fixed: CF-03a, CF-04a, CF-04b, CF-04c

**Task 1.5: Fix stale dimming tests** (Group F)
- File: `tests/test-statusline.sh`
- Change from `run_py` to `run_py_color` (or Python direct call without NO_COLOR)
- Tests fixed: STALE-01, STALE-03, STALE-04, STALE-05, STALE-06

**Task 1.6: Fix legacy stub tests** (Group E)
- File: `tests/test-statusline.sh`
- Redirect `render_cache_delta` → `render_cache_pill`, `render_sys_overhead` → `render_sys_overhead_pill`
- Update assertions for new return shapes
- Check `_read_transcript_tail` return for phase2 anchor test
- Tests fixed: spike at spike, sys_overhead module, phase2 anchor

**Task 1.7: Fix obs snapshot tests** (Group G)
- Files: `tests/test-statusline.sh`, `src/statusline.py`
- Trace `_try_obs_snapshot` path resolution with OBS_ROOT override
- Fix path wiring in test setup
- Tests fixed: T-obs-1, T-obs-3, T-obs-4, T-obs-6

**Task 1.8: Fix context bar compound tests** (Group H)
- File: `tests/test-statusline.sh`
- Verify `render_context_bar` output with cache_busting=True
- Update assertion patterns: inline alert glyph is now at start of output, not after `%`
- Tests fixed: compound critical+bust, compound warn+bust, compound normal+bust

**Task 1.9: Fix context overhead / color tests** (Group I)
- Files: `tests/test-statusline.sh`
- Verify each: `_try_phase2_transcript` signature, darken factor RGB values, busting glyph in NO_COLOR
- Fix: `cache busting not degraded`, `busting critical color`, `config thresholds`, `per-segment coloring`, `forensics report`, `A-01b`, `phase2 anchor`
- Tests fixed: 7 tests

**Task 1.10: Fix hook integration test** (Group J)
- File: `tests/test-statusline.sh`
- Fix hook path from `~/.claude/hooks/obs-stop-cache.py` to `$REPO_DIR/hooks/obs-stop-cache.py`
- Tests fixed: hook integration

**Verification gate:** `bash tests/test-statusline.sh` → 235/235 passed, 0 failed.

---

## Phase 2: Remaining Dedup (3 items)

### Task 2.1: render_obs_* Factory Pattern (L3)

**Current state:** 7 structurally identical renderers at `src/statusline.py:1582-1675`. Each:
```python
def render_obs_XXX(state, theme):
    n = state.get("obs_XXX")
    if not n: return None
    cfg = theme.get("obs_XXX", {})
    glyph = cfg.get("glyph", "DEFAULT").rstrip()
    return _pill(f"{glyph}{n}", cfg, theme=theme)
```

Two variants (`render_obs_rereads`, `render_obs_failures`) add threshold coloring.

**Approach:** Create `_render_obs_counter(state, theme, state_key, theme_key, *, prefix="", format_fn=None)` following the existing `_render_system_metric` pattern. Add threshold support. Register each obs module via a simple data declaration.

**Keep:** All existing function names as thin wrappers (they're referenced by name in layout configs). Each becomes a 2-line delegation.

**Files:** `src/statusline.py`
**Lines saved:** ~60
**Risk:** Low — purely structural, no behavioral change

### Task 2.2: Wire generate_overhead_report Through extract_usage_full

**Current state:** `hooks/obs_utils.py:448-484` has inline usage extraction that duplicates the logic in `extract_usage_full` (lines 566-594). The inline version only extracts `usage` dict, ignoring model/request_id/entry_id.

**Approach:**
```python
# Before (inline extraction):
msg = entry.get("message")
if isinstance(msg, dict) and msg.get("stop_reason") is not None:
    usage = msg.get("usage")
    if isinstance(usage, dict):
        turns.append(usage)
        continue
tur = entry.get("toolUseResult")
if isinstance(tur, dict):
    usage = tur.get("usage")
    if isinstance(usage, dict):
        turns.append(usage)

# After (using shared function):
usage, _, _, _ = extract_usage_full(entry)
if usage is not None:
    turns.append(usage)
```

**Files:** `hooks/obs_utils.py`
**Lines saved:** ~12
**Risk:** Very low — extract_usage_full is a strict superset

### Task 2.3: Remove statusline.py Compatibility Shim

**Current state:** `src/statusline.py` has an inline fallback for `resolve_package_root_env` that runs when `obs_utils` import fails. Now that `obs_utils` is stable and always available via the plugin symlink, the shim can be removed.

**Prerequisite:** Verify the import always succeeds: check `_OBS_AVAILABLE` flag and how it's set.

**Files:** `src/statusline.py`
**Lines saved:** ~5-10
**Risk:** Low — verify import path first

---

## Phase 3: Tier 1 Backlog (7 OPP items)

All items are additive — no existing behavior changes.

### Task 3.1: OPP-15 — Package Schema Version in Manifest

**What:** Add `"schema_version": "1.0.0"` to manifest on package creation.

**Where:** `hooks/obs_utils.py` → `create_package()` function (~line 129). Add one key to the initial manifest dict.

**Test:** Verify `manifest.json` contains `schema_version` key after `create_package()` call.

**Lines:** ~3 (1 code + 2 test)

### Task 3.2: OPP-18 — Hook Fault Surfacing in Statusline

**What:** Read `~/.claude/logs/lifecycle-hook-faults.jsonl` and expose recent fault count in statusline.

**Where:**
- `src/statusline.py` → `_inject_obs_counters()`: Add fault ledger scan (count lines from last N minutes)
- `src/statusline.py` → New `render_obs_faults()` module or extend `render_obs_failures`
- State key: `obs_hook_faults` (count of faults in last hour)

**Approach:** Fast line-count scan (same pattern as `_count_obs_events`). Only count faults with `level: "fault"`. Cache with same TTL as other obs modules.

**Test:** Write fault record, verify count appears in state.

**Lines:** ~30

### Task 3.3: OPP-12 — Hook Performance Sidecar

**What:** Instrument `hook_utils.run_fail_open()` with wall-clock timing. Write timing records to `metadata/hook_perf.jsonl` in the session package.

**Where:**
- `hooks/hook_utils.py` → `run_fail_open()`: Wrap `main_fn()` with `time.monotonic()` timing
- Need `package_root` in scope — add optional `session_id` param to `run_fail_open` or pass via env

**Approach:** Since `run_fail_open` is the outermost wrapper, add timing there. Write to a new `hook_perf.jsonl` sidecar. Don't block on write failure.

```python
def run_fail_open(main_fn, hook_name, event_name, *, session_id=None):
    t0 = time.monotonic()
    try:
        main_fn()
    except Exception as exc:
        log_hook_fault(hook_name, event_name, exc)
        sys.exit(0)
    finally:
        elapsed_ms = (time.monotonic() - t0) * 1000
        if session_id:
            _write_hook_perf(session_id, hook_name, event_name, elapsed_ms)
```

**Migration:** Callers pass `session_id` kwarg. Non-breaking (kwarg with default None).

**Lines:** ~25

### Task 3.4: OPP-16 — Compaction Anchor Invalidation Event

**What:** When PreCompact hook fires, emit `compact.anchor_invalidated` event and clear `turn_1_anchor` from session cache.

**Where:**
- `hooks/obs-precompact.py` → `main()`: Emit new event after existing compact handling
- `src/statusline.py` → `_inject_obs_counters()`: Check for compaction count increase, clear stale anchor

**Approach:** The PreCompact hook already runs. Add event emission. Statusline detects the event count changing and clears its cached anchor.

**Test:** Simulate compaction, verify anchor cleared from cache.

**Lines:** ~25

### Task 3.5: OPP-17 — Hook Coverage Report

**What:** At session start, scan `~/.claude/settings.json` for registered hooks, compare against expected qLine hook set, write coverage summary to `session_inventory.json`.

**Where:** `hooks/obs-session-start.py` → `_scan_inventory()`: Add hook coverage section.

**Approach:** Read settings.json, extract hook names, compare against known qLine hooks list, report missing/extra.

**Test:** Mock settings.json with partial hooks, verify coverage report in inventory.

**Lines:** ~40

### Task 3.6: OPP-14 — Parse Diagnostic Sidecar

**What:** Create `diagnostics.jsonl` for transcript parse failures and render errors. When `_read_transcript_tail` or `_read_transcript_anchor` encounters malformed JSONL, log the parse error instead of silently skipping.

**Where:**
- `src/context_overhead.py` → `_read_transcript_tail()`, `_read_transcript_anchor()`: Add diagnostic logging on parse failure
- `src/statusline.py` → Expose diagnostic count in state for optional display

**Approach:** Write to `native/statusline/diagnostics.jsonl` using the same atomic append pattern. Only log errors, not successes (bounded growth).

**Test:** Feed malformed JSONL, verify diagnostic written.

**Lines:** ~30

### Task 3.7: OPP-25 — Transcript Schema Validation in Tests

**What:** Add test fixtures with real transcript samples. Validate that `_read_transcript_tail`, `_read_transcript_anchor`, and `extract_usage_full` handle actual CC output correctly.

**Where:** `tests/test-statusline.sh` (new section) + `tests/fixtures/transcripts/` (sample files from `tests/replay/`)

**Approach:** Select 3-5 representative replay files. Write tests that run the extraction functions against them and verify field presence/types.

**Test:** Self-verifying — these ARE the tests.

**Lines:** ~50 (tests only)

---

## Phase 4: Alert System Audit (8 triggers)

### Task 4.1: Audit Alert Trigger Accuracy

For each of the 8 triggers, verify:
1. The condition matches what the handoff describes
2. The threshold or flag is correctly derived
3. The trigger fires when expected and doesn't fire when not expected

| Trigger | Condition | Audit Focus |
|---------|-----------|-------------|
| bust | `cache_busting == True` | Verify `_try_phase2_transcript` sets this correctly after AG-01 fix |
| expired | `cache_expired == True` | Verify idle timeout detection works |
| micro | `microcompact_suspected == True` | Verify heuristic: `drop_ratio < 0.5 and abs_drop > 5000` against real data |
| bloat | `raw_sys_pct >= sys_crit_t` | Verify `sys_crit_t` threshold is correct (should be 50% of context) |
| heavy | `total_pct >= crit_t` | Verify `crit_t` uses corrected thresholds from AG-02 fix |
| compact | `tuc <= 10` | Verify `turns_until_compact` calculation from `avg_growth` |
| turns | `tuc <= 50` | Same as above |
| degraded | `cache_degraded == True` | Verify degradation detection with corrected cache hit rate |

**Where:** `src/statusline.py:826-900`, `src/context_overhead.py:670-720`

**Deliverable:** Written audit results per trigger, with code fixes for any issues found.

### Task 4.2: Audit turns_until_compact Calculation

**What:** The `turns_until_compact` (tuc) value depends on `avg_growth` from a trailing window of context size changes. This may be noisy or wrong.

**Where:** Find `turns_until_compact` calculation in `context_overhead.py` or `statusline.py`.

**Audit:**
- How is `avg_growth` computed? (trailing window size, outlier handling)
- What happens when growth is 0 or negative?
- Does it correctly handle the post-AG-01 anchor values?
- Is the division safe (no divide-by-zero)?

### Task 4.3: Audit microcompact_suspected Heuristic

**What:** The heuristic checks `drop_ratio < 0.5 and abs_drop > 5000` to detect silent tool result clearing. This was "based on observed patterns, not verified against CC source."

**Where:** Find `microcompact_suspected` in `context_overhead.py`.

**Audit:**
- Are these thresholds reasonable?
- Does the heuristic fire during normal operation (false positives)?
- Does it correctly detect micro-compaction?

### Task 4.4: Fix /tmp/qline-alert.json Lifecycle

**What:** Alert onset tracking file is never cleaned up.

**Fix options:**
1. Delete on session end (add to obs-session-end.py)
2. Add expiry check — if onset > 1 hour old, treat as stale
3. Include session_id in the file and ignore if session_id doesn't match

**Recommended:** Option 3 — include session_id, ignore stale entries from different sessions.

**Lines:** ~10

### Task 4.5: Add Alert System Tests

**What:** The alert system has zero dedicated tests. Add tests for:
- Each trigger fires correctly
- Priority order is respected (bust > expired > micro > ... > degraded)
- Banner shows for 5s then collapses to glyph
- /tmp file lifecycle
- No-alert state clears file

**Where:** `tests/test-statusline.sh` (new section "alerts")

**Lines:** ~80-100 (tests only)

---

## Phase 5: Verification & Deploy

### Task 5.1: Full Test Suite Run

Run `bash tests/test-statusline.sh` and verify 235/235 + new tests all pass.

### Task 5.2: Deploy to Statusline

Copy updated `src/statusline.py` to `~/.claude/statusline.py` (the active deployment path).

### Task 5.3: Live Smoke Test

Start a new Claude Code session and verify:
- Statusline renders correctly
- Obs counters populate
- Alert triggers fire on synthetic data (if possible)

---

## Task Dependencies

```
Phase 1 (tests) ← no deps, start immediately
  Tasks 1.1-1.10 are all independent — can run in parallel

Phase 2 (dedup) ← depends on Phase 1 complete (need passing tests to verify)
  Task 2.1 (factory pattern) — independent
  Task 2.2 (overhead report) — independent
  Task 2.3 (remove shim) — independent

Phase 3 (Tier 1) ← depends on Phase 2 complete
  Task 3.1 (schema version) — independent
  Task 3.2 (fault surfacing) — independent
  Task 3.3 (hook perf) — independent
  Task 3.4 (compaction event) — independent
  Task 3.5 (hook coverage) — independent
  Task 3.6 (diagnostics) — independent
  Task 3.7 (transcript validation) — independent

Phase 4 (alerts) ← depends on Phase 1 complete (need tests)
  Task 4.1 (trigger audit) — first, informs 4.2-4.5
  Task 4.2 (tuc audit) — depends on 4.1
  Task 4.3 (microcompact audit) — depends on 4.1
  Task 4.4 (file lifecycle) — depends on 4.1
  Task 4.5 (alert tests) — depends on 4.1-4.4
```

## Estimated Scope

| Phase | Tasks | Est. Lines Changed | Risk |
|-------|-------|--------------------|------|
| 1 | 10 | ~300 (test only) | Very low |
| 2 | 3 | ~80 code, ~30 test | Low |
| 3 | 7 | ~200 code, ~100 test | Low (all additive) |
| 4 | 5 | ~50 code, ~100 test | Medium (audit may find surprises) |
| 5 | 3 | ~0 (verification) | None |
| **Total** | **28** | **~860** | |
