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

**Constants to validate (lines 48-52):**

| Constant | Claimed Value | Validation Method |
|----------|---------------|-------------------|
| `_SYSTEM_PROMPT_TOKENS` | 6200 | Compare against actual first-turn system message token count from a fresh session transcript |
| `_SYSTEM_TOOLS_TOKENS` | 11600 | Count actual tool definitions in a session with no deferred tools |
| `_SESSION_START_OVERHEAD` | 3500 | Measure actual hook/skill expansion tokens at session start |
| `CC_OUTPUT_RESERVE` | 20000 | Verify against Claude Code documented or observed output budget |
| `CC_AUTOCOMPACT_BUFFER` | 13000 | Verify against Claude Code compaction trigger behavior |

**Functions to audit:**

| Function | What It Claims | Validation Approach |
|----------|---------------|---------------------|
| `_estimate_static_overhead()` | Phase 1: file-size-based token estimate from CLAUDE.md, MEMORY.md, tool counts, MCP server count | Compare estimate against actual first-turn token counts from transcript |
| `_read_transcript_tail()` | Extracts cache_create and cache_read from last 5 turns | Run against 5+ real transcripts; verify extracted values match raw transcript entries |
| `_read_transcript_anchor()` | Extracts baseline system overhead from first turn | Run against transcripts from sessions with varying MCP/plugin configs |
| `_read_manifest_anchor()` | Reads cached anchor from manifest.json | Verify manifest values match what the anchor-writing hook actually stored |
| `inject_context_overhead()` | Orchestrates Phase 1 + Phase 2 and injects into render state | End-to-end validation: known input → expected state |

### 1.2 — Statusline Metric Audit

Audit derived metrics in `src/statusline.py`:

| Metric | Function(s) | Validation |
|--------|-------------|------------|
| Context bar % | `render_context_bar()` | Verify formula: `(used_tokens / max_tokens) * 100` with correct deductions for overhead, reserve, buffer |
| Cache health state | cache health logic in context_overhead | Replay sessions with known cache patterns: healthy, degraded, busting |
| Cost formatting | `_format_cost()` | Verify rounding, currency symbol, edge cases ($0.00, >$100) |
| Duration formatting | `_format_duration()` | Verify auto-format thresholds: seconds, minutes+seconds, hours+minutes |
| Obs counters | `_inject_obs_counters()` | Count events in a known session's hook_events.jsonl, compare against what statusline reports |
| Read/reread ratio | obs_reads/obs_rereads modules | Verify reread detection logic against .read_state sidecar |

### 1.3 — Assumption Validation Checklist

These are the specific assumptions called out in the research plan. Each must be validated or falsified with evidence:

| # | Assumption | Status | Evidence |
|---|-----------|--------|----------|
| A1 | Transcript parsing paths correctly identify stop entries for cache extraction | | |
| A2 | Cache anchor derivation selects the right first-turn entry and warm-cache fallback is correct | | |
| A3 | Cache hit-rate formula is mathematically correct; busting/degraded thresholds match real-world patterns | | |
| A4 | System-overhead estimate correctly accounts for CLAUDE files, MCP servers, plugin stubs, and settings | | |
| A5 | Obs counter values from hook_events.jsonl match actual event counts (no off-by-one, no missed events) | | |
| A6 | Stale-session and stale-transcript risks on resume/continue flows are handled (session_id reuse, transcript truncation) | | |

**Note:** Status and Evidence fields are filled by the executing sub-agent during T1 execution. Empty cells above are intentional placeholders.

For each assumption, fill in: **validated** / **partially valid** / **falsified**, plus the evidence artifact (replay output, transcript comparison, or manual calculation).

### 1.4 — Replay Dataset Construction

Build the replay dataset per TX conventions:

**From existing fixtures:**
- Copy/symlink all 12 files from `tests/fixtures/statusline/` into `tests/replay/fixtures/from-tests/`

**From real sessions (curate 3-5):**

| Scenario | Selection Criteria | Session Date Range |
|----------|-------------------|-------------------|
| Short, clean | < 10 hook events, no compaction, no failures | Any recent |
| Medium, varied | 50-200 events, multiple tool types, cache metrics present | Apr 4-7 |
| Long, compacted | 500+ events, at least one compaction event | Any |
| Subagent-heavy | Multiple subagent.spawned events | Any |
| Error-rich | Multiple failure.posttool events or degraded health | Any |

**Synthetic edge cases (author new):**

| Fixture | Tests What |
|---------|-----------|
| `synthetic/cache-busting-rapid.json` | Cache health transitions: healthy → degraded → busting within 5 turns |
| `synthetic/compaction-mid-session.json` | Overhead anchor invalidation after compaction |
| `synthetic/transcript-truncated.json` | Transcript file shorter than expected (tail read hits EOF early) |
| `synthetic/stale-resume.json` | Session resumed after >1 hour gap; transcript has new session_id entries |
| `synthetic/zero-cache-read.json` | Every turn has cache_create but cache_read=0 (cold session) |
| `synthetic/missing-hook-data.json` | hook_events.jsonl missing or empty; statusline must degrade gracefully |

### 1.5 — Accuracy Gaps Table

**Deliverable format:**

| ID | Severity | Metric | Root Cause Hypothesis | Reproduction | Confidence | Recommended Fix | Classification |
|----|----------|--------|-----------------------|--------------|------------|-----------------|----------------|
| AG-01 | | | | | | | supported / fragile |

Severity levels:
- **Critical:** metric produces wrong value that misleads user decisions (e.g., context bar shows 40% when actually 70%)
- **Major:** metric is directionally correct but materially inaccurate (e.g., overhead off by >20%)
- **Minor:** metric is slightly off but doesn't affect user decisions (e.g., cache hit rate off by 2%)

---

## Codebase Pointers

| What | Where | Key Lines |
|------|-------|-----------|
| Overhead constants | `src/context_overhead.py` | ~48-52 (constants block — verify actual line numbers before auditing) |
| Static estimation | `src/context_overhead.py` | `_estimate_static_overhead()` |
| Transcript tail read | `src/context_overhead.py` | `_read_transcript_tail()` |
| Transcript anchor read | `src/context_overhead.py` | `_read_transcript_anchor()` |
| Manifest anchor read | `src/context_overhead.py` | `_read_manifest_anchor()` |
| Main orchestrator | `src/context_overhead.py` | `inject_context_overhead()` |
| Context bar render | `src/statusline.py` | `render_context_bar()` |
| Obs counter injection | `src/statusline.py` | `_inject_obs_counters()` |
| Cache metrics write | `hooks/obs-stop-cache.py` | Main write path |
| Session manifest | `hooks/obs_utils.py` | `update_manifest()`, `create_package()` |
| Existing test fixtures | `tests/fixtures/statusline/*.json` | All 12 files |
| Real session transcripts | `~/.claude/observability/sessions/*/` | `metadata/hook_events.jsonl`, `custom/cache_metrics.jsonl` |

---

## Acceptance Criteria

- [ ] All 5 constants in context_overhead.py validated or flagged with evidence
- [ ] All 6 assumptions in the validation checklist have a status and evidence artifact
- [ ] Replay dataset constructed: existing fixtures + 3-5 real sessions + 6 synthetic edge cases
- [ ] Every function in the audit tables has been run against replay data with results documented
- [ ] Accuracy gaps table populated with at least severity, metric, root cause, and confidence for every gap found
- [ ] Each gap classified as supported/observed-stable/fragile/speculative per TX standards
- [ ] Recommended fixes are scoped (not open-ended) and reference specific functions

---

## Risks

| Risk | Mitigation |
|------|------------|
| Transcript format varies between CC versions | Note CC version for each real session used; flag version-dependent findings |
| Cache metrics depend on model behavior that changes across Claude model updates | Use multiple sessions across different dates to detect variance |
| Real session data may contain sensitive paths or content | Strip or hash any user-content fields before including in replay dataset |

---

## Do Not Decide Here

- Whether to change the cache health thresholds (propose in accuracy gaps table, decide in T5)
- Whether to switch from transcript-based to event-driven cache tracking (that's T2 territory)
- Whether new observability fields are needed (that's T3)
- Ranking of fixes by priority (that's T5)
