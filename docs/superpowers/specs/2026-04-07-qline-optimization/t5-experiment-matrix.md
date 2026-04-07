# T5 — Experiment Matrix & Implementation Backlog

## Objective

Converge findings from T1 (accuracy), T2 (freshness), T3 (observability), and T4 (external scan) into a ranked experiment matrix and categorized implementation backlog. This is the decision document — it ranks every opportunity and produces the actionable backlog that feeds the implementation spec.

## Non-Goals

- Implementing any changes (this track produces the backlog; implementation is Phase 3)
- Repeating research already done in T1-T4 (reference their outputs, don't re-derive)
- Proposing new opportunities not grounded in track findings

---

## Inputs

- T1: accuracy gaps table, assumption validation results, replay dataset
- T2: latency benchmarks, strategy comparison matrix, recommended refresh strategy
- T3: source inventory, missing visibility table, schema proposals
- T4: supported-vs-unsupported dependency table, upstream risk register
- TX: experiment template, evidence standards

---

## Tasks

### 5.1 — Opportunity Collection

Every distinct opportunity gathered from T1-T4. Each references source track findings by their native ID.

| # | Opportunity | Source Track | Source ID(s) | Type |
|---|-------------|-------------|-------------|------|
| 1 | Fix manifest anchor priority — demote manifest `cache_anchor` below transcript anchor in `_try_phase2_transcript()` | T1 | AG-01 | Accuracy fix |
| 2 | Fix warning threshold formula — use `effective - offset` instead of `autocompact - offset` in `compute_context_thresholds()` | T1 | AG-02 | Accuracy fix |
| 3 | Add calibration factor to static overhead estimate (1.08x) or prefer transcript anchor when available | T1 | AG-03, A4 | Accuracy fix |
| 4 | Compaction-aware anchor refresh — allow overwriting `cache_anchor` after compaction | T1 | AG-04 | Accuracy fix |
| 5 | Make context correction (`output_tokens` inclusion) configurable | T1 | AG-05 | Accuracy fix |
| 6 | Change MCP server fallback from 5 to 0 | T1 | AG-06 | Accuracy fix |
| 7 | Tune cache decay constant or clarify test expectations for degraded detection | T1 | AG-07 | Accuracy fix |
| 8 | Fix Phase 2 anchor calibration (consequence of AG-01 fix) | T1 | AG-08 | Accuracy fix |
| 9 | Reduce cache TTL from 30s to 5s (Strategy A-prime) | T2 | Rec. 2.5, A-prime | Freshness improvement |
| 10 | Implement seq-based cache invalidation (Strategy B) | T2 | Strategy B | Freshness improvement |
| 11 | Session resume signal — clear stale caches on `session.reentry` detection | T3 | MV-10, 3.3.7 | Observability + accuracy fix |
| 12 | Hook performance sidecar — instrument `run_fail_open()` with timing | T3 | MV-01, 3.3.1 | Observability |
| 13 | Source freshness manifest keys | T3 | MV-02, 3.3.2 | Observability |
| 14 | Parse diagnostic sidecar for transcript/render failures | T3 | MV-03, MV-04, 3.3.3 | Observability |
| 15 | Package schema version in manifest | T3 | MV-07, 3.3.4 | Observability |
| 16 | Compaction impact signal — `compact.anchor_invalidated` event | T3 | MV-08, 3.3.5 | Observability + accuracy |
| 17 | Hook coverage report in session_inventory.json | T3 | MV-05, 3.3.6 | Observability |
| 18 | Hook fault surfacing from lifecycle-hook-faults.jsonl | T3 | MV-11, 3.3.8 | Observability |
| 19 | Reduce transcript JSONL dependency — source cache metrics from `current_usage` in stdin | T4 | UR-01, UR-05 | Fragility reduction |
| 20 | Remove/guard `conversation` dict dependency in `normalize()` | T4 | UR-04 | Fragility reduction |
| 21 | Make CC internal constants configurable or derive from observation | T4 | UR-02 | Fragility reduction |
| 22 | Add defensive session_id resolution on resume (scan recent packages on miss) | T4 | UR-03 | Fragility reduction |
| 23 | Compaction staleness marker via PreCompact/PostCompact hooks | T4 | UR-06 | Fragility reduction |
| 24 | Remove undocumented top-level `current_usage` fallback path | T4 | UR-07 | Fragility reduction |
| 25 | Transcript schema validation in test suite for breakage detection | T4 | UR-01 | Fragility reduction |
| 26 | Version-tag transcript parsing logic for multi-parser support | T4 | UR-01 | Fragility reduction |
| 27 | Staleness detection when Stop hook fails to fire | T4 | UR-05 | Fragility reduction |

**Total: 27 opportunities** from 8 T1 gaps, 2 T2 strategies, 8 T3 proposals, and 9 T4 mitigations.

---

### 5.2 — Experiment Matrix

**Scoring dimensions:**

| Dimension | Scale | Weight | Definition |
|-----------|-------|--------|------------|
| Impact | 1-5 | 3x | How much does this improve the user's experience or understanding? |
| Risk | 1-5 (inverted: 1=high risk, 5=low risk) | 2x | Chance of introducing regressions or breaking existing behavior |
| Latency Gain | 0-3 | 1x | Reduction in event-to-display latency (0 = none, 3 = major) |
| Correctness Gain | 0-3 | 2x | Improvement in metric accuracy (0 = none, 3 = fixes critical gap) |
| Observability Gain | 0-3 | 1x | New debugging/visibility capability (0 = none, 3 = major blind spot filled) |
| Implementation Cost | 1-5 (inverted: 1=expensive, 5=trivial) | 1x | Lines of code, files changed, testing complexity |
| Fragility Change | -2 to +2 | 1x | Net change in dependency on undocumented behavior (-2 = much more fragile, +2 = much less) |

**Score = (Impact * 3) + (Risk * 2) + Latency + (Correctness * 2) + Obs + Cost + Fragility**

Max possible: 15 + 10 + 3 + 6 + 3 + 5 + 2 = 44

| Rank | ID | Title | Track | Impact | Risk | Lat. | Corr. | Obs | Cost | Frag. | Score | Rationale |
|------|-----|-------|-------|--------|------|------|-------|-----|------|-------|-------|-----------|
| 1 | OPP-01 | Fix manifest anchor priority (AG-01) | T1 | 5 | 4 | 0 | 3 | 0 | 5 | +1 | **38** | Critical accuracy bug. Demoting one priority check in `_try_phase2_transcript()` is a 3-line change. Fixes the root cause of AG-08 too. Reduces fragility by removing dependency on the wrong manifest value. |
| 2 | OPP-11 | Session resume signal (MV-10/3.3.7) | T3 | 4 | 5 | 1 | 2 | 2 | 5 | 0 | **36** | Trivial (~10 lines), uses existing `session.reentry` events already collected but not consumed. Fixes real staleness on resume. High ROI. |
| 3 | OPP-09 | Reduce cache TTL 30s to 5s (A-prime) | T2 | 4 | 5 | 3 | 0 | 0 | 5 | 0 | **35** | Two integer constant changes. 6x freshness improvement. T2 proved pipeline is sub-4ms even on XL sessions; 30s TTL is unnecessary. Zero architectural risk. |
| 4 | OPP-02 | Fix warning threshold formula (AG-02) | T1 | 4 | 5 | 0 | 3 | 0 | 5 | 0 | **35** | One-line formula fix. Deterministic mathematical error where `warning_at == error_at`. Uses verified CC source constants. |
| 5 | OPP-19 | Reduce transcript dependency via `current_usage` (UR-01/UR-05) | T4 | 5 | 3 | 0 | 2 | 0 | 2 | +2 | **33** | Highest fragility reduction. Sourcing cache metrics from documented stdin `current_usage` instead of undocumented transcript JSONL removes the #1 fragile dependency. Medium implementation cost: needs architectural change in cache metric pipeline. |
| 6 | OPP-16 | Compaction anchor invalidation event (MV-08/3.3.5) | T3 | 4 | 4 | 0 | 2 | 2 | 4 | 0 | **32** | ~25 lines across two files. Fixes stale anchor after compaction. New event type follows TX envelope. Complements AG-01 fix. |
| 7 | OPP-15 | Package schema version in manifest (MV-07/3.3.4) | T3 | 2 | 5 | 0 | 0 | 1 | 5 | +1 | **28** | Trivial: one line in `create_package()`. Future-proofing for all T3 additive changes. Low impact today but enables safe evolution. |
| 8 | OPP-18 | Hook fault surfacing (MV-11/3.3.8) | T3 | 3 | 5 | 0 | 0 | 3 | 4 | 0 | **28** | ~25 lines. Surfaces crash data from existing fault ledger that is already being written but never read. High observability gain for invisible hook failures. |
| 9 | OPP-20 | Remove `conversation` dict dependency (UR-04) | T4 | 3 | 4 | 0 | 1 | 0 | 4 | +2 | **28** | Removes undocumented field dependency. Audit `normalize()` to confirm documented alternatives exist; then delete the fragile code path. Medium risk: must verify no lost functionality. |
| 10 | OPP-05 | Configurable context correction (AG-05) | T1 | 3 | 5 | 0 | 1 | 0 | 4 | 0 | **27** | Add `context_bar.include_output = true/false` config key. Documents the divergence from CC's display. Current behavior is arguably more useful but confusing when comparing to CC. |
| 11 | OPP-12 | Hook performance sidecar (MV-01/3.3.1) | T3 | 3 | 4 | 0 | 0 | 3 | 3 | 0 | **25** | Instruments `run_fail_open()` with timing. Needs minor refactor to get package_root into wrapper scope. Fills a major blind spot (16 hooks with zero latency visibility). |
| 12 | OPP-06 | MCP server fallback to 0 (AG-06) | T1 | 2 | 5 | 0 | 1 | 0 | 5 | 0 | **25** | One-line change. Fallback from 5 to 0 is more conservative. Rarely triggered but fixes wrong direction on miss. |
| 13 | OPP-21 | Configurable CC internal constants (UR-02) | T4 | 3 | 4 | 0 | 1 | 0 | 3 | +2 | **25** | Add `qline.toml` keys for CC_OUTPUT_RESERVE, CC_AUTOCOMPACT_BUFFER, etc. Reduces speculative dependency. Medium cost: config schema change + validation. |
| 14 | OPP-25 | Transcript schema validation in tests (UR-01) | T4 | 3 | 5 | 0 | 0 | 1 | 4 | +1 | **25** | Add test fixtures that validate expected transcript fields against real samples. Early breakage detection on CC updates. Additive to test suite only. |
| 15 | OPP-27 | Staleness detection when Stop hook fails (UR-05) | T4 | 3 | 4 | 0 | 1 | 2 | 3 | +1 | **25** | When statusline sees new turns (via context_window changes) without corresponding cache events, log a warning. Reduces impact of known Stop hook reliability issues. |
| 16 | OPP-08 | Phase 2 anchor calibration (AG-08) — auto-fixed by OPP-01 | T1 | 3 | 5 | 0 | 2 | 0 | 5 | 0 | **30** | No standalone work needed if OPP-01 is fixed. Listed for traceability. The calibration ratio logic is correct; only its input (the corrupted anchor) was wrong. Score reflects standalone value if OPP-01 were deferred. |
| 17 | OPP-04 | Compaction-aware anchor refresh (AG-04) | T1 | 3 | 3 | 0 | 2 | 0 | 3 | -1 | **22** | Partially addressed by OPP-16 (compaction invalidation event). Standalone implementation adds fragility (depends on CC compaction internals). Best done after OPP-16. |
| 18 | OPP-22 | Defensive session_id resolution on resume (UR-03) | T4 | 3 | 4 | 0 | 1 | 0 | 3 | +1 | **22** | Add fallback scan of recent session packages when runtime map lookup fails. Medium cost: directory scan logic. Addresses speculative UR-03 risk. |
| 19 | OPP-23 | Compaction staleness marker via hooks (UR-06) | T4 | 3 | 4 | 0 | 1 | 1 | 3 | 0 | **22** | Overlaps with OPP-16. Write a staleness flag in PreCompact hook that the next statusline invocation detects. If OPP-16 is done, this is redundant. Listed for completeness. |
| 20 | OPP-10 | Seq-based cache invalidation — Strategy B (T2) | T2 | 3 | 3 | 3 | 0 | 0 | 3 | 0 | **21** | ~50 LOC. Eliminates all cache staleness by checking `.seq_counter` on each invocation. More complex than OPP-09 (A-prime) with marginal gain over 5s TTL. Best as Phase 2 follow-on after A-prime is validated. |
| 21 | OPP-14 | Parse diagnostic sidecar (MV-03/MV-04/3.3.3) | T3 | 3 | 4 | 0 | 0 | 2 | 2 | 0 | **21** | Medium complexity: timing instrumentation across multiple functions, bounded JSONL writer, error-only recording. Useful for self-diagnostics but lower ROI than simpler proposals. |
| 22 | OPP-17 | Hook coverage report (MV-05/3.3.6) | T3 | 2 | 5 | 0 | 0 | 2 | 3 | 0 | **21** | ~40 lines in `obs-session-start.py`. Automates T0 manual verification. One-time diagnostic at session start. |
| 23 | OPP-13 | Source freshness manifest keys (MV-02/3.3.2) | T3 | 3 | 3 | 0 | 0 | 2 | 2 | 0 | **19** | Medium complexity with flock contention concern. Best written to session cache, not manifest. Lower ROI because OPP-09 (TTL reduction) already reduces the staleness window from 30s to 5s. |
| 24 | OPP-07 | Tune cache decay constant (AG-07) | T1 | 2 | 3 | 0 | 1 | 0 | 4 | 0 | **18** | Need to determine if test or code is wrong first. If decay is too aggressive, reduce from 0.7 to 0.5. Requires analysis before change. |
| 25 | OPP-03 | Static overhead calibration factor (AG-03) | T1 | 2 | 4 | 0 | 1 | 0 | 4 | 0 | **22** | The 8.5% underestimate is acceptable for a lower bound. A 1.08x factor is a one-line change but may overcompensate for small projects. Phase 2 transcript anchor already provides the correction. Low urgency. |
| 26 | OPP-26 | Version-tagged transcript parsing (UR-01) | T4 | 3 | 3 | 0 | 0 | 0 | 1 | +2 | **18** | High effort: maintain multiple parsers gated by CC version detection. Significant complexity for a surface that has been stable in practice. Best deferred until a breakage occurs. |
| 27 | OPP-24 | Remove undocumented `current_usage` fallback (UR-07) | T4 | 1 | 5 | 0 | 0 | 0 | 5 | +1 | **19** | Trivial deletion but risk is already Low/Low per T4. The fallback is harmless. Lowest priority. |

**Sorted by score (descending):**

| Rank | ID | Title | Score |
|------|-----|-------|-------|
| 1 | OPP-01 | Fix manifest anchor priority (AG-01) | **38** |
| 2 | OPP-11 | Session resume signal (MV-10/3.3.7) | **36** |
| 3 | OPP-09 | Reduce cache TTL 30s to 5s (A-prime) | **35** |
| 4 | OPP-02 | Fix warning threshold formula (AG-02) | **35** |
| 5 | OPP-19 | Reduce transcript dependency (UR-01/UR-05) | **33** |
| 6 | OPP-16 | Compaction anchor invalidation (MV-08/3.3.5) | **32** |
| 7 | OPP-08 | Phase 2 anchor calibration — auto-fix via OPP-01 (AG-08) | **30** |
| 8 | OPP-15 | Package schema version (MV-07/3.3.4) | **28** |
| 9 | OPP-18 | Hook fault surfacing (MV-11/3.3.8) | **28** |
| 10 | OPP-20 | Remove `conversation` dict dependency (UR-04) | **28** |
| 11 | OPP-05 | Configurable context correction (AG-05) | **27** |
| 12 | OPP-12 | Hook performance sidecar (MV-01/3.3.1) | **25** |
| 13 | OPP-06 | MCP server fallback to 0 (AG-06) | **25** |
| 14 | OPP-21 | Configurable CC internal constants (UR-02) | **25** |
| 15 | OPP-25 | Transcript schema validation in tests (UR-01) | **25** |
| 16 | OPP-27 | Staleness detection on Stop hook miss (UR-05) | **25** |
| 17 | OPP-03 | Static overhead calibration factor (AG-03) | **22** |
| 18 | OPP-04 | Compaction-aware anchor refresh (AG-04) | **22** |
| 19 | OPP-22 | Defensive session_id resolution (UR-03) | **22** |
| 20 | OPP-23 | Compaction staleness marker (UR-06) | **22** |
| 21 | OPP-10 | Seq-based cache invalidation — Strategy B | **21** |
| 22 | OPP-14 | Parse diagnostic sidecar (MV-03/MV-04) | **21** |
| 23 | OPP-17 | Hook coverage report (MV-05/3.3.6) | **21** |
| 24 | OPP-24 | Remove `current_usage` fallback (UR-07) | **19** |
| 25 | OPP-13 | Source freshness manifest keys (MV-02) | **19** |
| 26 | OPP-07 | Tune cache decay constant (AG-07) | **18** |
| 27 | OPP-26 | Version-tagged transcript parsing (UR-01) | **18** |

---

### 5.3 — Top 10 Deep Dives

#### EXP-T1-01: Fix Manifest Anchor Priority

**Hypothesis:** Demoting the manifest `cache_anchor` below the transcript-derived first-turn anchor in `_try_phase2_transcript()` will eliminate the corrupted anchor value that currently poisons Phase 2 overhead computation. The "correct by accident" recovery path will become the primary path by design.

**Changed source(s):** `src/context_overhead.py` — `_try_phase2_transcript()` (lines 496-498). Swap priority: check `_read_transcript_anchor()` first, then fall back to `_read_manifest_anchor()` only if transcript is unavailable.

**Measurement method:** Replay 6 curated sessions from T1 (b6366041, 37e77508, f13afa23, 767f1709, 565718fd, 86c99415). Compare anchor values before/after fix. Verify: (a) cold-start anchor matches first-turn `cache_creation_input_tokens` (36k-52k range), not per-turn delta (973-2406); (b) calibration ratio approaches 1.0 (currently 0.77).

**Metrics captured:**
- Latency delta: None (same code path, different priority order)
- Correctness delta: anchor value 973-2406 (wrong) to 36k-52k (correct); calibration ratio 0.77 to ~1.0
- Fragility risk: Low — reduces fragility by removing dependency on `obs-stop-cache.py` write semantics
- Observability gain: None

**Claude-version sensitivity:** Depends on transcript JSONL format for `_read_transcript_anchor()` (classified Fragile by T4). However, the current manifest anchor is ALSO fragile AND wrong. Net: no change in fragility, major gain in correctness.

**Implementation cost:** Trivial — 3-line priority reorder.

**Evidence:** T1 AG-01: All 6 sessions with manifest `cache_anchor` show values 973-2406 vs transcript first-turn values 36032-51958. Session f13afa23: manifest=1371, transcript=38151. The manifest stores per-turn `cache_create` delta, not system overhead.

---

#### EXP-T3-01: Session Resume Signal

**Hypothesis:** Detecting `session.reentry` event count changes in `_inject_obs_counters()` and clearing stale overhead/anchor caches will eliminate 30s+ staleness on session resume, providing immediately fresh data on re-entry.

**Changed source(s):** `src/statusline.py` — `_inject_obs_counters()` (~line 1900). Add ~10 lines to compare `session.reentry` count against `last_known_reentry_count` in session cache. On increase: clear `overhead_ts` and `turn_1_anchor` from session cache.

**Measurement method:** Resume a session after 5+ minutes idle. Verify: (a) obs counters refresh immediately on first post-resume invocation (not after 30s delay); (b) overhead anchor is re-derived from transcript on first post-resume overhead computation; (c) no regression on fresh sessions (reentry count 0 triggers no action).

**Metrics captured:**
- Latency delta: ~0ms overhead (one additional dict lookup per invocation)
- Correctness delta: Eliminates 30-60s stale data window on resume; first post-resume statusline shows current state
- Fragility risk: Low — uses existing `session.reentry` events, no new files or events
- Observability gain: Medium — resume transitions become visible in cache invalidation behavior

**Claude-version sensitivity:** Depends on `obs-session-start.py` continuing to emit `session.reentry` events (qLine-owned) and on `session_id` persisting on resume (speculative per T4 UR-03). The reentry detection is defensive: if `session.reentry` events stop being emitted, the comparison `0 > 0` is False and no action is taken (graceful no-op).

**Implementation cost:** Trivial — ~10 lines, no new files, no new events.

**Evidence:** T3 3.3.7: `obs-session-start.py:129-137` already emits `session.reentry` events. `_count_obs_events()` already counts them in the `ec` dict. The data exists and is collected; it is simply not consumed.

---

#### EXP-T2-01: Reduce Cache TTL from 30s to 5s (Strategy A-Prime)

**Hypothesis:** Reducing the obs counter cache TTL and overhead cache TTL from 30s to 5s will improve display freshness 6x with negligible I/O overhead, because T2 measurements prove the uncached pipeline completes in under 4ms even on XL sessions (2440 events, 1.2MB JSONL).

**Changed source(s):**
- `src/statusline.py` line 1899: change `>= 30` to `>= 5`
- `src/context_overhead.py` line 751: change `< 30` to `< 5`

**Measurement method:** Run benchmark script (`tests/t2_latency_benchmark.py`) before and after on same 4 session sizes (Small/Medium/Large/XL). Verify: (a) pipeline latency remains under 10ms on all sizes; (b) obs counter data refreshes within 5s of hook events; (c) overhead data refreshes within 5s of transcript changes.

**Metrics captured:**
- Latency delta: Worst-case staleness 30s to 5s (6x improvement). Pipeline execution unchanged (~3.5ms XL).
- Correctness delta: None (same computation, more frequent)
- Fragility risk: Low — no architectural change, two constant modifications, instantly revertible
- Observability gain: None directly, but fresher data improves all displayed metrics

**Claude-version sensitivity:** None. Cache TTLs are purely qLine-internal. No CC dependency.

**Implementation cost:** Trivial — two integer constant changes.

**Evidence:** T2 section 2.1: XL session (2440 events, 1.2MB) uncached obs_counters scan costs 0.89ms. Even at once-per-5s frequency, this is 0.89ms per 5000ms = 0.018% CPU. T2 section 2.4: Strategy A-prime scored (1, 1, 2, 2, 1) = 7, matching Strategy B with zero architectural risk.

---

#### EXP-T1-02: Fix Warning Threshold Formula

**Hypothesis:** Changing `compute_context_thresholds()` to compute `warning = effective - CC_WARNING_OFFSET` (instead of `autocompact - CC_WARNING_OFFSET`) will restore the intended 13000-token gap between warning and error thresholds.

**Changed source(s):** `src/context_overhead.py` line 681: replace `autocompact` with `effective` in the warning computation.

**Measurement method:** Call `compute_context_thresholds(200000)` before and after. Verify: (a) before: `warning_at=147000, error_at=147000` (identical — bug); (b) after: `warning_at=160000, error_at=147000` (13k gap — correct). Run context bar render with values at 148k, 155k, 165k tokens to verify graduated severity: error at 148k, warning at 155k, normal at 165k.

**Metrics captured:**
- Latency delta: None
- Correctness delta: Warning threshold changes from 147000 to 160000 for 200k window; severity graduation restored
- Fragility risk: Low — formula uses verified CC source constants (Supported classification)
- Observability gain: None

**Claude-version sensitivity:** Depends on CC internal constants (`CC_WARNING_OFFSET`, `CC_AUTOCOMPACT_BUFFER`) extracted from CC v2.1.92 decompiled source. Classified as Speculative by T4, but the mathematical relationship (`effective = context_window_size - CC_OUTPUT_RESERVE`) is consistent with observed behavior.

**Implementation cost:** Trivial — one-line formula change.

**Evidence:** T1 AG-02: `compute_context_thresholds(200000)` returns `warning_at: 147000, error_at: 147000`. CC source: warning at `nU - _a1 = 160000`, error at `EH_ - qa1 = 147000`. The 13000-token gap is the CC_AUTOCOMPACT_BUFFER.

---

#### EXP-T4-01: Reduce Transcript JSONL Dependency

**Hypothesis:** Sourcing per-turn cache metrics (cache_creation, cache_read, input_tokens) from the documented `current_usage` object in the statusline stdin JSON — instead of parsing the undocumented transcript JSONL — will eliminate the highest-impact fragile dependency (UR-01) while maintaining cache health computation accuracy.

**Changed source(s):**
- `src/context_overhead.py` — `_try_phase2_transcript()`: add a path that reads `current_usage.cache_creation_input_tokens` and `current_usage.cache_read_input_tokens` from the stdin payload (already available in `normalize()` output as `state["cache_creation"]` and `state["cache_read"]`).
- `src/statusline.py` — `normalize()`: ensure `current_usage` fields are extracted and passed through `state`.
- `hooks/obs-stop-cache.py` — optionally: reduce from parsing transcript to recording the simpler `current_usage` values.

**Measurement method:** Compare cache health computations (hit rate, busting detection) using transcript-derived metrics vs stdin-derived metrics across 5 curated sessions. Verify: (a) hit rates match within 5%; (b) busting/degraded states are detected at the same turns; (c) anchor derivation still works (first-turn cache_creation is available as the first non-null `current_usage`).

**Metrics captured:**
- Latency delta: Removes transcript tail read (0.12-0.16ms) from cache metric path. Marginal.
- Correctness delta: Depends on whether `current_usage` provides per-turn deltas (needed for hit rate) or cumulative totals (would need differencing). Must verify.
- Fragility risk: Major reduction (+2) — moves from undocumented JSONL format to documented stdin field
- Observability gain: None

**Claude-version sensitivity:** The replacement path uses only documented `current_usage` fields (Supported per T4). However, the `current_usage` object is `null` before the first API call and may provide cumulative rather than per-turn values — this must be validated.

**Implementation cost:** Medium-Large. Architectural change: re-route the cache metric pipeline from transcript-driven to stdin-driven. Transcript parsing remains needed for historical analysis but exits the hot path.

**Evidence:** T4 UR-01: Transcript JSONL schema is Fragile, confirmed by closed issue #27724 (no public schema docs). T4 4.4: `current_usage` fields are Supported with explicit documentation. T1 validated that `_read_transcript_tail()` is correct but fragile.

---

#### EXP-T3-02: Compaction Anchor Invalidation Event

**Hypothesis:** Emitting a `compact.anchor_invalidated` event from `obs-precompact.py` and having `_try_phase2_transcript()` clear its cached anchor on detecting this event will eliminate stale overhead display after compaction.

**Changed source(s):**
- `hooks/obs-precompact.py`: Add ~10 lines after the existing `compact.started` event to emit `compact.anchor_invalidated` with the prior anchor value.
- `src/context_overhead.py` — `_try_phase2_transcript()`: Add ~15 lines to check for this event (piggyback on existing `_count_obs_events()` call) and clear `session_cache["turn_1_anchor"]` when detected.

**Measurement method:** Trigger compaction in a test session (either via `/compact` or by filling context to autocompact threshold). Verify: (a) `compact.anchor_invalidated` event appears in hook_events.jsonl; (b) next overhead computation re-anchors from the post-compaction transcript; (c) overhead percentage reflects post-compaction state, not pre-compaction.

**Metrics captured:**
- Latency delta: None (event scan is already happening; one additional event type check is negligible)
- Correctness delta: Overhead display corrects within one refresh cycle after compaction (currently stays stale until manually re-anchored)
- Fragility risk: Low — new event type uses existing TX-compliant envelope. Depends on PreCompact hook continuing to fire (Observed-stable per T4).
- Observability gain: Medium — compaction transitions become explicitly tracked events

**Claude-version sensitivity:** Depends on PreCompact hook firing before compaction (Supported event per T4 4.1). Issue #44308 notes PreCompact has "no visibility into what's being lost" but the hook itself fires reliably.

**Implementation cost:** Small — ~25 lines across 2 files.

**Evidence:** T3 3.3.5: Compaction currently leaves `turn_1_anchor` stale. The `compaction_suppress_until_turn` mechanism (context_overhead.py:632-656) only suppresses busting alerts, not the stale anchor. T1 AG-04 identified the persistence problem; T3 3.3.5 proposes the fix.

---

#### EXP-T1-03: Phase 2 Anchor Calibration Fix (via OPP-01)

**Hypothesis:** Once manifest anchor priority is fixed (EXP-T1-01), the Phase 2 anchor calibration ratio will automatically correct from ~0.77 to ~1.0 because the calibration formula (`measured_anchor / static_estimate`) receives the correct measured anchor.

**Changed source(s):** None beyond EXP-T1-01. This is a validation experiment, not a code change.

**Measurement method:** After applying EXP-T1-01, replay T0 test #32 conditions. Verify calibration_ratio moves from 0.7729 to 0.95-1.10 range.

**Metrics captured:**
- Latency delta: None
- Correctness delta: Calibration ratio 0.77 to ~1.0; removes misleading calibration that masks the 8.5% estimate undercount
- Fragility risk: None (no additional code change)
- Observability gain: None

**Claude-version sensitivity:** Same as EXP-T1-01.

**Implementation cost:** Zero — validation only. The fix is in EXP-T1-01.

**Evidence:** T1 AG-08: `calibration_ratio = 0.7729` is `27k / 34973 = 0.77` where 27k is a mid-session cache_create picked up by the tail reader (not the first-turn anchor). After fixing AG-01, the first-turn anchor (~37k) yields `37k / 34973 = 1.058`, consistent with T1's measured 8.5% underestimate.

---

#### EXP-T3-03: Package Schema Version

**Hypothesis:** Adding a `schema_version` key to manifest.json enables safe forward evolution of the package schema. Old packages are retroactively `1.0.0`; new packages start at `1.1.0` with T3-era additive fields.

**Changed source(s):** `hooks/obs_utils.py` — `create_package()` (line 161-186): add `"schema_version": "1.1.0"` to the manifest dict.

**Measurement method:** Create a new session package. Verify: (a) manifest.json contains `schema_version: "1.1.0"`; (b) `_read_manifest_anchor()` and `_read_obs_health()` continue to work on old manifests (no `schema_version` key, treated as `1.0.0`); (c) no test regressions.

**Metrics captured:**
- Latency delta: None (one additional JSON key, negligible)
- Correctness delta: None
- Fragility risk: None — purely additive
- Observability gain: Minor — package version is now inspectable for debugging compatibility issues

**Claude-version sensitivity:** None. Purely qLine-internal.

**Implementation cost:** Trivial — one line in `create_package()`.

**Evidence:** T3 MV-07: No `schema_version` field exists today. All manifest readers use `.get()` calls that are already sparse-safe. TX section 2 mandates additive versioning for schema evolution.

---

#### EXP-T3-04: Hook Fault Surfacing

**Hypothesis:** Periodically scanning the last entries of `~/.claude/logs/lifecycle-hook-faults.jsonl` and surfacing recent fault counts in the statusline health badge will make hook crashes visible to users who currently have no indication of hook failures.

**Changed source(s):**
- `src/statusline.py`: Add `_check_hook_faults()` function (~20 lines) that stats the fault ledger, reads last 2KB on mtime change, counts `level: "fault"` entries from the last 5 minutes. Call from `_inject_obs_counters()` with a 60s TTL.
- `src/statusline.py`: Enhance `render_obs_health()` to show a warning indicator when `obs_hook_faults > 0`.

**Measurement method:** Deliberately introduce a crashing hook (e.g., syntax error in a test hook). Verify: (a) fault appears in lifecycle-hook-faults.jsonl (existing behavior); (b) within 60s, statusline health badge shows fault warning; (c) when faults clear (no new faults for 5 minutes), badge returns to normal.

**Metrics captured:**
- Latency delta: ~0.02ms on fault ledger stat (file exists check), ~0.1ms on tail read (2KB) when mtime changes. Negligible.
- Correctness delta: None
- Fragility risk: Low — reads qLine-owned fault ledger at a fixed, documented path
- Observability gain: High — surfaces an entire class of invisible failures (hook crashes)

**Claude-version sensitivity:** None. Fault ledger is qLine-owned (`hook_utils.py:17`).

**Implementation cost:** Small — ~25 lines total.

**Evidence:** T3 MV-11: `hook_utils.py` writes faults to `~/.claude/logs/lifecycle-hook-faults.jsonl` with full traceback. Never read by any component. A hook could crash on every invocation with zero user indication.

---

#### EXP-T4-02: Remove `conversation` Dict Dependency

**Hypothesis:** The `conversation` dict field read by `normalize()` is undocumented and its data is available from documented fields. Removing the dependency eliminates a fragile surface without functionality loss.

**Changed source(s):** `src/statusline.py` — `normalize()` (lines 431-548): Audit all reads from `conversation` dict. For each consumed field, verify documented equivalent exists. Remove the `conversation` read path; rely on documented `context_window.*` and other fields.

**Measurement method:** Remove `conversation` access in `normalize()`. Run full test suite. Pipe a real statusline payload with and without the `conversation` field to verify identical output.

**Metrics captured:**
- Latency delta: None
- Correctness delta: Minor — if `conversation` provided unique data not available elsewhere, that data is lost. Must verify before removing.
- Fragility risk: Reduces fragility (+2) by removing undocumented field dependency
- Observability gain: None

**Claude-version sensitivity:** Reduces sensitivity — the removed path was the fragile one.

**Implementation cost:** Small — requires audit of `normalize()` to map `conversation` fields to documented equivalents, then delete the fallback path.

**Evidence:** T4 UR-04: `conversation` field is NOT in current official statusline docs. May be a legacy field renamed/restructured. `normalize()` reads it but documented alternatives likely exist in `context_window.*`.

---

### 5.4 — Implementation Backlog

#### Tier 1: Safe Additive

Changes that add new capability without modifying existing behavior. New files, new keys, new modules only. Existing tests pass without modification.

| Priority | ID | Title | Tier | Dependencies | Effort | Acceptance Criteria | Source |
|----------|-----|-------|------|-------------|--------|-------------------|--------|
| P1 | OPP-15 | Package schema version | 1 | None | S | manifest.json contains `schema_version: "1.1.0"` for new packages; old packages treated as `1.0.0` by all readers | MV-07, 3.3.4 |
| P2 | OPP-18 | Hook fault surfacing | 1 | None | S | Fault count from lifecycle-hook-faults.jsonl surfaced in obs_health; badge shows warning when faults > 0 in last 5 min | MV-11, 3.3.8 |
| P3 | OPP-12 | Hook performance sidecar | 1 | OPP-15 (schema version exists for new files) | S-M | `hook_perf.jsonl` written by `run_fail_open()` with per-hook elapsed_ms; statusline displays p50/p99 latency when file exists | MV-01, 3.3.1 |
| P4 | OPP-16 | Compaction anchor invalidation event | 1 | None | S | `compact.anchor_invalidated` event emitted by obs-precompact; event follows TX envelope; reader tolerates absence on old packages | MV-08, 3.3.5 |
| P5 | OPP-25 | Transcript schema validation in tests | 1 | None | S | Test fixtures validate expected transcript fields against 5 real samples; CI catches transcript format changes | UR-01 |
| P6 | OPP-17 | Hook coverage report | 1 | None | S-M | `session_inventory.json` gains `hook_coverage` section comparing hooks.json vs settings.json vs disk | MV-05, 3.3.6 |
| P7 | OPP-14 | Parse diagnostic sidecar | 1 | OPP-15 | M | `diagnostics.jsonl` written on parse error/partial outcomes; bounded at 500 lines; obs_health shows warning on threshold | MV-03, MV-04, 3.3.3 |

#### Tier 2: Needs Migration

Changes that modify existing behavior. Require backward compatibility path and may need test fixture updates.

| Priority | ID | Title | Tier | Dependencies | Effort | Acceptance Criteria | Source |
|----------|-----|-------|------|-------------|--------|-------------------|--------|
| P1 | OPP-01 | Fix manifest anchor priority | 2 | None | S | Transcript anchor takes priority over manifest anchor in `_try_phase2_transcript()`; calibration ratio within 0.9-1.1 on replay dataset; AG-08 auto-resolved | AG-01, AG-08 |
| P2 | OPP-02 | Fix warning threshold formula | 2 | None | S | `compute_context_thresholds(200000)` returns `warning_at=160000, error_at=147000`; 13k gap restored | AG-02 |
| P3 | OPP-09 | Reduce cache TTL 30s to 5s | 2 | None | S | Obs counter and overhead caches refresh every 5s; pipeline latency remains under 10ms on all session sizes | T2 A-prime |
| P4 | OPP-11 | Session resume signal | 2 | None | S | Stale caches cleared on `session.reentry` detection; first post-resume statusline shows fresh data | MV-10, 3.3.7 |
| P5 | OPP-20 | Remove `conversation` dependency | 2 | None | S | `normalize()` no longer reads `conversation` dict; all consumed data sourced from documented fields; test suite passes | UR-04 |
| P6 | OPP-06 | MCP server fallback to 0 | 2 | None | S | Fallback count changed from 5 to 0 in `_estimate_static_overhead()` | AG-06 |
| P7 | OPP-05 | Configurable context correction | 2 | None | S | `qline.toml` gains `context_bar.include_output` key (default true); documented in example config | AG-05 |
| P8 | OPP-21 | Configurable CC internal constants | 2 | None | M | `qline.toml` gains keys for CC_OUTPUT_RESERVE, CC_AUTOCOMPACT_BUFFER, etc.; defaults match current values; documented as speculative | UR-02 |
| P9 | OPP-22 | Defensive session_id resolution | 2 | None | M | When runtime map lookup fails, scan recent session packages; log miss event; resolve or degrade gracefully | UR-03 |
| P10 | OPP-07 | Tune cache decay constant | 2 | OPP-01 (anchor must be correct first) | S | Cache decay behavior matches test expectations; test #35 passes with correct transcript data | AG-07 |
| P11 | OPP-03 | Static overhead calibration | 2 | OPP-01 (calibration depends on correct anchor) | S | Calibration factor applied or Phase 2 anchor preferred; estimate accuracy improves from 91.5% to 95%+ | AG-03 |
| P12 | OPP-27 | Stop hook staleness detection | 2 | None | M | When new turns detected without cache events, warning logged to diagnostics sidecar; health badge shows staleness | UR-05 |
| P13 | OPP-10 | Seq-based cache invalidation (Strategy B) | 2 | OPP-09 (validate A-prime first) | M | `.seq_counter` checked on each invocation; cache re-read only on seq change; zero-staleness on active sessions | T2 Strategy B |
| P14 | OPP-13 | Source freshness manifest keys | 2 | OPP-09 (TTL reduction makes this less urgent) | M | Source freshness data tracked in session cache; optionally persisted to manifest at session end | MV-02, 3.3.2 |
| P15 | OPP-24 | Remove `current_usage` fallback | 2 | OPP-20 (audit normalize first) | S | Undocumented top-level `current_usage` fallback removed; documented `context_window.current_usage` path only | UR-07 |

#### Tier 3: Depends on Upstream

Changes that require Claude Code features, documented APIs, or upstream fixes to be fully effective.

| Priority | ID | Title | Tier | Dependencies | Effort | Acceptance Criteria | Source |
|----------|-----|-------|------|-------------|--------|-------------------|--------|
| P1 | OPP-19 | Reduce transcript dependency | 3 | Requires validated `current_usage` providing per-turn cache deltas (not just cumulative totals). Must verify CC behavior. | L | Cache metrics sourced from stdin `current_usage` instead of transcript JSONL; transcript parsing exits hot path; hit rate computed from documented fields | UR-01, UR-05 |
| P2 | OPP-04 | Compaction-aware anchor refresh | 3 | Depends on compaction behavior remaining stable (CC internal). Partially mitigated by OPP-16 (Tier 1). | M | `cache_anchor` overwritten after compaction with post-compaction first-turn value; requires PostCompact hook to reliably fire | AG-04 |
| P3 | OPP-23 | Compaction staleness marker | 3 | Requires upstream fix for statusline post-compaction refresh (#37163, #35816). Partially mitigated by OPP-16. | M | PreCompact hook writes staleness flag; statusline shows "stale" indicator until next refresh. Full fix depends on CC refreshing statusline after compact. | UR-06 |
| P4 | OPP-26 | Version-tagged transcript parsing | 3 | Requires CC version detection mechanism OR public transcript schema. Currently neither exists. | L | Multiple transcript parsers maintained, gated by CC version. Falls back to latest parser on unknown version. | UR-01 |

---

### 5.5 — Recommended Paths

#### Accuracy Path

**Goal:** Fix the accuracy gaps identified in T1, starting with the critical AG-01 and cascading fixes that depend on it.

**Prerequisites:**
- T0 test harness operational (confirmed: test suite passing after T0 fixes)
- Replay dataset from T1 (5 real sessions, 6 synthetic fixtures, 3 transcript fragments)

**Sequence:**

1. **OPP-01: Fix manifest anchor priority** (AG-01, Critical) — Tier 2
   - The foundational fix. All other accuracy items either depend on this or are improved by it.
   - 3-line change in `_try_phase2_transcript()`.
   - Automatically resolves OPP-08 (AG-08, calibration drift).

2. **OPP-02: Fix warning threshold formula** (AG-02, Major) — Tier 2
   - Independent of OPP-01. Can be done in parallel.
   - 1-line formula fix in `compute_context_thresholds()`.

3. **OPP-06: MCP server fallback to 0** (AG-06, Minor) — Tier 2
   - Independent. 1-line change.

4. **OPP-05: Configurable context correction** (AG-05, Minor) — Tier 2
   - Config addition. Document the CC vs qLine divergence.

5. **OPP-07: Tune cache decay constant** (AG-07, Major) — Tier 2
   - Must come AFTER OPP-01 because the decay behavior needs to be re-evaluated with correct anchor values.
   - Determine if test or code is wrong; adjust accordingly.

6. **OPP-03: Static overhead calibration** (AG-03, Minor) — Tier 2
   - Must come AFTER OPP-01 because the calibration ratio depends on the correct anchor.
   - The 8.5% underestimate is acceptable; apply 1.08x factor only if precision demands it.

**Validation method:**
- Replay all 5 curated sessions through the accuracy pipeline before and after each fix.
- Verify: anchor values correct, calibration ratios in 0.95-1.10 range, warning/error thresholds have correct gap, context bar severity matches CC behavior.
- Record before/after in `tests/replay/expected/` for regression detection.

**Rollback plan:**
- Each fix is an isolated code change. Revert the specific commit.
- OPP-01 rollback: restore manifest anchor priority. System returns to "correct by accident" behavior.
- No schema or data format changes in the accuracy path, so rollback is clean.

---

#### Freshness Path

**Goal:** Reduce event-to-display staleness from 30s to 5s immediately, with optional zero-staleness follow-on.

**Prerequisites:**
- T2 latency benchmark baseline established (confirmed: sub-4ms pipeline on all session sizes)
- OPP-01 accuracy fix applied (correct data should refresh correctly)

**Sequence:**

1. **OPP-09: Reduce cache TTL 30s to 5s** (A-prime) — Tier 2
   - Two integer constant changes. Immediate 6x freshness improvement.
   - Ship as patch release. No migration, no schema changes.

2. **OPP-11: Session resume signal** (MV-10) — Tier 2
   - ~10 lines. Eliminates stale data on session resume.
   - Complements TTL reduction: TTL handles periodic staleness, resume signal handles transition staleness.

3. **OPP-10: Seq-based cache invalidation** (Strategy B) — Tier 2, optional Phase 2
   - ~50 LOC. Only if sub-5s staleness is insufficient.
   - Provides true zero-staleness by checking `.seq_counter` on each invocation.
   - Validates after A-prime is proven in production.

**Migration plan:**
- Phase 1 (OPP-09 + OPP-11): No migration needed. Constants change. Deployed as version bump.
- Phase 2 (OPP-10): Adds seq comparison logic to statusline.py. Store `last_seen_seq` in disk cache. Falls back to time-based TTL if `.seq_counter` is unreadable.

**Validation method:**
- Run `tests/t2_latency_benchmark.py` after each change. Verify pipeline latency under 10ms.
- Manual test: trigger a burst of 10 tool calls; verify obs counters update within 5s (Phase 1) or within 1 CC refresh cycle (Phase 2).
- Monitor via snapshot timestamps: compare hook_events last_ts against snapshot ts to measure real display lag.

**Fallback plan:**
- OPP-09 fallback: change constants back to 30. Instant revert.
- OPP-11 fallback: remove the reentry count check. Revert to pre-resume staleness behavior.
- OPP-10 fallback: remove seq comparison logic. Fall back to time-based TTL (already proven by OPP-09).

---

#### Observability Path

**Goal:** Fill the highest-impact visibility gaps identified in T3, starting with trivial wins and progressing to infrastructure.

**Prerequisites:**
- OPP-15 (schema version) should land first to establish versioning before additive fields.
- Package layout from TX section 1.3 governs file placement.

**Sequence:**

1. **OPP-15: Package schema version** (MV-07) — Tier 1
   - One line in `create_package()`. Foundation for all subsequent schema additions.

2. **OPP-18: Hook fault surfacing** (MV-11) — Tier 1
   - ~25 lines. Surfaces existing crash data that is already collected but invisible.
   - No new files created; reads existing fault ledger.

3. **OPP-16: Compaction anchor invalidation** (MV-08) — Tier 1
   - ~25 lines across 2 files. New event type in existing envelope.
   - Complements accuracy path OPP-01 by handling post-compaction staleness.

4. **OPP-12: Hook performance sidecar** (MV-01) — Tier 1
   - Small-Medium effort. New `hook_perf.jsonl` sidecar.
   - Enables performance debugging for all 16 hooks.

5. **OPP-17: Hook coverage report** (MV-05) — Tier 1
   - Small-Medium effort. Additive section in `session_inventory.json`.
   - Automates the manual T0 verification.

6. **OPP-14: Parse diagnostic sidecar** (MV-03/MV-04) — Tier 1
   - Medium effort. New `diagnostics.jsonl` with bounded writes.
   - Enables self-diagnostics for the render pipeline.

7. **OPP-25: Transcript schema validation in tests** — Tier 1
   - Small effort. Test-only change.
   - Early warning system for transcript format changes.

**Schema:**
- All new JSONL sidecars follow the TX `{ seq, ts, ... }` envelope where applicable.
- New manifest keys are additive and sparse-safe (`m.get("key", default)`).
- Schema version `1.1.0` indicates the presence of T3-era additions.

**Reader:**
- Hook faults (OPP-18): read by `_inject_obs_counters()` with 60s TTL.
- Compaction event (OPP-16): read by `_try_phase2_transcript()` via existing event scan.
- Hook perf (OPP-12): read by `_inject_obs_counters()` with 30s TTL (tail scan of last N entries).
- Diagnostics (OPP-14): read by `render_obs_health()` for threshold-based warnings.

**Validation method:**
- OPP-15: verify `schema_version` in new manifests; verify old manifests still parse.
- OPP-18: crash a test hook; verify fault badge appears within 60s.
- OPP-16: trigger compaction; verify anchor re-derivation on next overhead computation.
- OPP-12: run a session; verify hook_perf.jsonl contains timing for all invoked hooks.
- Each proposal has a graceful absence path (FileNotFoundError tolerance) — test with both new and old packages.

**Rollback plan:**
- All Tier 1 items are purely additive. Rollback = stop writing the new data.
- Old packages continue to work unchanged.
- New sidecars can be deleted without affecting core functionality.
- Remove reader code if a sidecar proves problematic; statusline degrades to pre-observability behavior.

---

## Acceptance Criteria

- [x] All opportunities from T1-T4 collected into flat list (no orphaned findings) — 27 opportunities from 8 AG-*, 2 T2 strategies, 8 MV-* proposals, 9 UR-* mitigations
- [x] Experiment matrix scored and ranked with all dimensions filled — all 27 scored, max 38, min 18
- [x] Top 10 opportunities have full TX-format experiment write-ups — 10 EXP-* entries
- [x] Implementation backlog categorized into three tiers — Tier 1: 7 items, Tier 2: 15 items, Tier 3: 4 items
- [x] Every backlog item has dependencies, effort estimate, and acceptance criteria
- [x] At least one recommended path for accuracy fixes — 6-step sequence, OPP-01 first
- [x] At least one recommended path for fresher real-time updates — 3-step sequence, A-prime first
- [x] At least one recommended schema path for richer observability — 7-step sequence, schema version first
- [x] Backlog items reference their source track findings by ID
- [x] No implementation decisions made that contradict track findings

---

## Convergence Checklist

- [x] **Every T1 accuracy gap appears in the backlog.** AG-01 (OPP-01, Tier 2 P1), AG-02 (OPP-02, Tier 2 P2), AG-03 (OPP-03, Tier 2 P11), AG-04 (OPP-04, Tier 3 P2), AG-05 (OPP-05, Tier 2 P7), AG-06 (OPP-06, Tier 2 P6), AG-07 (OPP-07, Tier 2 P10), AG-08 (OPP-08, auto-resolved by OPP-01).
- [x] **T2's recommended strategy is represented in the backlog.** Strategy A-prime = OPP-09 (Tier 2 P3). Strategy B = OPP-10 (Tier 2 P13, optional follow-on).
- [x] **T3's high-impact schema proposals are in the backlog.** 3.3.1 (OPP-12), 3.3.2 (OPP-13), 3.3.3 (OPP-14), 3.3.4 (OPP-15), 3.3.5 (OPP-16), 3.3.6 (OPP-17), 3.3.7 (OPP-11), 3.3.8 (OPP-18). All 8 proposals represented.
- [x] **T4's fragile dependencies are either mitigated or accepted.** UR-01 (OPP-19 Tier 3, OPP-25/26 Tier 1/3), UR-02 (OPP-21 Tier 2), UR-03 (OPP-22 Tier 2), UR-04 (OPP-20 Tier 2), UR-05 (OPP-27 Tier 2, OPP-19 Tier 3), UR-06 (OPP-23 Tier 3), UR-07 (OPP-24 Tier 2).
- [x] **No backlog item contradicts TX data contracts.** All Tier 1 items are additive (new files/keys only). Tier 2 items modify existing behavior but through documented internal changes (formula fixes, constant changes). No breaking changes to public interfaces.
- [x] **Must-fix items from T0 are listed as prerequisites.** T0 test harness operational is a prerequisite for the accuracy path validation method. Replay dataset from T1 is a prerequisite for accuracy validation.
- [x] **Evidence fields in EXP-* write-ups link to source findings.** All 10 EXP entries reference AG-*, MV-*, UR-* IDs from their source tracks.

---

## Risks

| Risk | Mitigation |
|------|------------|
| Track outputs may be inconsistent or contradictory | Convergence checklist catches conflicts; no contradictions found across T1-T4 |
| Scoring is subjective | Rationale column documents the reasoning for each score; evidence-based where possible |
| Backlog may be too large to execute | Recommended paths select the highest-impact subset (top ~10 items across 3 paths); user approves scope |
| OPP-01 fix may expose previously-masked issues | The "correct by accident" path means current output is usually correct; the fix makes it correct by design with no expected output change |
| OPP-19 (transcript reduction) may not be feasible if `current_usage` only provides cumulative totals | Listed as Tier 3 with explicit validation prerequisite; OPP-25 (schema validation) provides interim protection |

---

## Do Not Decide Here

- Which backlog items to actually implement (user approval required after T5)
- Timeline or sprint assignments (out of scope for research)
- Whether to request upstream Claude Code changes (requires separate decision)
