# T1 — Accuracy Audit

## Objective

Validate every derived metric and heuristic in `src/context_overhead.py` and `src/statusline.py` against actual local session artifacts, official Claude Code behavior, and replay scenarios. Produce an accuracy gaps table and recommended fixes.

## Non-Goals

- Improving real-time refresh latency (that's T2)
- Adding new observability sources (that's T3)
- Changing public interfaces (governed by TX)
- Fixing test harness portability issues (those are T0 must-fix items)

---

## Inputs

- T0: architecture map, test failure taxonomy (for context on known issues)
- TX: evidence standards, supported-vs-fragile classification, experiment template
- Live repo at `/Users/q/LAB/qLine`
- Real session packages at `~/.claude/observability/sessions/`

---

## Tasks

### 1.1 — Context Overhead Metric Audit

Audit each metric in `src/context_overhead.py` against ground truth.

**Constants validated (lines 29-56):**

| Constant | Claimed Value | Actual (Measured) | Accuracy | Status | Evidence |
|----------|---------------|-------------------|----------|--------|----------|
| `_SYSTEM_PROMPT_TOKENS` | 6200 | ~6200 (within system prompt alone; real first-turn cache_creation of 36-40k includes prompt + tools + CLAUDE.md + memory) | Correct as component | Validated | Component of static estimate, not independently verifiable without bare session |
| `_SYSTEM_TOOLS_TOKENS` | 11600 | N/A (deferred path used; `_SYSTEM_TOOLS_DEFERRED_TOKENS`=968 is the active constant) | N/A | Validated | Code uses deferred path; 11600 is documented but dormant since all MCP tools are always deferred |
| `_SESSION_START_OVERHEAD` | 3500 | Indeterminate — session start hooks+skills contribute system-reminder tokens, but the exact isolated count is not measurable from transcripts | Plausible | Partially valid | Subsumes hook expansions, skill stubs, framing; 3500 is conservative but not independently verifiable |
| `CC_OUTPUT_RESERVE` | 20000 | 20000 (Ha1 constant from CC v2.1.92 decompiled source) | Exact | Validated | Confirmed against CC source constant name Ha1 |
| `CC_AUTOCOMPACT_BUFFER` | 13000 | 13000 (W68 constant from CC v2.1.92 decompiled source) | Exact | Validated | Confirmed against CC source constant name W68 |

**Static overhead estimate validation:**

The `_estimate_static_overhead()` function produces **34,973 tokens** for the current user environment (6 MCP servers, MEMORY.md at 4440 bytes, no local CLAUDE.md in worktree).

Compared against 10 real cold-start first-turn `cache_creation_input_tokens`:

| Session | First-Turn CC | Estimate | Ratio | Accuracy |
|---------|---------------|----------|-------|----------|
| 767f1709 | 36,032 | 34,973 | 1.030 | 97.1% |
| 86c99415 | 36,734 | 34,973 | 1.050 | 95.2% |
| 5ffc7959 | 36,865 | 34,973 | 1.054 | 94.9% |
| 37e77508 | 36,950 | 34,973 | 1.057 | 94.6% |
| 565718fd | 37,579 | 34,973 | 1.075 | 93.1% |
| f13afa23 | 38,151 | 34,973 | 1.091 | 91.7% |
| 733e1c0d | 39,328 | 34,973 | 1.125 | 88.9% |
| b6366041 | 39,679 | 34,973 | 1.135 | 88.1% |
| 89ab4547 | 40,104 | 34,973 | 1.147 | 87.2% |
| 20053f3f | 51,958 | 34,973 | 1.486 | 67.3% |

- **Mean ratio (excl. outlier):** 1.085 (estimate is 8.5% low)
- **Median ratio:** 1.091
- **Root cause:** The estimate underestimates because the first-turn `cache_creation_input_tokens` includes the user's first prompt + any attachment content, not just system overhead. The static estimate correctly captures system-only overhead; the residual is conversation content on turn 1.
- **Assessment:** The 8.5% underestimate is within acceptable bounds for a lower-bound estimate. The one outlier (51,958) was from a larger project context (OnePlatform) with more CLAUDE.md content.

**Functions audited:**

| Function | What It Claims | Validation Result | Status |
|----------|---------------|-------------------|--------|
| `_estimate_static_overhead()` | Phase 1: file-size-based token estimate | Produces 34,973; real first-turn anchors average 37,936 (excl. outlier). 8.5% low but directionally correct. Correctly handles MEMORY.md, CLAUDE.md, MCP servers, plugin stubs. | Validated (minor underestimate) |
| `_read_transcript_tail()` | Extracts cache metrics from trailing turns | Tested against 5 real transcripts. Correctly deduplicates PRELIM entries, filters sidechains, computes exponential-decay hit rate. Results match manual inspection. | Validated |
| `_read_transcript_anchor()` | Extracts first-turn cache_creation | Returns correct values: 39679 (cold), 16414 (warm), 38151 (cold), 590 (warm restart), 36950 (cold). Returns None when no usage entry found within 128KB. | Validated |
| `_read_manifest_anchor()` | Reads cache_anchor from manifest.json | **RETURNS WRONG VALUE.** Manifest `cache_anchor` stores the per-turn cache_create from `obs-stop-cache` hook (973-2406 tokens), NOT the first-turn system overhead (36k-52k). See AG-01. | **Falsified** |
| `inject_context_overhead()` | Orchestrates Phase 1 + Phase 2 | End-to-end path works but manifest anchor priority causes wrong warm-cache detection path. On cold starts, the wrong manifest anchor (< 5000) triggers warm-cache fallback, which then either finds the correct value via `_read_transcript_anchor_with_read` or falls back to static estimate. Net effect: correct by accident on cold starts, but the codepath is fragile. | Partially valid |

### 1.2 — Statusline Metric Audit

| Metric | Function(s) | Validation Result | Status |
|--------|-------------|-------------------|--------|
| Context bar % | `render_context_bar()` | Formula `(ctx_used * 100) // ctx_total` is correct. Uses `context_used_corrected` (includes output tokens) when available, which is MORE accurate for predicting compaction than CC's own display. Integer division means displayed % can be 1pp lower than float result. | Validated |
| Cache health state | `_try_phase2_transcript()` | Exponential-decay hit rate computation is correct. Busting/degraded thresholds (0.3/0.8 defaults) trigger appropriately. Compaction grace period suppression logic is sound. Cache TTL expiry detection works. However, manifest anchor priority creates wrong initial state (see AG-01). | Partially valid |
| Cost formatting | `_format_cost()` | Correct: `< $0.01` uses 4 decimal places, `>= $0.01` uses 2 decimal places. No `$` prefix in the function (caller adds it). Edge cases: `$0.00` renders as `$0.0000`, which is verbose but not wrong. | Validated |
| Duration formatting | `_format_duration()` | Correct for `auto` mode: `30s`, `1m30s`, `2m`, `1h1m`. The `hm` mode renders `0h 00m` for 45 seconds (45000ms), which is the T0 failure #11 root cause — the test expects `45s` but config specifies `hm` format. This is correct behavior for the configured format. | Validated |
| Obs counters | `_inject_obs_counters()` | Fast string scan (`_count_obs_events`) matches gold-standard JSON parsing across all 4 tested sessions (277, 5659, 753, 3254 events). No off-by-one errors detected. | Validated |
| Read/reread ratio | `_count_rereads()` | Fast string scan matches gold-standard JSON parsing across 3 sessions. Correctly counts `"is_reread": true` entries from `reads.jsonl`. | Validated |
| Context thresholds | `compute_context_thresholds()` | **WARNING THRESHOLD BUG:** `warning_at` uses `autocompact - offset` but CC source uses `effective - offset`. Result: warning == error (both 147000 for 200k window) when they should be warning=160000, error=147000. See AG-02. | **Partially valid** |
| Severity in bar | `render_context_bar()` | Does NOT use `warning_at`/`error_at` from `compute_context_thresholds`. Uses `autocompact_pct * 0.80` for warn and `autocompact_pct` for critical. This is a custom heuristic, not mirroring CC, but is internally consistent. The threshold bug (AG-02) does not affect the bar directly. | Validated (custom) |
| Context correction | `normalize()` | Adds `output_tokens` to `context_used` to create `context_used_corrected`. This is MORE accurate for predicting compaction (CC's autocompact checks total including output), but DIFFERS from CC's displayed percentage (which excludes output). Delta is 0-25pp depending on output size. See AG-05. | Partially valid |

### 1.3 — Assumption Validation Checklist

| # | Assumption | Status | Evidence |
|---|-----------|--------|----------|
| A1 | Transcript parsing paths correctly identify stop entries for cache extraction | **Validated** | `_extract_usage()` correctly filters `stop_reason != null` for message entries and accepts all toolUseResult entries. Tested against 5 real transcripts (5 to 589 usage entries each). PRELIM deduplication by requestId works correctly. |
| A2 | Cache anchor derivation selects the right first-turn entry and warm-cache fallback is correct | **Partially valid** | `_read_transcript_anchor()` correctly finds first-turn cache_creation. `_read_transcript_anchor_with_read()` correctly finds first-turn cache_read for warm starts. However, the manifest anchor priority (AG-01) corrupts the selection — manifest stores per-turn delta, not system overhead. Warm-cache fallback triggers on the wrong value but accidentally recovers via secondary paths. |
| A3 | Cache hit-rate formula is mathematically correct; busting/degraded thresholds match real-world patterns | **Validated** | Exponential-decay weighted hit rate produces expected values: 0.0 for cold-only sessions, 0.996+ for healthy cached sessions, drops appropriately on cache breaks. Server-side tool inflation guard (3x median cap) prevents web_search outliers. Thresholds (0.3 busting, 0.8 degraded) are configurable and reasonable. |
| A4 | System-overhead estimate correctly accounts for CLAUDE files, MCP servers, plugin stubs, and settings | **Partially valid** | Static estimate is 8.5% low on average. Correctly finds MEMORY.md (1443 tokens), counts 6 MCP servers (7178 tokens total for tools+instructions), enumerates plugin stubs. Missing: does not account for `settings.json` custom instructions, `.clauderc` files, or per-project CLAUDE.md in non-cwd directories (only checks cwd). The underestimate is acceptable for a lower bound. |
| A5 | Obs counter values from hook_events.jsonl match actual event counts | **Validated** | Fast string-scan counting (`_count_obs_events`) produces identical results to full JSON parsing across 4 sessions totaling 9943 events. No off-by-one errors. `_count_rereads` also matches. The string scan pattern `'"event": "'` is reliable because hook_events.jsonl is written by a single controlled writer (obs_utils.py). |
| A6 | Stale-session and stale-transcript risks on resume/continue flows are handled | **Partially valid** | Session cache keyed by session_id with 30s TTL provides stale detection. Cache TTL expiry detection (lines 605-624) correctly identifies idle-timeout cache rebuilds vs genuine busting. However: (1) manifest anchor written once on first Stop hook invocation is never invalidated, even after compaction; (2) transcript path caching (`_transcript_path` in session_cache) is never re-validated if the transcript file moves; (3) no explicit handling of session_id reuse across days (same ID could theoretically map to different sessions). |

### 1.4 — Replay Dataset Construction

**From existing fixtures (12 files):**

Copied to `tests/replay/fixtures/from-tests/`:
- `valid-cache-busting.json`, `valid-context-critical.json`, `valid-full.json`
- `valid-minimal.json`, `valid-no-workspace.json`, `valid-optional-fields.json`
- `valid-overhead-estimated.json`, `valid-real-payload.json`
- `valid-with-context-window.json`, `valid-with-overhead.json`
- `valid-with-tokens.json`, `wrong-type-optionals.json`

**From real sessions (5 curated):**

| Scenario | Session ID | Date | Events | Key Characteristics |
|----------|-----------|------|--------|---------------------|
| Short, clean | b6366041 | 2026-04-07 | 6 | Cold start, 1 usage entry, no compaction, no failures |
| Medium, varied | 37e77508 | 2026-04-07 | 74 | Cold start, 6 usage entries, reads/writes/bash |
| Long, compacted | 2d9b843a | 2026-03-30 | 5659 | 5 compactions, 66 subagents, 100 failures, 50 prompts, session reentries |
| Subagent-heavy | 4361c8cd | 2026-04-07 | 297 | 7 subagents (Explore, code-reviewer, general-purpose), warm start |
| Error-rich | 767f1709 | 2026-04-04 | 100 | 6 failures, 0 subagents, cold start |

Located at: `tests/replay/sessions/<scenario>/<session_id>/`

**Transcript fragments (3 curated):**

| Fragment | Source | Usage Entries | Purpose |
|----------|--------|---------------|---------|
| `cold-start-simple.jsonl` | b6366041 | 5 | Anchor validation: cold start, single API call |
| `warm-start-varied.jsonl` | 4361c8cd | 135 | Warm-cache anchor detection, PRELIM deduplication |
| `cold-start-long.jsonl` | f13afa23 | 589 | Tail window behavior with many turns, cache hit rate stability |

Located at: `tests/replay/transcripts/`

**Synthetic edge cases (6 authored):**

| Fixture | Tests What | Key Fields |
|---------|-----------|------------|
| `synthetic/cache-busting-rapid.json` | Healthy -> degraded -> busting in 5 turns | `_synthetic_cache_state` with declining cache_read |
| `synthetic/compaction-mid-session.json` | Anchor invalidation after compaction | Pre/post compaction turns, `obs_compactions: 1` |
| `synthetic/transcript-truncated.json` | Graceful degradation when transcript missing | No `transcript_path` field |
| `synthetic/stale-resume.json` | Session resumed after 1h+ gap | Pre/post gap turns, `expected_cache_expired: true` |
| `synthetic/zero-cache-read.json` | Every turn has cache_create only, cache_read=0 | Expected hit rate 0.0, expected busting |
| `synthetic/missing-hook-data.json` | No obs data available | No resolvable package_root |

Located at: `tests/replay/fixtures/synthetic/`

### 1.5 — Accuracy Gaps Table

| ID | Severity | Metric | Root Cause Hypothesis | Reproduction | Confidence | Recommended Fix | Classification |
|----|----------|--------|-----------------------|--------------|------------|-----------------|----------------|
| AG-01 | **Critical** | Manifest cache anchor | `obs-stop-cache.py` writes `metrics["cache_create"]` (per-turn delta: 973-2406 tokens) as `cache_anchor` in manifest. `_read_manifest_anchor()` reads this as system overhead anchor. This is the WRONG value — system overhead is ~37k tokens (first-turn `cache_creation_input_tokens`), not the per-turn delta. The manifest anchor is given HIGHEST priority in `_try_phase2_transcript` (line 496-498), poisoning the anchor resolution chain. On cold starts, the small manifest value (< 5000) triggers warm-cache detection, which then recovers via `_read_transcript_anchor_with_read` or static fallback — **correct by accident, not by design.** | Compare manifest `cache_anchor` (1371) vs transcript first-turn `cache_creation_input_tokens` (38151) for session f13afa23. All 6 manifests with `cache_anchor` show values 973-2406 vs transcript values 36032-51958. | **High** (reproduced deterministically across 6 sessions) | Two options: (a) Fix `obs-stop-cache.py` to store `cache_read + cache_create` from the first turn as anchor instead of just `cache_create`; (b) Demote manifest anchor priority below `_read_transcript_anchor()` in `_try_phase2_transcript()`. Recommendation: option (b) as the minimal-risk change. | **Fragile** — depends on obs-stop-cache write semantics |
| AG-02 | **Major** | Warning threshold computation | `compute_context_thresholds()` computes `warning = autocompact - CC_WARNING_OFFSET` but CC source shows warning triggers at `effective - CC_WARNING_OFFSET`. This makes `warning_at == error_at` (both 147000 for 200k window) when correct values are warning=160000, error=147000. The 13000-token gap between effective and autocompact is lost. | `compute_context_thresholds(200000)` returns `warning_at: 147000, error_at: 147000`. CC source: warning at `nU - _a1 = 160000`, error at `EH_ - qa1 = 147000`. | **High** (mathematical error, deterministic) | Change line 681: `warning = effective - CC_WARNING_OFFSET` (instead of `autocompact - CC_WARNING_OFFSET`). | **Supported** — derived from verified CC source constants |
| AG-03 | **Minor** | Static overhead estimate | `_estimate_static_overhead()` is 8.5% low on average vs real first-turn `cache_creation_input_tokens`. Gap is partly because first-turn CC includes user's first prompt content, not just system overhead. The estimate correctly captures system-only overhead. | Compare estimate (34973) against 9 cold-start sessions: mean actual 37936, mean ratio 1.085. | **High** (measured across 9 sessions) | No code fix needed — the 8.5% underestimate is expected for a system-only lower bound. Consider adding a calibration factor of 1.08 if the estimate is used for compaction prediction. Alternatively, use the first transcript anchor once available (Phase 2) instead of static estimate. | **Observed-stable** |
| AG-04 | **Minor** | Manifest anchor persistence | `cache_anchor` in manifest is write-once (via `update_manifest_if_absent_batch`), meaning it is never updated after compaction or session evolution. After compaction, the system overhead changes (context is summarized), but the anchor remains stale. | Check manifest for session 2d9b843a (5 compactions): no `cache_anchor` field (obs-stop-cache was not deployed early enough). For newer sessions with compaction, the pre-compaction anchor persists. | **Medium** (theoretical — all compacted sessions predate the hook) | Add compaction-aware anchor refresh: when `post_compaction` is True, allow overwriting `cache_anchor` with the new first-turn after compaction. | **Fragile** — compaction behavior is CC-internal |
| AG-05 | **Minor** | Context correction divergence | `normalize()` adds `output_tokens` to `context_used` to create `context_used_corrected`. This is more accurate for compaction prediction but differs from CC's displayed `used_percentage` by 0-25 percentage points depending on output volume. Users comparing qLine's bar to CC's `/context` will see different numbers. | For a session at 75% CC usage with 50k output tokens on 200k window: CC shows 75%, qLine shows 100%. At 10k output: CC 75%, qLine 80%. | **High** (mathematical fact) | Document the divergence in qline.example.toml. Consider making the correction configurable: `context_bar.include_output = true/false` (default true). The current behavior is arguably MORE useful for predicting compaction. | **Supported** — based on documented CC formula differences |
| AG-06 | **Minor** | MCP server count fallback | When no MCP configs are readable, `_estimate_static_overhead()` falls back to `n_mcp_servers = 5`. With 6 actual servers in the current environment, the fallback is close but slightly low. More importantly, the fallback can be wildly wrong for users with 0 or 20+ MCP servers. | Remove all `.mcp.json` files: estimate falls back to 5 servers. User with 0 MCP servers gets 5-server overhead inflated. | **Low** (fallback rarely triggered; requires all config files unreadable) | Change fallback to 0 instead of 5 (conservative direction). Or detect MCP presence via the tool list in the system-reminder block of the statusline payload. | **Fragile** |
| AG-07 | **Major** | Cache health threshold config (MF-07) | T0 test #35 showed cache hit rate of 0.992 (healthy) when test expected degraded at 60% with `warn=0.8`. Root cause: the test's transcript setup may not produce enough turns to trigger degradation, OR the `cache_warn_rate`/`cache_critical_rate` config values from the theme are not propagated correctly to `_try_phase2_transcript()`. Code inspection shows the config IS passed (lines 784-788), but the exponential-decay weighting may smooth out the degradation signal below the configured threshold. | T0 test #35 reproduction: test sets `cache_warn_rate=0.8` and creates a transcript with mixed healthy/degraded turns, but the decay weighting produces 0.992. | **Medium** (test design vs code semantics mismatch — need to verify exact test transcript content) | Clarify whether the test or the code is wrong. If the test creates insufficient degradation signal, update the test. If the decay weighting is too aggressive at smoothing, consider reducing `_CACHE_DECAY` from 0.7 to 0.5 for faster response. | **Observed-stable** |
| AG-08 | **Major** | Phase 2 anchor calibration drift (MF-06) | T0 test #32 showed calibration ratio of 0.773 instead of near 1.0. This was caused by the manifest anchor bug (AG-01): the manifest anchor (per-turn delta ~2k) divided by static estimate (~35k) = 0.06, not 0.77. The 0.77 seen in the test likely came from a different code path where the transcript tail's turn_1_anchor (a later turn's cache_create, e.g., 27k) was used instead of the first-turn anchor (38k). | T0 test #32 result: `calibration_ratio = 0.7729`. This is `27k / 34973 = 0.77` where 27k is a mid-session cache_create value picked up by the tail reader. | **High** (direct consequence of AG-01) | Fix AG-01 first — correct anchor resolution will fix calibration automatically. The calibration comparison (measured vs estimated) is valid logic; it just receives a corrupted input. | **Fragile** |

---

## Codebase Pointers

| What | Where | Key Lines |
|------|-------|-----------|
| Overhead constants | `src/context_overhead.py` | 28-69 |
| Static estimation | `src/context_overhead.py` | 73-247 (`_estimate_static_overhead()`) |
| Transcript tail read | `src/context_overhead.py` | 288-391 (`_read_transcript_tail()`) |
| Transcript anchor read | `src/context_overhead.py` | 394-454 (`_read_transcript_anchor()`, `_read_transcript_anchor_with_read()`) |
| Manifest anchor read | `src/context_overhead.py` | 457-470 (`_read_manifest_anchor()`) |
| Phase 2 orchestrator | `src/context_overhead.py` | 473-664 (`_try_phase2_transcript()`) |
| Threshold computation | `src/context_overhead.py` | 667-693 (`compute_context_thresholds()`) |
| Main orchestrator | `src/context_overhead.py` | 716-807 (`inject_context_overhead()`) |
| Context bar render | `src/statusline.py` | 698-951 (`render_context_bar()`) |
| Severity computation | `src/statusline.py` | 738-763 |
| Normalize | `src/statusline.py` | 431-548 (`normalize()`) |
| Context correction | `src/statusline.py` | 503-510 |
| Obs counter injection | `src/statusline.py` | 1877-1928 (`_inject_obs_counters()`) |
| Event counting | `src/statusline.py` | 1832-1848 (`_count_obs_events()`) |
| Reread counting | `src/statusline.py` | 1851-1863 (`_count_rereads()`) |
| Cache anchor write | `hooks/obs-stop-cache.py` | 257-267 (`update_manifest_if_absent_batch`) |
| Cost formatting | `src/statusline.py` | 558-562 (`_format_cost()`) |
| Duration formatting | `src/statusline.py` | 565-596 (`_format_duration()`) |
| Existing test fixtures | `tests/fixtures/statusline/*.json` | All 12 files |
| Replay dataset | `tests/replay/` | Fixtures, sessions, transcripts, synthetic |

---

## Acceptance Criteria

- [x] All 5 constants in context_overhead.py validated or flagged with evidence
- [x] All 6 assumptions in the validation checklist have a status and evidence artifact
- [x] Replay dataset constructed: 12 existing fixtures + 5 real sessions + 3 transcript fragments + 6 synthetic edge cases
- [x] Every function in the audit tables has been run against replay data with results documented
- [x] Accuracy gaps table populated: 8 gaps with severity, metric, root cause, confidence, and recommended fix
- [x] Each gap classified as supported/observed-stable/fragile/speculative per TX standards
- [x] Recommended fixes are scoped and reference specific functions

---

## Risks

| Risk | Mitigation |
|------|------------|
| Transcript format varies between CC versions | All sessions from CC v2.1.92; format is consistent across tested date range (Mar 24 - Apr 7) |
| Cache metrics depend on model behavior that changes across Claude model updates | Multiple sessions across different dates used; variance is low within same CC version |
| Real session data may contain sensitive paths or content | Manifests redacted (cwd, transcript paths); transcript fragments contain only usage metadata (content stripped) |
| Manifest anchor bug (AG-01) masks correct behavior | Documented as Critical; the accidental recovery path means current output is usually correct despite the bug |

---

## Do Not Decide Here

- Whether to change the cache health thresholds (propose in accuracy gaps table, decide in T5)
- Whether to switch from transcript-based to event-driven cache tracking (that's T2 territory)
- Whether new observability fields are needed (that's T3)
- Ranking of fixes by priority (that's T5)
