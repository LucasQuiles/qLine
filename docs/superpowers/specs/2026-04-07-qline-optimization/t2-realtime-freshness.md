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

Measure each segment of the event-to-display pipeline:

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

**Measurements needed:**

| Segment | What to Measure | Method |
|---------|----------------|--------|
| A: Hook dispatch latency | Time from Claude event to hook process start | Timestamp in hook vs event timestamp in stdin |
| B-D: Hook I/O | Time for JSONL append + manifest update | Instrument hooks with timing output to stderr |
| E: Statusline refresh interval | How often Claude Code calls the statusline command | Log invocation timestamps over a 5-minute active session |
| F: Stdin read | Time in `read_stdin_bounded()` | Already has 200ms deadline; measure actual |
| G-I: Overhead computation | Time in `inject_context_overhead()` | Time the function; break down Phase 1 vs Phase 2 |
| H: Transcript tail read | Time to read last 5 turns from transcript JSONL | Time `_read_transcript_tail()` |
| J-K: Obs counter scan | Time to scan hook_events.jsonl for counts | Time `_inject_obs_counters()` on sessions of varying size |
| L: Cache I/O | Time for cache read + conditional write | Time cache operations in `statusline.py` |
| M: Total render | End-to-end statusline execution time | Time from stdin read to stdout write |

**Deliverable:** Latency map table with segments, measured values (min/median/p95), and bottleneck identification.

### 2.2 — Throttling Layer Inventory

Document every throttling/caching mechanism and its effect on freshness:

| Layer | Mechanism | Current Setting | Effect on Freshness |
|-------|-----------|-----------------|---------------------|
| Claude Code statusline refresh | CC calls statusline command on a cycle | Unknown — measure | Upper bound on display freshness |
| qLine metrics cache | `/tmp/qline-cache.json` with 60s TTL | 60s | System metrics (CPU, mem, disk, git) lag up to 60s |
| Transcript tail window | Reads last 5 turns only | 5 turns | Cache metrics reflect recent window, not full session |
| Hook event scan | Full file scan on each invocation | No throttle | Grows linearly with session length |
| Snapshot throttling | Obs snapshot rate limiting | Check obs_utils.py | May suppress rapid-fire updates |
| Manifest read | Read on each invocation | No cache | Always fresh but adds I/O |

### 2.3 — Strategy Prototyping

Design three refresh strategies at the plan level (no implementation, just architecture + expected behavior):

#### Strategy A: Current Model (Transcript + Cache)

```
statusline invoked → read stdin → read transcript tail → read manifest
  → read hook_events.jsonl → compute metrics → write cache → render
```

- **Strengths:** Simple, no new files, no new hooks
- **Weaknesses:** Transcript tail read is the hot path; latency scales with transcript size; stale on resume
- **Freshness bound:** CC refresh cycle + transcript write latency + tail read latency

#### Strategy B: Event-Driven Invalidation

```
Hook fires → writes event to hook_events.jsonl (same as current behavior)
           → also bumps a monotonic counter in a "freshness sidecar"
             (e.g., <package>/metadata/.state_seq)

statusline invoked → read stdin → check .state_seq
  → if seq unchanged since last render: use cached state
  → if seq changed: re-read only the sources that could have changed
  → render
```

- **Strengths:** Avoids re-reading unchanged data; freshness tracks hook activity, not transcript timing
- **Weaknesses:** Requires new sidecar file; cache invalidation logic adds complexity; seq collisions on concurrent hooks
- **Freshness bound:** CC refresh cycle + sidecar write latency (near-instant)
- **Claude-version fragility:** Low (uses own sidecar, not transcript timing)

#### Strategy C: Hybrid (Fresh State Sidecar + Transcript Fallback)

```
Hook fires → writes event to hook_events.jsonl (same as current behavior)
           → also writes a compact "fresh state" JSON sidecar
             (e.g., <package>/native/statusline/live_state.json)
             containing: obs counts, cache metrics, health, last_seq, last_ts

statusline invoked → read stdin → try live_state.json first
  → if fresh (age < 5s): use sidecar values directly, skip transcript/manifest reads
  → if stale or missing: fall back to current model (transcript + manifest)
  → render
```

- **Strengths:** Fastest hot path (one small file read); graceful fallback; transcript used only as backup
- **Weaknesses:** Sidecar must be maintained by all hooks that produce relevant state; risk of sidecar/transcript divergence
- **Freshness bound:** CC refresh cycle + sidecar age threshold (5s default)
- **Claude-version fragility:** Low (sidecar is owned by qLine)

### 2.4 — Strategy Comparison Matrix

Score each strategy on 5 dimensions:

| Dimension | A: Current | B: Event-Driven | C: Hybrid | Measurement Method |
|-----------|-----------|-----------------|-----------|-------------------|
| **Latency** (lower = better) | | | | Measured in 2.1; projected for B/C based on I/O profile |
| **Correctness risk** (lower = better) | | | | How many sources of truth; divergence scenarios |
| **File I/O cost** (lower = better) | | | | Count of file reads/writes per statusline invocation |
| **Claude-version fragility** (lower = better) | | | | Per TX classification: supported/observed-stable/fragile |
| **Implementation complexity** (lower = better) | | | | New files, changed functions, hook modifications |

**Scoring:** 1 (best) to 3 (worst) per dimension. Total score = sum. Ties broken by correctness risk.

**Note:** Strategy A scores must be populated from Task 2.1 measurements (empirical). Strategies B and C scores are projections based on I/O profile analysis and architectural reasoning.

### 2.5 — Recommendation

Produce a recommendation using this template:

```
Recommended strategy: [A / B / C]
Rationale: [2-3 sentences]
Key risk: [primary risk and mitigation]
Migration path: [how to get from A → recommended without breaking existing sessions]
Default behavior: [what happens if the new sidecar/file is missing — must fall back gracefully]
```

**Default recommendation from research plan:** Prefer hybrid event-driven invalidation (C) if it materially reduces staleness without making statusline correctness depend on undocumented transcript timing. If measurements show Strategy A is already within 1s of real-time, the complexity of B or C may not be justified.

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

- [ ] Latency map table completed with measured values for all segments
- [ ] Throttling layer inventory documented with current settings and freshness impact
- [ ] Three strategies described at plan level with strengths, weaknesses, freshness bounds
- [ ] Comparison matrix scored on all 5 dimensions with measurement/projection methods noted
- [ ] Recommendation produced with rationale, risk, migration path, and fallback behavior
- [ ] All measurements taken from the live repo during active sessions (not hypothetical)
- [ ] Claude-version fragility labeled per TX classification for each strategy
- [ ] T2 may use fixtures from the replay dataset constructed in T1 but does not own construction of that dataset

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
