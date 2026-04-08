# Task: qLine Comprehensive Remediation

**ID:** qline-remediation-001
**Profile:** BUILD
**Complexity:** COMPLICATED
**Created:** 2026-04-07
**Status:** Execute

## Mission Brief

Systematically address all 4 remaining work tracks from the 2026-04-07 optimization session:

1. **40 test failures** → 0 (fix tests and code to reach 235/235)
2. **Remaining dedup** — 3 unfinished consolidation items (L3 factory, overhead wiring, shim removal)
3. **Tier 1 backlog** — 7 safe additive OPP items (15, 18, 12, 16, 17, 14, 25)
4. **Alert system audit** — verify 8 triggers, fix issues, add tests

## Definition of Done

- `bash tests/test-statusline.sh` passes 235/235 + new tests
- All render_obs_* functions use factory pattern
- generate_overhead_report uses extract_usage_full
- All 7 Tier 1 OPP items implemented with tests
- Alert system audited with written findings and new tests
- All changes committed on `main`

## Phase Log

| Phase | Status | Notes |
|-------|--------|-------|
| 0: Normalize | complete | Clean state, extensive prior research exists |
| 1: Frame | complete | Mission brief above, derived from handoff doc |
| 2: Scout | complete | Full codebase analysis done in prior session (T0-T5 specs) |
| 3: Architect | complete | 12-bead manifest below |
| 4: Execute | active | Dispatching runners |

## Bead Manifest

See `beads/` directory. 12 beads in 5 waves:

**Wave 1 — Test Harness (parallel):**
- B01: Harness portability (bash 3.2, wc -l, mktemp)
- B02: Glyph drift + legacy stub tests
- B03: Stale dimming + ANSI color tests
- B04: Context bar + overhead tests
- B05: Obs snapshot + hook integration tests

**Wave 2 — Dedup (parallel, after Wave 1):**
- B06: render_obs_* factory pattern
- B07: Wire generate_overhead_report + remove shim

**Wave 3 — Tier 1 Backlog (parallel, after Wave 2):**
- B08: OPP-15 schema version + OPP-16 compaction event + OPP-25 transcript tests
- B09: OPP-18 hook fault surfacing + OPP-12 hook perf sidecar
- B10: OPP-17 hook coverage + OPP-14 parse diagnostics

**Wave 4 — Alert Audit (after Wave 1):**
- B11: Alert system audit + fixes + tests

**Wave 5 — Verification:**
- B12: Full suite run + deploy
