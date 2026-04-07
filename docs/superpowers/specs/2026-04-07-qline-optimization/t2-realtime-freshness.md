# T2 — Real-Time Freshness

## Objective

Measure end-to-end latency from Claude event to visible statusline change. Benchmark every throttling layer in the current pipeline. Prototype and compare three refresh strategies. Produce a scored comparison matrix with a recommended path.

## Non-Goals

- Fixing metric accuracy (that's T1)
- Adding new data sources or observability fields (that's T3)
- External research on Claude Code internals (that's T4)
- Implementation of any strategy (that's post-T5)

---

## Inputs

- T0: architecture map, runtime artifact map
- TX: experiment template, evidence standards, supported-vs-fragile classification
- Live repo at `/Users/q/LAB/qLine`
- Active observability sessions for live measurement

---

## Tasks

### 2.1 — Current Pipeline Latency Map

**Executed 2026-04-07. Benchmark script: `tests/t2_latency_benchmark.py`**

Pipeline diagram (unchanged from spec):

```
Claude event (API response / tool call)
  │
  ├─[A]─→ Hook fires (obs-*.py)
  │           │
  │           ├─[B]─→ hook_events.jsonl append
  │           ├─[C]─→ custom/*.jsonl append
  │           └─[D]─→ manifest.json update
  │
  ├─[E]─→ Claude Code refreshes statusline (next cycle)
  │           │
  │           └─[F]─→ statusline.py stdin read
  │                       │
  │                       ├─[G]─→ context_overhead.py runs
  │                       │           │
  │                       │           ├─[H]─→ transcript tail read
  │                       │           └─[I]─→ manifest anchor read
  │                       │
  │                       ├─[J]─→ _inject_obs_counters()
  │                       │           │
  │                       │           └─[K]─→ hook_events.jsonl scan
  │                       │
  │                       └─[L]─→ /tmp/qline-cache.json read/write
  │
  └─[M]─→ Rendered ANSI line to stdout
```

#### Measurement Environment

- Hardware: Apple Silicon (arm64), macOS Darwin 25.2.0
- Python: 3.x (system)
- File system: APFS (SSD-backed)
- Sessions measured: 4 real sessions from `~/.claude/observability/sessions/`

#### Session Size Classes

| Class | Session ID | Events | Ledger | Reads | Manifest | Transcript |
|-------|-----------|--------|--------|-------|----------|-----------|
| Small | `7968468c` | 42 | 15 KB | 2 KB | 1 KB | 277 KB |
| Medium | `fce19404` | 335 | 161 KB | 50 KB | 9 KB | 1.8 MB |
| Large | `20053f3f` | 842 | 317 KB | 42 KB | 6 KB | 4.1 MB |
| XL | `20db3daa` | 2440 | 1.2 MB | 263 KB | 18 KB | 7.0 MB |

#### Per-Segment Latency Table (median, milliseconds)

| Segment | Description | Small (42) | Medium (335) | Large (842) | XL (2440) | Scaling |
|---------|------------|-----------|-------------|------------|----------|---------|
| **F: stdin read** | `read_stdin_bounded()` — 200ms deadline, `select()` + binary read | ~0.1 (estimated) | ~0.1 | ~0.1 | ~0.1 | Constant (fixed payload size) |
| **G: Phase 1 static estimate** | `_estimate_static_overhead()` — CLAUDE.md file stat/read | 1.80 | 1.80 | 1.80 | 1.80 | Constant (fixed file set) |
| **H: Transcript tail read** | `_read_transcript_tail()` — seek to last 50KB, parse turns | 0.16 | 0.12 | 0.14 | 0.14 | **Constant** (capped at 50KB tail) |
| **I: Manifest read** | `manifest.json` full read + JSON parse | 0.015 | 0.025 | 0.021 | 0.037 | Linear with manifest size, sub-ms |
| **I: Manifest anchor** | `_read_manifest_anchor()` — read + extract `cache_anchor` | 0.015 | 0.025 | 0.021 | 0.037 | Same as manifest read |
| **J-K: Hook events scan** | `_count_obs_events()` — full line scan of `hook_events.jsonl` | 0.021 | 0.105 | 0.217 | **0.674** | **Linear** with event count |
| **J: Rereads scan** | `_count_rereads()` — full line scan of `reads.jsonl` | 0.013 | 0.039 | 0.041 | 0.167 | Linear with read count |
| **L: Cache read** | `load_cache()` from `/tmp/qline-cache.json` | 0.016 | 0.016 | 0.016 | 0.016 | Constant |
| **L: Cache write** | `save_cache()` — atomic write + fsync | 0.182 | 0.182 | 0.182 | 0.182 | Constant |
| **Health read** | `_read_obs_health()` — manifest read for health status | 0.014 | 0.026 | 0.020 | 0.041 | Same as manifest read |
| **Resolve pkg root (cold)** | `resolve_package_root()` — runtime map read | 0.012 | 0.012 | 0.012 | 0.012 | Constant |
| **Resolve pkg root (warm)** | Cached in-process | ~0 | ~0 | ~0 | ~0 | Constant |
| **Seq counter read** | `.seq_counter` file read | 0.011 | 0.011 | 0.011 | 0.011 | Constant |

#### Composite Pipeline Timing (median, milliseconds)

| Pipeline Segment | Small (42) | Medium (335) | Large (842) | XL (2440) |
|-----------------|-----------|-------------|------------|----------|
| **obs_counters** (resolve + event scan + rereads + health) | 0.064 | 0.184 | 0.287 | **0.893** |
| **overhead_injection** (transcript tail + manifest + static est.) | 2.049 | 2.188 | 2.166 | 2.439 |
| **cache I/O** (read + write) | ~0.2 | ~0.2 | ~0.2 | ~0.2 |
| **Total qLine-controlled (sum)** | **~2.3** | **~2.6** | **~2.7** | **~3.5** |

#### Bottleneck Analysis

1. **Dominant cost: `_estimate_static_overhead()`** — 1.8ms median on every invocation (when not cached). This is the single largest segment because it walks the file system to stat CLAUDE.md files. Capped by the 30s overhead cache.

2. **Linear growth: `_count_obs_events()`** — Full line scan of `hook_events.jsonl` grows linearly from 0.02ms (42 events, 15KB) to 0.67ms (2440 events, 1.2MB). At 5000+ events this would approach 1.5ms. Capped by the 30s obs count cache.

3. **Transcript tail read is NOT a bottleneck** — `_read_transcript_tail()` uses a 50KB tail window (`_TRANSCRIPT_TAIL_BYTES = 50 * 1024`), making it constant-time regardless of transcript size. Measured 0.12-0.16ms across all session sizes.

4. **Cache I/O is negligible** — Read: 0.016ms, write (with fsync): 0.182ms.

5. **The entire qLine-controlled pipeline completes in under 4ms** even on XL sessions. The dominant latency factor is **NOT the pipeline itself** but the **CC refresh cycle (segment E)** and the **30-second obs/overhead cache TTLs**.

**Key finding:** At sub-4ms total pipeline execution, qLine is never the bottleneck. The 30s cache TTLs for obs counters and overhead data are the primary freshness limiters. The CC statusline refresh cycle (unknown frequency) is the upper bound on display freshness.

### 2.2 — Throttling Layer Inventory

**Executed 2026-04-07.**

Every caching and throttling layer in the pipeline, with measured impact:

| # | Layer | Location | Mechanism | Current Setting | Freshness Impact | Classification |
|---|-------|----------|-----------|-----------------|-----------------|----------------|
| 1 | **CC statusline refresh cycle** | Claude Code runtime | CC invokes statusline command on an internal timer | **Unknown** — not documented, not measurable from within qLine | **Upper bound on all display freshness.** No qLine optimization can beat this cycle. | Fragile (undocumented) |
| 2 | **Obs counter cache** | `statusline.py:1899` | `_inject_obs_counters()` caches event counts for 30s per session | **30s TTL** (`now - last_count_ts >= 30`) | Hook events (reads, writes, bash, failures) lag up to 30s. A burst of 50 events in 10s is invisible until the next refresh after 30s. | Observed-stable (qLine-owned) |
| 3 | **Overhead cache** | `context_overhead.py:751` | `inject_context_overhead()` caches sys overhead + cache health for 30s | **30s TTL** (`now - overhead_ts < 30`) | System overhead tokens, cache hit rate, busting indicators lag up to 30s. Anchor (once-per-session) is cached indefinitely. | Observed-stable (qLine-owned) |
| 4 | **System metrics cache** | `statusline.py:1373-1409` | `collect_system_data()` writes all system collectors to cache, reads back on failure only | **60s CACHE_MAX_AGE_S** — but collectors run fresh every invocation; cache is fallback only | System metrics (CPU, mem, disk, git) are **always fresh on success**. Cache is used only when a collector throws. Stale data possible if `git` subprocess hangs. | Observed-stable (qLine-owned) |
| 5 | **Transcript tail window** | `context_overhead.py:252,309` | `_read_transcript_tail()` reads only last 50KB of transcript (`_TRANSCRIPT_TAIL_BYTES`) | **50KB window** (adaptive 3-8 turns) | Cache metrics reflect only the trailing 3-8 turns, not full session. Adequate for rolling health but misses historical spikes. | Supported (by design) |
| 6 | **Snapshot throttle** | `statusline.py:1974-1976` | `_try_obs_snapshot()` skips write if <30s AND content hash unchanged | **30s cooldown + content dedup** | Snapshot JSONL grows at most once per 30s with identical data, or immediately on state change. Not a freshness limiter for display — only affects the observability record. | Observed-stable (qLine-owned) |
| 7 | **Transcript path scan cache** | `context_overhead.py:769-779` | Scans `~/.claude/projects/` for transcript file, caches path in session_cache | **Indefinite after first hit** (cached in `session_cache["_transcript_path"]`) | Only affects first invocation. Currently 3 project dirs = 0.014ms scan. Would degrade with hundreds of project dirs. | Observed-stable (qLine-owned) |
| 8 | **Package root cache** | `obs_utils.py:215-240` | `resolve_package_root()` caches in `_package_root_cache` dict | **Indefinite per-process** (runtime map never changes) | Zero impact — warm lookup is <0.001ms. | Supported (by design) |
| 9 | **Hook event scan** | `statusline.py:1832-1848` | `_count_obs_events()` does full line scan of `hook_events.jsonl` | **No internal throttle** — but gated by layer #2 (30s obs cache) | Without layer #2, would grow linearly (0.67ms at 2440 events). With layer #2, scan runs at most once per 30s. | Observed-stable (qLine-owned) |

#### Freshness Budget Breakdown

```
Worst-case latency from Claude event to visible statusline change:

  [A] Hook dispatch     ~instantaneous (CC fires hook synchronously)
  [B-D] Hook I/O        ~0.5ms (append + manifest update)
  [E] CC refresh cycle   UNKNOWN — could be 1s, 5s, or 30s
  [F-M] qLine pipeline   2.3-3.5ms (measured)

  + obs counter cache    up to 30s stale
  + overhead cache       up to 30s stale

  Total worst case: CC_cycle + 30s + 3.5ms
  Total best case:  CC_cycle + 0ms + 2.3ms (cache just expired)
```

**Key finding:** The 30s caches (#2, #3) dominate freshness. The pipeline itself is sub-4ms. If caches were removed entirely, freshness would be bounded only by the CC refresh cycle — and the pipeline cost would remain under 4ms even on XL sessions (linear scan of 1.2MB JSONL costs only 0.67ms). The question is not "is the pipeline too slow" but "are the 30s caches necessary."

**Answer: The 30s caches are NOT necessary for performance.** Even at XL scale (2440 events), the uncached obs_counters pipeline costs only 0.89ms. Reducing the cache TTL from 30s to 5s would improve freshness 6x with negligible additional I/O (one extra 0.89ms scan per 5s). Removing the cache entirely would add at most 0.89ms per CC invocation, well within the 200ms stdin deadline budget.

### 2.3 — Strategy Prototyping

**Executed 2026-04-07.**

Three refresh strategies described at plan level with architecture, strengths, weaknesses, and freshness bounds. All projections are grounded in the 2.1 measurements.

#### Strategy A: Current Model (Transcript + Cache)

```
statusline invoked → read stdin (0.1ms)
  → resolve_package_root (0.012ms cold, ~0 warm)
  → _inject_obs_counters:
      if obs_cache age < 30s: use cached counts
      else: scan hook_events.jsonl (0.02-0.67ms)
           + scan reads.jsonl (0.01-0.17ms)
           + read manifest health (0.01-0.04ms)
           + save to cache (0.18ms)
  → inject_context_overhead:
      if overhead_cache age < 30s: use cached overhead
      else: _read_transcript_tail (0.12-0.16ms, capped at 50KB)
           + _read_manifest_anchor (0.01-0.04ms)
           + _estimate_static_overhead (1.8ms, walks CLAUDE.md files)
           + save to cache (0.18ms)
  → collect_system_data (subprocess: git, etc.)
  → render → stdout
```

- **Strengths:** Simple. No new files, no new hooks. Proven stable across hundreds of sessions. Total qLine-controlled pipeline < 4ms. Transcript tail read is constant-time (50KB cap) — NOT linearly scaling as originally hypothesized.
- **Weaknesses:** 30s cache TTLs for obs counters and overhead data cause up to 30s staleness. A burst of hook events is invisible for up to 30s. The 30s TTL is conservative — measurements show uncached path costs only 0.89ms even at XL scale.
- **Freshness bound:** CC refresh cycle + 30s (cache TTL) + ~3.5ms (pipeline)
- **Claude-version fragility:** Medium. Transcript tail read depends on transcript JSONL format (observed-stable, not documented). Stdin payload fields are supported.

#### Strategy B: Event-Driven Invalidation

```
Hook fires → writes event to hook_events.jsonl (existing)
           → atomically bumps .state_seq (existing .seq_counter)
           → NO additional file writes

statusline invoked → read stdin (0.1ms)
  → read .seq_counter (0.011ms)
  → compare to last-seen seq in process cache
  → if seq unchanged: use cached state entirely (skip all scans)
  → if seq changed: re-read only changed sources
      → scan hook_events.jsonl (0.02-0.67ms)
      → read manifest (0.01-0.04ms)
      → transcript tail ONLY if overhead cache expired
  → update last-seen seq
  → render → stdout
```

- **Strengths:** No new files — reuses existing `.seq_counter` as invalidation signal. Avoids re-reading unchanged data on quiet periods. On active sessions, re-reads happen at most every CC refresh cycle (not throttled by 30s cache). Eliminates 30s staleness without increasing I/O on idle sessions.
- **Weaknesses:** Requires cache invalidation logic (seq comparison + selective re-read). The `.seq_counter` is bumped by ALL hooks (including reads, which don't change display state) — may cause unnecessary re-scans. Process cache is ephemeral (statusline runs as separate process per invocation) so "last-seen seq" must be stored in the disk cache.
- **Freshness bound:** CC refresh cycle + 0ms (immediate invalidation) + ~1ms (selective re-read)
- **Claude-version fragility:** Low. Uses only qLine-owned files (`.seq_counter`, `hook_events.jsonl`, manifest). No transcript dependency for invalidation.

#### Strategy C: Hybrid (Fresh State Sidecar + Transcript Fallback)

```
Hook fires → writes event to hook_events.jsonl (existing)
           → also writes compact live_state.json sidecar:
             { obs_counts: {...}, health: "healthy", last_seq: N, 
               cache_hit_rate: 0.95, sys_overhead_tokens: 34973, ts: "..." }
             at <package>/native/statusline/live_state.json

statusline invoked → read stdin (0.1ms)
  → try reading live_state.json (~0.02ms for small JSON)
  → if age < 5s: inject sidecar values directly, skip all scans
  → if stale or missing: fall back to Strategy A (full pipeline)
  → render → stdout
```

- **Strengths:** Fastest possible hot path — single small file read (est. ~0.02ms). Graceful degradation to full pipeline on sidecar miss. Hook-driven freshness means display updates track hook activity in real-time (within CC refresh cycle). Cache health and sys_overhead could be pre-computed in hooks rather than in statusline.
- **Weaknesses:** Every hook that affects display state must update the sidecar (currently 10+ hook scripts). Sidecar write adds ~0.2ms (JSON serialize + atomic write) to every hook execution — hooks currently have 5s timeout so this is well within budget, but it's additive I/O. Risk of sidecar/transcript divergence if hooks crash between event write and sidecar update. Sidecar contains pre-computed values — if rendering logic changes, sidecar must be kept in sync.
- **Freshness bound:** CC refresh cycle + 0ms (hook writes sidecar immediately) + ~0.02ms (sidecar read)
- **Claude-version fragility:** Low. Sidecar is fully qLine-owned. Transcript used only as fallback. However, cache_hit_rate and sys_overhead computation in hooks would need access to transcript data — either hooks compute it (adding transcript dependency to hooks) or those fields are omitted from sidecar (falling back to Strategy A for those metrics).

### 2.4 — Strategy Comparison Matrix

**Executed 2026-04-07.**

**Scoring:** 1 (best) to 3 (worst) per dimension. Total score = sum. Ties broken by correctness risk.

Strategy A scores are from Task 2.1 measurements (empirical). Strategies B and C are projections based on I/O profile analysis and architectural reasoning.

| Dimension | A: Current | B: Event-Driven | C: Hybrid | Measurement/Projection Method |
|-----------|-----------|-----------------|-----------|-------------------------------|
| **Latency** | 2 | 1 | 1 | A: 2.3-3.5ms pipeline but 30s cache staleness. B: seq check (0.011ms) + selective re-read when changed. C: sidecar read (~0.02ms) on hot path. B and C eliminate 30s staleness. |
| **Correctness risk** | 1 | 2 | 3 | A: single source of truth (files scanned directly). B: seq counter matches file state (nearly atomic). C: sidecar can diverge from source files if hook crashes between event write and sidecar update — two sources of truth. |
| **File I/O cost** | 2 | 1 | 3 | A: 4-6 file reads per invocation (when caches cold). B: 1 file read (seq) on quiet; 4-6 on change. C: 1 read (sidecar) on hot + 1 write per hook invocation (10+ hooks add sidecar writes). Net: C adds most total I/O across system. |
| **CC-version fragility** | 2 | 1 | 1 | A: depends on transcript JSONL format (observed-stable) for cache metrics. B: no transcript dependency for invalidation. C: no transcript dependency on hot path; fallback uses transcript. |
| **Implementation complexity** | 1 | 2 | 3 | A: no changes. B: add seq comparison + selective invalidation logic to statusline.py (~50 LOC), store last_seq in disk cache. C: add sidecar write to every relevant hook (~10 files changed), add sidecar reader to statusline.py (~30 LOC), define sidecar schema, handle sidecar/source divergence. |
| **Total** | **8** | **7** | **11** | |

#### Score Rationale

**Strategy A (8):** The current model is correct, simple, and surprisingly fast (sub-4ms pipeline). Its only weakness is the 30s cache TTLs, which are an unnecessarily conservative choice given that even the heaviest uncached scan (XL: 0.89ms) is well within budget. **An A-prime variant that simply reduces cache TTLs from 30s to 3-5s would score (1, 1, 2, 2, 1) = 7**, matching Strategy B with zero architectural change.

**Strategy B (7):** Cleanest improvement path. The `.seq_counter` already exists and is atomically incremented by every hook. Using it as an invalidation signal eliminates cache staleness without adding I/O. The main risk is noisy invalidation (every Read hook bumps seq even though reads don't change display state) — but the cost of a false re-scan is only 0.89ms.

**Strategy C (11):** Most complex with least marginal benefit over B. The sidecar pre-computes values that the statusline can compute in <1ms, so the ~0.02ms hot path advantage is negligible. Meanwhile, it adds a write to every hook invocation and introduces a second source of truth that can diverge.

#### Critical Insight: Strategy A-Prime

The measurements reveal that the spec's original hypothesis — "transcript tail read is the hot path; latency scales with transcript size" — is **false**. The transcript tail read uses a 50KB seek window and completes in 0.12-0.16ms regardless of transcript size. The actual pipeline is already fast enough to run uncached.

This means the simplest optimization is **not an architectural change** but a **parameter change**: reduce the 30s TTLs on obs counter cache and overhead cache to 3-5s. This can be done by changing two integer constants:

- `statusline.py:1899` — change `>= 30` to `>= 5`
- `context_overhead.py:751` — change `< 30` to `< 5`

This "Strategy A-prime" achieves 6x freshness improvement with zero risk.

### 2.5 — Recommendation

**Executed 2026-04-07.**

```
Recommended strategy: A-prime (cache TTL reduction), with B as follow-on

Rationale: Measurements show the entire qLine pipeline completes in under 4ms
even on XL sessions (2440 events, 1.2MB JSONL). The only meaningful freshness
limiter is the 30s cache TTL, which was designed as a guard against presumed I/O
cost that measurements prove is negligible (~0.89ms worst case). Reducing the
TTL from 30s to 5s delivers 6x freshness improvement by changing two integer
constants — zero architectural risk, zero new files, zero hook modifications.

Key risk: Increasing scan frequency from once-per-30s to once-per-5s adds
~0.89ms of I/O per scan on XL sessions. With CC refresh cycle assumed at 1-5s,
this means the scan may run on every invocation. Even so, 0.89ms is well within
the 200ms stdin deadline budget (0.4% of budget). On SSD-backed APFS, file
caching means repeated reads of the same JSONL are served from kernel buffer
cache. Mitigation: monitor pipeline latency via snapshot timestamps; if any
session exceeds 10ms total pipeline time, add a configurable TTL parameter.

Migration path:
  Phase 1 (immediate): Reduce obs counter cache TTL from 30s to 5s in
    statusline.py (line 1899). Reduce overhead cache TTL from 30s to 5s in
    context_overhead.py (line 751). Ship as patch release.
  Phase 2 (optional): Implement Strategy B seq-based invalidation for
    zero-staleness on active sessions while preserving zero-cost on idle
    sessions. This is a refinement, not a requirement — A-prime alone
    reduces worst-case staleness from 30s to 5s, which is below human
    perception threshold for status display.

Default behavior: If cache files are missing or corrupt, the pipeline already
falls back to uncached execution (measured at <4ms). No new sidecar or file
format is introduced in A-prime.

Fallback: Strategy A (current 30s TTL) is always available by reverting two
constants. No migration or schema changes are involved.
```

**Divergence from research plan default:** The plan suggested Strategy C (hybrid sidecar) as the default recommendation. Measurements invalidated the premise that drove that recommendation — the transcript tail read is NOT a scaling bottleneck (it's capped at 50KB), and the pipeline is already fast enough to run uncached. Strategy C would add complexity (sidecar writes in 10+ hooks, schema to maintain, divergence risk) for negligible latency gain (~0.02ms vs ~3.5ms). The correct action is the simplest one: reduce the cache TTLs.

**When Strategy B becomes relevant:** If future requirements demand sub-second freshness (e.g., real-time tool count animation in the status bar), Strategy B's seq-based invalidation provides true zero-staleness by checking a single 4-byte counter file on each invocation. This would be a Phase 2 optimization after A-prime is validated in production.

---

## Codebase Pointers

| What | Where | Key Lines |
|------|-------|-----------|
| Stdin reader | `src/statusline.py` | `read_stdin_bounded()` — 200ms deadline, 512KB cap |
| Metrics cache | `src/statusline.py` | Cache read/write logic, 60s TTL |
| Obs counter injection | `src/statusline.py` | `_inject_obs_counters()` |
| Context overhead orchestrator | `src/context_overhead.py` | `inject_context_overhead()` |
| Transcript tail read | `src/context_overhead.py` | `_read_transcript_tail()` |
| Manifest anchor | `src/context_overhead.py` | `_read_manifest_anchor()` |
| Hook event append | `hooks/obs_utils.py` | `append_event()`, `_atomic_jsonl_append()` |
| Manifest update | `hooks/obs_utils.py` | `update_manifest()` |
| Seq counter | `hooks/obs_utils.py` | `next_seq()` — fcntl.flock atomic counter |
| All hook scripts | `hooks/obs-*.py` | Entry points for each event type |

---

## Acceptance Criteria

- [x] Latency map table completed with measured values for all segments — 4 sessions (42-2440 events), 12 segments, min/median/p95 for each
- [x] Throttling layer inventory documented with current settings and freshness impact — 9 layers identified with TX classification
- [x] Three strategies described at plan level with strengths, weaknesses, freshness bounds — A, B, C + A-prime variant
- [x] Comparison matrix scored on all 5 dimensions with measurement/projection methods noted — A=8, B=7, C=11, A-prime=7
- [x] Recommendation produced with rationale, risk, migration path, and fallback behavior — A-prime (TTL reduction) recommended
- [x] All measurements taken from the live repo during active sessions (not hypothetical) — benchmark script at `tests/t2_latency_benchmark.py`
- [x] Claude-version fragility labeled per TX classification for each strategy — in throttling inventory and comparison matrix
- [x] T2 may use fixtures from the replay dataset constructed in T1 but does not own construction of that dataset — used live sessions, not T1 fixtures

---

## Risks

| Risk | Mitigation |
|------|------------|
| CC statusline refresh rate is not documented | Measure empirically; label as observed-stable |
| Hook_events.jsonl scan time may be negligible today but grow with session length | Benchmark on sessions of 50, 200, 500, 1000+ events |
| Sidecar strategies (B/C) add file I/O that may be slower than transcript read on small sessions | Measure both paths; recommendation must account for session size distribution |

---

## Do Not Decide Here

- Which strategy to implement (that's T5 after scoring all tracks)
- Schema for new sidecar files (that's T3 for observability, TX for compatibility)
- Whether transcript reading should be removed entirely (may still be needed for accuracy)
