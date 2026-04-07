# T0 — Baseline & Repo Truth

## Objective

Establish the single source of truth for qLine's current state: repo layout, plugin installation shape, active configuration, architecture map, and test health. Produce a must-fix list that gates all downstream optimization work.

## Non-Goals

- Fixing test failures (only classifying them)
- Proposing optimizations or new features
- Modifying any source code
- Auditing metric accuracy (that's T1)

---

## Inputs

- Live repo at `/Users/q/LAB/qLine`
- Active plugin symlink at `~/.claude/plugins/qline`
- Claude settings at `~/.claude/settings.json`
- Observability sessions at `~/.claude/observability/`
- Contract definitions from `tx-data-contracts.md`

---

## Tasks

### 0.1 — Repo State Verification

Confirm the canonical repo and stale clone status:

| Check | Expected | Action if wrong |
|-------|----------|-----------------|
| `/Users/q/LAB/qLine` is a git repo on `main` | Expected `73da760` at spec authoring time; record actual HEAD regardless; flag if on a non-main branch | Record actual HEAD |
| `~/.claude/plugins/qline` symlink points to `/Users/q/LAB/qLine` | Yes | Record actual target |
| `/Users/q/qline` exists and is stale | On `experiment/apr04-*` branch, behind main | Note divergence, do not modify |
| No uncommitted changes in canonical repo | Clean working tree | Record any dirty state |

### 0.2 — Plugin Installation Map

Document the complete plugin installation shape:

**Plugin manifest:**
- Read `.claude-plugin/plugin.json` — record name, version, description
- Verify `hooks/hooks.json` entries match actual hook files on disk

**Settings registration:**
- Read `~/.claude/settings.json`
- List every hook command registered for qline
- Verify each command path resolves to an executable file
- Check for orphaned settings entries (hook in settings but file missing) or unregistered hooks (file exists but not in settings)

**Deliverable:** Plugin installation map table with columns: hook name, event type, settings path, file exists, executable, timeout.

### 0.3 — Architecture Map

Produce a canonical architecture map covering:

**Source layout:**

| Component | Path | Lines | Purpose |
|-----------|------|-------|---------|
| Main statusline | `src/statusline.py` | ~2037 | Stdin reader, normalizer, module registry, renderer |
| Context overhead | `src/context_overhead.py` | ~387 | System overhead estimation, cache metrics, anchor tracking |
| Hook utilities | `hooks/hook_utils.py` | ~142 | Shared hook infrastructure (stdin, fail-open, fault logging) |
| Session utilities | `hooks/obs_utils.py` | ~608 | Package creation, event recording, manifest management |
| Hooks (13) | `hooks/obs-*.py` + gates | varies | Lifecycle event recording |
| Test harness | `tests/test-statusline.sh` | ~235+ | Shell-based test suite |
| Test fixtures | `tests/fixtures/statusline/*.json` | 12 files | JSON payloads for test scenarios |

**Data flow diagram (text):**

```
Claude Code
  ├── stdin JSON ──→ statusline.py ──→ stdout (ANSI line)
  │                      ↓
  │                 context_overhead.py
  │                      ↓
  │                 /tmp/qline-cache.json (60s TTL)
  │                      ↓
  │                 ~/.claude/observability/sessions/<date>/<sid>/
  │
  └── hook events ──→ obs-*.py ──→ hook_events.jsonl
                          ↓
                     custom/*.jsonl (bash, cache, reads, writes)
                          ↓
                     manifest.json (health, anchors)
```

**Runtime artifact map:**

| Artifact | Path | Writer | Reader | TTL/Lifecycle |
|----------|------|--------|--------|---------------|
| Metrics cache | `/tmp/qline-cache.json` | statusline.py | statusline.py | 60s TTL |
| Session manifest | `<package>/manifest.json` | obs_utils.py | statusline.py, context_overhead.py | Session lifetime |
| Hook events | `<package>/metadata/hook_events.jsonl` | obs-*.py | statusline.py (count scan) | Session lifetime |
| Seq counter | `<package>/metadata/.seq_counter` | obs_utils.py | obs_utils.py | Session lifetime |
| Runtime map | `~/.claude/observability/runtime/<sid>.json` | obs-session-start.py | statusline.py | Session lifetime |
| Read state | `<package>/metadata/.read_state` | obs-pretool-read.py | statusline.py | Session lifetime |
| Cache metrics | `<package>/custom/cache_metrics.jsonl` | obs-stop-cache.py | context_overhead.py | Session lifetime |

### 0.4 — Test Failure Taxonomy

Run `tests/test-statusline.sh` on the live repo and classify every failure:

**Execution:**
```bash
cd /Users/q/LAB/qLine
bash tests/test-statusline.sh 2>&1
```

**Classification categories:**

| Category | Definition | Example |
|----------|------------|---------|
| **Harness portability** | Test infra assumes bash features, paths, or utilities not present on this macOS | `seq` vs `jot`, GNU vs BSD `date` |
| **Fixture drift** | Test fixture JSON doesn't match current statusline field expectations | Missing field added since fixture creation |
| **Rendering regression** | Expected output string doesn't match actual render | Layout, spacing, glyph, or color change |
| **Logic defect** | Metric computation produces wrong value | Cache hit-rate formula error |
| **Path assumption** | Test hardcodes a path that differs on this machine | `/usr/bin/python3` vs `/opt/homebrew/bin/python3` |

**Deliverable:** Test failure table with columns: test name, category, error output (truncated), severity (blocks experiment / cosmetic / harness-only), suggested fix category (harness, fixture update, code fix).

### 0.5 — Must-Fix List

Distill T0.4 into a bounded must-fix list. Only failures classified as **logic defect** or **rendering regression** with severity **blocks experiment** qualify. Harness portability and fixture drift are noted but do not gate Phase 1.

**Deliverable:** Numbered list with: failure ID, description, affected code path, estimated fix scope (1-liner, function-level, module-level).

---

## Codebase Pointers

| What | Where |
|------|-------|
| Plugin manifest | `/Users/q/LAB/qLine/.claude-plugin/plugin.json` |
| Hook registration | `/Users/q/LAB/qLine/hooks/hooks.json` |
| Main statusline | `/Users/q/LAB/qLine/src/statusline.py` |
| Context overhead | `/Users/q/LAB/qLine/src/context_overhead.py` |
| Hook utilities | `/Users/q/LAB/qLine/hooks/hook_utils.py` |
| Session utilities | `/Users/q/LAB/qLine/hooks/obs_utils.py` |
| Test harness | `/Users/q/LAB/qLine/tests/test-statusline.sh` |
| Test fixtures | `/Users/q/LAB/qLine/tests/fixtures/statusline/` |
| Claude settings | `~/.claude/settings.json` |
| Plugin symlink | `~/.claude/plugins/qline` |
| Observability root | `~/.claude/observability/` |
| Runtime maps | `~/.claude/observability/runtime/` |

---

## Acceptance Criteria

- [ ] Repo state verification table completed — all checks documented
- [ ] Plugin installation map table produced — every hook accounted for
- [ ] Architecture map produced — data flow and runtime artifacts documented
- [ ] Test harness run on live repo — full output captured
- [ ] Every test failure classified into exactly one category
- [ ] Must-fix list bounded — only blocking defects, no open-ended items
- [ ] All deliverables use evidence format from TX

---

## Risks

| Risk | Mitigation |
|------|------------|
| Test harness requires GNU tools not on macOS | Classify as harness portability, not a code defect |
| Active session writes to observability dirs during test run | Run tests with `QLINE_NO_COLLECT=1`, use snapshot of session data |
| Settings.json has hooks from other plugins mixed in | Filter to qline-related entries only |

---

## Do Not Decide Here

- Whether any test failure warrants a code change (that's a Phase 1 decision after T0 is reviewed)
- Whether the architecture should change (that's T1-T4 territory)
- Whether the stale `/Users/q/qline` clone should be synced (explicit user decision)
