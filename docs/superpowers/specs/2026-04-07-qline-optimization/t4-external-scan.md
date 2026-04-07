# T4 — External Scan

## Objective

Ground qLine's assumptions in official Claude Code documentation. Scan public issues for known regressions and missing surfaces. Compare against adjacent patterns only where they inform concrete design choices. Produce a supported-vs-unsupported dependency table and upstream risk register.

## Non-Goals

- Comprehensive competitive analysis of all terminal statusline tools
- Reverse-engineering undocumented Claude Code internals beyond what's observable
- Proposing qLine changes (this track produces a dependency table; changes come from T5)
- Testing or measuring anything (that's T1/T2)

---

## Inputs

- T0: architecture map (which Claude surfaces qLine uses)
- TX: supported-vs-fragile classification definitions, evidence standards
- Official Anthropic Claude Code documentation
- Public Claude Code GitHub issues and discussions
- Live repo at `/Users/q/LAB/qLine` (for checking which features depend on which surfaces)

---

## Tasks

### 4.1 — Official Documentation Audit

Consult official Anthropic Claude Code docs for the definitive behavior of every surface qLine depends on:

| Surface | What qLine Depends On | Documented? | Doc Source | Notes |
|---------|----------------------|-------------|------------|-------|
| Statusline stdin JSON payload | Field names: `cwd`, `model`, `session_id`, `conversation`, `duration_ms`, `total_cost_usd`, `num_turns` | | | |
| Statusline refresh behavior | How often CC calls the statusline command; conditions that trigger refresh | | | |
| Hook lifecycle events | `SessionStart`, `Stop`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `UserPromptSubmit`, `PreCompact`, `SubagentStop`, `TaskCompleted`, `SessionEnd` | | | |
| Hook input payload schema | JSON structure passed to each hook type via stdin | | | |
| Hook timeout behavior | What happens when a hook exceeds timeout; does CC kill the process? | | | |
| Hook exit code semantics | Exit 0 = success; nonzero = ? (abort tool? log warning? ignore?) | | | |
| `${CLAUDE_PLUGIN_ROOT}` substitution | Variable expansion in hooks.json command paths | | | |
| Transcript JSONL format | Structure of conversation transcript files; location; update timing | | | |
| Session ID semantics | When session_id changes; behavior on resume/continue; uniqueness guarantees | | | |
| Context window budget | Max tokens, output reserve, compaction trigger thresholds | | | |
| Cache behavior | cache_creation_input_tokens, cache_read_input_tokens fields in API responses | | | |
| Plugin installation | .claude-plugin/plugin.json schema; hooks.json schema; symlink discovery | | | |

**For each surface:** fill in Documented? (yes/no/partial), reference the specific doc page or section, and note any gaps or ambiguities.

### 4.2 — Public Issue Scan

Search the Claude Code GitHub issues (anthropics/claude-code or equivalent public tracker) for known problems affecting qLine's dependencies:

**Search areas:**

| Topic | Search Terms | What We're Looking For |
|-------|-------------|----------------------|
| Statusline | statusline, status line, status_line | Missing fields, refresh bugs, stdin payload changes |
| Hook reliability | hook, PostToolUse, PreToolUse, timeout | Hook not firing, timeout kills, event ordering issues |
| Session/transcript | session, transcript, resume, continue | Stale session_id, transcript truncation, resume behavior |
| Context/cache | context, cache, compaction, compact | Cache metric accuracy, compaction trigger changes, context budget changes |
| Plugin | plugin, .claude-plugin, hooks.json | Plugin discovery changes, hooks.json schema changes |

**For each relevant issue found:**

| Issue # | Title | Status | Impact on qLine | Affected Surface | Severity |
|---------|-------|--------|-----------------|------------------|----------|
| | | | | | |

**Note:** Table rows are filled by the executing sub-agent during T4. If no relevant issues are found for a search area, produce a "no relevant issues found" row with a note on search coverage and terms used.

### 4.3 — Adjacent Pattern Comparison

Compare qLine's approach against adjacent terminal/statusline patterns ONLY where the comparison informs a concrete T2 or T3 design choice:

| Pattern | Where Used | Relevance to qLine |
|---------|-----------|-------------------|
| Event-driven vs polling refresh | Terminal multiplexers (tmux status), shell prompts (starship, p10k) | Informs T2 strategy B/C: how do other tools handle event → display latency? |
| Prompt/status cache invalidation | Shell prompt tools | Informs T2 cache TTL strategy: time-based vs event-based invalidation |
| Lightweight telemetry sidecars | Observability tools (OpenTelemetry local exporters) | Informs T3 sidecar design: append-only JSONL vs structured snapshots |

**For each pattern:** describe the approach, note what qLine could learn, and explicitly state whether it's applicable or not.

Do NOT produce a broad feature comparison matrix. Only include patterns that directly affect a design decision in T2 or T3.

### 4.4 — Supported vs Unsupported Dependency Table

**Primary deliverable.** Classify every Claude Code surface qLine depends on:

| Surface | Classification | Evidence | qLine Features Affected | Risk if Surface Changes |
|---------|---------------|----------|------------------------|------------------------|
| stdin JSON `model` field | | | Model display module | |
| stdin JSON `session_id` | | | Session package resolution | |
| stdin JSON `conversation` | | | Context bar, overhead estimation | |
| Hook `Stop` event payload | | | Cache metrics capture | |
| Hook `PostToolUse` event payload | | | Obs write/bash/edit tracking | |
| Transcript JSONL format | | | Anchor derivation, cache tail read | |
| Transcript file location | | | `_read_transcript_tail()` path resolution | |
| Session ID stability on resume | | | Package reuse, stale state avoidance | |
| cache_creation_input_tokens API field | | | Cache health computation | |
| Context window max_tokens | | | Context bar denominator | |
| Plugin hooks.json schema | | | Hook registration | |
| `${CLAUDE_PLUGIN_ROOT}` expansion | | | Hook command resolution | |

**Classifications (per TX):**
- **Supported** — documented, stable API contract
- **Observed-stable** — not documented but consistent across tested versions
- **Fragile** — known to change or depends on undocumented timing
- **Speculative** — inferred, never validated

### 4.5 — Upstream Risk Register

For each fragile or speculative dependency, document the risk:

| ID | Surface | Classification | Risk Description | Likelihood | Impact | Mitigation Options |
|----|---------|---------------|-----------------|------------|--------|-------------------|
| UR-01 | | | | low/med/high | low/med/high | |

---

## Codebase Pointers

These are the qLine source locations that consume the external surfaces being audited:

| What | Where | Surfaces Consumed |
|------|-------|-------------------|
| Stdin parsing | `src/statusline.py` → `normalize()` | All stdin JSON fields |
| Transcript reading | `src/context_overhead.py` → `_read_transcript_tail()`, `_read_transcript_anchor()` | Transcript JSONL format, file location |
| Cache metrics extraction | `hooks/obs-stop-cache.py` | Stop event payload, cache API fields |
| Session resolution | `hooks/obs_utils.py` → `resolve_package_root()` | session_id stability, runtime map |
| Hook registration | `hooks/hooks.json` | hooks.json schema, `${CLAUDE_PLUGIN_ROOT}` |
| Plugin manifest | `.claude-plugin/plugin.json` | Plugin discovery mechanism |
| Context budget constants | `src/context_overhead.py` lines 48-52 | Context window sizes, reserve budgets |

---

## Acceptance Criteria

- [ ] Documentation audit table filled for all 12 surfaces with yes/no/partial and source references
- [ ] Public issue scan covers all 5 search areas with relevant issues documented
- [ ] Adjacent pattern comparison limited to 3 patterns with explicit applicability judgment
- [ ] Supported-vs-unsupported table classifies all surfaces identified in Task 4.1 and any additional discovered during the scan
- [ ] Upstream risk register populated for all fragile/speculative dependencies
- [ ] Every classification backed by evidence (doc link, issue number, or version comparison)
- [ ] No speculative claims presented as fact — uncertainty is explicit

---

## Risks

| Risk | Mitigation |
|------|------------|
| Official docs may be incomplete or outdated | Cross-reference with public issues and observed behavior; label gaps |
| Public issue tracker may not cover all regressions | Supplement with CC changelog if available; label coverage gaps |
| Adjacent pattern research could expand unboundedly | Strict limit to 3 patterns with documented relevance filter |

---

## Do Not Decide Here

- Whether to stop using fragile dependencies (that's T5)
- Whether to add compatibility shims for fragile surfaces (that's T5)
- Whether to request upstream changes from Anthropic (out of scope for this research tree)
