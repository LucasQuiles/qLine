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

Gather every distinct opportunity from T1-T4 into a flat list. An "opportunity" is any change that improves accuracy, freshness, observability, or reduces fragility.

**Collection sources:**

| Track | Opportunity Type | Where to Find |
|-------|-----------------|---------------|
| T1 | Accuracy fixes | Accuracy gaps table (AG-* entries) |
| T1 | Assumption corrections | Assumption validation checklist (A1-A6) |
| T2 | Refresh strategy change | Recommended strategy from comparison matrix |
| T2 | Throttling adjustments | Throttling layer inventory (specific layers to tune) |
| T3 | New observability fields | Schema proposals (MV-* entries with proposed schemas) |
| T3 | Missing visibility fills | Missing visibility table (high/medium impact items) |
| T4 | Fragility reduction | Upstream risk register (mitigation options for fragile/speculative deps) |
| T4 | Dependency hardening | Supported-vs-unsupported table (items to move toward supported) |

### 5.2 — Experiment Matrix

Score every opportunity using the experiment template from TX. This is the primary deliverable.

**Matrix format:**

| Rank | ID | Title | Track | Impact | Risk | Latency Gain | Correctness Gain | Obs Gain | Impl Cost | Fragility Change | Score |
|------|-----|-------|-------|--------|------|-------------|------------------|----------|-----------|-----------------|-------|
| 1 | | | | | | | | | | | |
| 2 | | | | | | | | | | | |
| ... | | | | | | | | | | | |

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

**Column-to-formula mapping:** "Correctness Gain" = Correctness in formula; "Impl Cost" = Cost in formula; "Obs Gain" = Obs in formula; "Fragility Change" = Fragility in formula.

Max possible: 15 + 10 + 3 + 6 + 3 + 5 + 2 = 44

### 5.3 — Top 10 Deep Dives

For the top 10 ranked opportunities, produce a full experiment write-up using the TX template:

```markdown
### EXP-<track>-<seq>: <title>

**Hypothesis:** ...
**Changed source(s):** ...
**Measurement method:** ...
**Metrics captured:** (latency delta, correctness delta, fragility risk, obs gain)
**Claude-version sensitivity:** ...
**Implementation cost:** ...
**Evidence:** (reference to T1-T4 finding)
```

### 5.4 — Implementation Backlog

Categorize all ranked opportunities into three implementation tiers:

#### Tier 1: Safe Additive
Changes that add new capability without modifying existing behavior. Can be implemented and deployed independently. Low regression risk.

**Criteria:**
- Only adds new files, new manifest keys, new event types, or new modules
- Existing tests pass without modification
- No changes to existing hook behavior or statusline output
- Falls back gracefully if new artifacts are missing

#### Tier 2: Needs Migration
Changes that modify existing behavior or data formats. Require a migration path and backward compatibility consideration.

**Criteria:**
- Modifies existing functions, formulas, or thresholds
- May require updating test fixtures or expected outputs
- Needs a compatibility path for existing session packages
- Should be deployed with a feature flag or gradual rollout

#### Tier 3: Depends on Upstream Claude Support
Changes that can't be fully implemented without new Claude Code features, documented APIs, or upstream fixes.

**Criteria:**
- Requires a currently-undocumented or fragile surface to become stable
- Depends on a new hook event, stdin field, or API surface
- Blocked by an open Claude Code issue
- Can be partially implemented with a best-effort fallback

**Backlog format:**

| Priority | ID | Title | Tier | Dependencies | Effort | Acceptance Criteria |
|----------|-----|-------|------|-------------|--------|-------------------|
| P1 | | | 1/2/3 | | S/M/L | |

### 5.5 — Recommended Paths

Produce at least one recommended path for each of the three research goals:

**Accuracy path:** Which T1 findings should be fixed first, in what order, with what validation?

**Freshness path:** Which T2 strategy should be adopted, with what migration plan and what fallback?

**Observability path:** Which T3 proposals should be implemented first, with what schema and what reader?

Each path should reference specific backlog items by ID and include:
- Prerequisites (must-fix items from T0)
- Implementation sequence
- Validation method (how to know it worked)
- Rollback plan (how to undo if it doesn't)

---

## Acceptance Criteria

- [ ] All opportunities from T1-T4 collected into flat list (no orphaned findings)
- [ ] Experiment matrix scored and ranked with all dimensions filled
- [ ] Top 10 opportunities have full TX-format experiment write-ups
- [ ] Implementation backlog categorized into three tiers
- [ ] Every backlog item has dependencies, effort estimate, and acceptance criteria
- [ ] At least one recommended path for accuracy fixes
- [ ] At least one recommended path for fresher real-time updates
- [ ] At least one recommended schema path for richer observability
- [ ] Backlog items reference their source track findings by ID
- [ ] No implementation decisions made that contradict track findings

---

## Convergence Checklist

Before T5 is marked complete, verify these cross-track consistency checks:

- [ ] Every T1 accuracy gap appears in the backlog (either as a fix or as "accepted risk" with rationale)
- [ ] T2's recommended strategy is represented in the backlog with appropriate tier
- [ ] T3's high-impact schema proposals are in the backlog
- [ ] T4's fragile dependencies are either mitigated in the backlog or explicitly accepted
- [ ] No backlog item contradicts TX data contracts (no breaking changes in Tier 1)
- [ ] Must-fix items from T0 are listed as prerequisites for relevant backlog items
- [ ] Evidence fields in EXP-* write-ups link to source findings by their track-native IDs (AG-* from T1, MV-* from T3, UR-* from T4, A* from T1 assumptions) — ID format parity is not required, only traceability

---

## Risks

| Risk | Mitigation |
|------|------------|
| Track outputs may be inconsistent or contradictory | Convergence checklist catches conflicts; resolve by referencing evidence |
| Scoring is subjective | Use evidence-based scoring; document rationale for non-obvious scores |
| Backlog may be too large to execute | Recommended paths select the highest-impact subset; user approves scope |

---

## Do Not Decide Here

- Which backlog items to actually implement (user approval required after T5)
- Timeline or sprint assignments (out of scope for research)
- Whether to request upstream Claude Code changes (requires separate decision)
