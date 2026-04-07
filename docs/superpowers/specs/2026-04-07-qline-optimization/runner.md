# qLine Optimization Research — Runner

## Purpose

Orchestration-only document. Owns the execution graph, gates, deliverable checklist, and convergence criteria for the qLine optimization and observability research tree. All implementation decisions belong in track outputs and converge through T5.

**Target repo:** `/Users/q/LAB/qLine`
**Stale clone:** `/Users/q/qline` — ignored unless an explicit sync task is added.

---

## Plan Tree

```
docs/superpowers/specs/2026-04-07-qline-optimization/
├── runner.md               ← this file
├── t0-baseline-repo-truth.md
├── t1-accuracy-audit.md
├── t2-realtime-freshness.md
├── t3-observability-expansion.md
├── t4-external-scan.md
├── t5-experiment-matrix.md
└── tx-data-contracts.md
```

---

## Track Status

| Track | Name | Status | Gate | Deliverable |
|-------|------|--------|------|-------------|
| T0 | Baseline & Repo Truth | **complete** | — | architecture map, test failure taxonomy (38 failures, 7 must-fix), must-fix list |
| TX | Data Contracts | **complete** | — | public interface registry (verified against source), replay harness spec, experiment template |
| T1 | Accuracy Audit | **complete** | T0 + TX approved | 8 accuracy gaps (1 critical AG-01), replay dataset (58 files), recommended fixes |
| T2 | Real-Time Freshness | **complete** | T0 + TX approved | pipeline 4ms, 30s TTL is bottleneck, recommends A-prime (5s TTL) |
| T3 | Observability Expansion | **complete** | T0 + TX approved | 32 sources, 15 visibility gaps, 8 schema proposals with classifications |
| T4 | External Scan | **complete** | T0 + TX approved | 24 surfaces classified, 18 issues, 7 upstream risks |
| T5 | Experiment Matrix | **complete** | T1-T4 stable | 27 opportunities ranked, 26 backlog items (7 Tier 1, 15 Tier 2, 4 Tier 3) |

---

## Dependency Graph

```
T0 (Baseline) ─── gates all downstream
│
├── TX (Data Contracts) ── authored alongside T0, referenced by T1-T5
│
├── T1 (Accuracy)       ─┐
├── T2 (Real-Time)       ├── parallel after T0 gate
├── T3 (Observability)   │
└── T4 (External Scan)  ─┘
                          │
                          └── T5 (Convergence) ── after T1-T4 stable
                               │
                               └── Implementation spec ── only after T5 ranks and selects
```

---

## Execution Order

1. **Phase 0** — T0 and TX execute first. T0 produces the architecture map, test failure taxonomy, and must-fix list. TX defines shared artifact formats, compatibility rules, and evidence standards. Both must be approved before downstream tracks start.

2. **Phase 1** — T1, T2, T3, T4 run in parallel. Each reads T0 outputs and TX contracts. Each produces its own deliverable tables independently.

3. **Phase 2** — T5 starts only after all Phase 1 tracks have produced stable outputs. T5 assembles the ranked experiment matrix and categorized implementation backlog.

4. **Phase 3** — Implementation spec or bead tree is authored only after T5 ranks and the user selects the recommended path. Not in scope for this research tree.

---

## Gate Rules

### T0 Gate (blocks Phase 1)
- Architecture map covers: repo layout, plugin symlink, settings.json hooks, session package structure, observability runtime paths
- Test failure taxonomy classifies every `tests/test-statusline.sh` failure into: harness portability, fixture drift, rendering regression, logic defect, path assumption
- Must-fix list is explicit and bounded (not open-ended)

### Phase 1 Gate (blocks T5)
Each track must produce:
- Its named deliverable tables (see Track Status above)
- Evidence for every claimed issue or opportunity
- Explicit "supported vs fragile" labels on anything depending on undocumented Claude behavior

### T5 Gate (blocks implementation)
- Experiment matrix ranks all opportunities by: impact, risk, latency gain, correctness gain, implementation cost
- Implementation backlog is categorized into: safe additive, needs migration, depends on upstream Claude support
- At least one recommended path for each of: accuracy fixes, fresher updates, richer observability

---

## Deliverable Checklist

### Phase 0 outputs
- [x] `t0-baseline-repo-truth.md` — completed with all sections populated
- [x] Architecture map (inline in T0 — 24 components, 8558 lines, 10 runtime artifacts)
- [x] Test failure taxonomy (38 failures: 14 harness, 9 fixture, 7 rendering, 6 logic, 2 path)
- [x] Must-fix-before-experiment list (7 items: MF-01 through MF-07)
- [x] `tx-data-contracts.md` — completed, verified against source (5 event names corrected, stdin fields validated)

### Phase 1 outputs
- [x] T1: accuracy gaps table (8 gaps: AG-01 critical, AG-02/07/08 major, AG-03-06 minor)
- [x] T1: replay dataset (58 files: 12 from-tests + 5 real sessions + 3 transcripts + 6 synthetic)
- [x] T2: end-to-end latency benchmarks (4ms pipeline, 30s cache TTL is bottleneck)
- [x] T2: four-strategy comparison matrix scored on 5+ dimensions (A, A-prime, B, C)
- [x] T3: source inventory table (32 sources: 10 hot-path, 5 static estimation, 17 hook-only)
- [x] T3: missing visibility table (15 gaps: MV-01 through MV-15, 8 schema proposals)
- [x] T4: supported-vs-unsupported dependency table (24 surfaces: 17 supported, 1 observed-stable, 4 fragile, 2 speculative)
- [x] T4: upstream risk register (7 risks: UR-01 through UR-07)

### Phase 2 outputs
- [x] T5: ranked experiment matrix (27 opportunities, scores recomputed and verified)
- [x] T5: categorized implementation backlog (7 Tier 1, 15 Tier 2, 4 Tier 3)
- [x] T5: recommended paths for accuracy (6-step), freshness (3-step), observability (7-step)

---

## Handoff Rules

- Track runners produce outputs inline in their spec doc (tables, findings sections).
- Large artifacts (replay datasets, benchmark logs) go under `tests/` or `docs/` as appropriate, referenced from the track doc.
- Track runners do not modify `src/`, `hooks/`, or `tests/` unless explicitly executing a must-fix from T0.
- The runner doc is updated (status table) as tracks complete.
- Conflicts between tracks are resolved in T5, not in individual tracks.

---

## Context Management

Each track spec is self-contained. A sub-agent executing a track reads:
1. Its own track spec (primary)
2. `tx-data-contracts.md` (shared reference)
3. T0 outputs (if Phase 1+)
4. Relevant source files from `/Users/q/LAB/qLine/` as pointed to in the spec

Sub-agents do NOT need to read other track specs or this runner doc. The orchestrator (main context) reads only this runner and track status updates.
