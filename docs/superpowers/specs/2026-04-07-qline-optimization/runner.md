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
| T0 | Baseline & Repo Truth | not started | — | architecture map, test failure taxonomy, must-fix list |
| TX | Data Contracts | not started | — | public interface registry, replay harness spec, experiment template |
| T1 | Accuracy Audit | not started | T0 + TX approved | accuracy gaps table, replay dataset, recommended fixes |
| T2 | Real-Time Freshness | not started | T0 + TX approved | latency benchmarks, strategy comparison matrix, recommendation |
| T3 | Observability Expansion | not started | T0 + TX approved | source inventory, missing visibility map, additive schema proposals |
| T4 | External Scan | not started | T0 + TX approved | supported-vs-unsupported table, upstream risk register |
| T5 | Experiment Matrix | not started | T1-T4 stable | ranked opportunity matrix, categorized implementation backlog |

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
- [ ] `t0-baseline-repo-truth.md` — completed with all sections populated
- [ ] Architecture map (inline in T0 or linked artifact)
- [ ] Test failure taxonomy (table in T0)
- [ ] Must-fix-before-experiment list (table in T0)
- [ ] `tx-data-contracts.md` — completed with interface registry, harness spec, templates

### Phase 1 outputs
- [ ] T1: accuracy gaps table with severity, metric, root cause, reproduction, fix
- [ ] T1: replay dataset (fixtures + curated sessions + synthetic edge cases)
- [ ] T2: end-to-end latency benchmarks for current flow
- [ ] T2: three-strategy comparison matrix scored on 5 dimensions
- [ ] T3: source inventory table (source, location, questions it answers)
- [ ] T3: missing visibility table (gap, impact, proposed schema)
- [ ] T4: supported-vs-unsupported dependency table
- [ ] T4: upstream risk register (known regressions, missing surfaces)

### Phase 2 outputs
- [ ] T5: ranked experiment matrix (top 10+ opportunities)
- [ ] T5: categorized implementation backlog
- [ ] T5: recommended paths for accuracy, freshness, observability

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
