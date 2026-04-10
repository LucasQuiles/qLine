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

**Executed 2026-04-07.**

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| `/Users/q/LAB/qLine` is a git repo | On `main` with `73da760` at spec authoring time | On branch `research/qline-optimization-2026-04-07`, HEAD `7e24e0e` (2 commits ahead of `73da760`: spec tree + gitignore) | OK — research branch as intended |
| `~/.claude/plugins/qline` symlink target | Points to `/Users/q/LAB/qLine` | Symlink -> `/Users/q/LAB/qLine` (confirmed) | OK |
| `/Users/q/qline` exists and is stale | On `experiment/apr04-*` branch, behind main | On `experiment/apr04-overhead-cache-sharpening`, HEAD `c306b22`, origin/main reports 0 behind (remote may not be set up) | Stale as expected |
| Uncommitted changes in canonical repo | Clean working tree | Clean — `git status --short` produces no output | OK |
| Worktree at `.worktrees/research` | Branch `research/execution` tracking same HEAD | Branch `research/execution`, HEAD `7e24e0e` (same as canonical), clean | OK |
| Deployed `~/.claude/statusline.py` | Matches repo source | Identical to `src/statusline.py` (zero diff) — standalone copy, NOT a symlink | OK |

**Note:** The `statusLine` entry in `settings.json` points to `/Users/q/.claude/statusline.py` (a direct copy), not through the plugin symlink. The install script copies the file; updates require running `update.sh` or manually copying.

### 0.2 — Plugin Installation Map

**Plugin manifest** (`.claude-plugin/plugin.json`):
- **Name:** `qline`
- **Version:** `1.0.0`
- **Description:** "Claude Code status line and session observability — styled terminal bar, tool recording, session tracking."
- **Author:** q

**hooks/hooks.json** — 10 event types, 16 hook commands:

| Hook File | Event Type | hooks.json | settings.json | File Exists | Executable | Timeout |
|-----------|-----------|------------|---------------|-------------|------------|---------|
| `obs-session-start.py` | SessionStart | Yes | Yes | Yes | Yes | 5s |
| `obs-pretool-read.py` | PreToolUse (Read) | Yes | Yes | Yes | Yes | 5s |
| `obs-posttool-write.py` | PostToolUse (Write) | Yes | Yes | Yes | Yes | 5s |
| `obs-posttool-bash.py` | PostToolUse (Bash) | Yes | Yes | Yes | Yes | 5s |
| `obs-posttool-edit.py` | PostToolUse (Edit\|MultiEdit) | Yes | Yes | Yes | Yes | 5s |
| `obs-prompt-submit.py` | UserPromptSubmit | Yes | Yes | Yes | Yes | 5s |
| `obs-stop-cache.py` | Stop | Yes | Yes | Yes | Yes | 2s |
| `obs-precompact.py` | PreCompact | Yes | Yes | Yes | Yes | 5s |
| `precompact-preserve.py` | PreCompact | Yes | Yes | Yes | Yes | 5s |
| `obs-subagent-stop.py` | SubagentStop | Yes | Yes | Yes | Yes | 5s |
| `subagent-stop-gate.py` | SubagentStop | Yes | Yes | Yes | Yes | 5s |
| `obs-session-end.py` | SessionEnd | Yes | Yes | Yes | Yes | 5s |
| `session-end-summary.py` | SessionEnd | Yes | Yes | Yes | Yes | 5s |
| `obs-task-completed.py` | TaskCompleted | Yes | Yes | Yes | Yes | 5s |
| `task-completed-gate.py` | TaskCompleted | Yes | Yes | Yes | Yes | 5s |
| `obs-posttool-failure.py` | PostToolUseFailure | Yes | Yes | Yes | Yes | 5s |

**Shared utility modules** (not hooks, imported by hooks):
- `hooks/hook_utils.py` (142 lines) — stdin reader, fail-open wrapper, fault logging
- `hooks/obs_utils.py` (608 lines) — package creation, event recording, manifest management

**Path consistency:** `hooks/hooks.json` uses `${CLAUDE_PLUGIN_ROOT}` variable paths; `settings.json` uses hardcoded `/Users/q/.claude/plugins/qline/hooks/` paths. Both resolve to the same files via the symlink.

**Orphan check:**
- No orphaned settings entries (every settings hook maps to a file on disk)
- No unregistered hook files (every `.py` file in `hooks/` is either registered or is a utility module)
- `hooks/__pycache__/` and `hooks/tests/` directories exist but are not hook registrations (expected)

### 0.3 — Architecture Map

**Source layout:**

| Component | Path | Lines | Purpose |
|-----------|------|-------|---------|
| Main statusline | `src/statusline.py` | 2037 | Stdin JSON reader, state normalizer, module registry, theme engine, renderer |
| Context overhead | `src/context_overhead.py` | 807 | System overhead estimation (Phase 1 static + Phase 2 transcript), cache health, anchor tracking, forensics |
| Hook utilities | `hooks/hook_utils.py` | 142 | Shared hook infrastructure: stdin reader, fail-open wrapper, fault logging |
| Session utilities | `hooks/obs_utils.py` | 608 | Package creation, event recording, manifest management, health subsystem updates |
| obs-session-start | `hooks/obs-session-start.py` | 200 | Session package initialization, runtime map creation |
| obs-pretool-read | `hooks/obs-pretool-read.py` | 153 | File read tracking and counting |
| obs-posttool-write | `hooks/obs-posttool-write.py` | 200 | File write tracking |
| obs-posttool-bash | `hooks/obs-posttool-bash.py` | 164 | Bash command tracking |
| obs-posttool-edit | `hooks/obs-posttool-edit.py` | 181 | Edit/MultiEdit tracking |
| obs-prompt-submit | `hooks/obs-prompt-submit.py` | 94 | User prompt submission recording |
| obs-stop-cache | `hooks/obs-stop-cache.py` | 270 | Cache metric extraction from transcript on Stop |
| obs-precompact | `hooks/obs-precompact.py` | 87 | Pre-compaction state capture |
| precompact-preserve | `hooks/precompact-preserve.py` | 135 | Context preservation before compaction |
| obs-subagent-stop | `hooks/obs-subagent-stop.py` | 112 | Subagent stop recording |
| subagent-stop-gate | `hooks/subagent-stop-gate.py` | 107 | Subagent stop gating logic |
| obs-session-end | `hooks/obs-session-end.py` | 230 | Session finalization |
| session-end-summary | `hooks/session-end-summary.py` | 128 | Session summary generation |
| obs-task-completed | `hooks/obs-task-completed.py` | 106 | Task completion recording |
| task-completed-gate | `hooks/task-completed-gate.py` | 99 | Task completion gating |
| obs-posttool-failure | `hooks/obs-posttool-failure.py` | 69 | Tool failure recording |
| Install script | `install.sh` | 230 | Plugin installation and settings registration |
| Uninstall script | `uninstall.sh` | 109 | Plugin removal |
| Update script | `update.sh` | 11 | Statusline copy update |
| Config example | `qline.example.toml` | 147 | User-facing configuration template |
| Test harness | `tests/test-statusline.sh` | 2448 | Shell-based test suite (235 assertions) |
| Test fixtures | `tests/fixtures/statusline/*.json` | 12 files | JSON payloads for test scenarios |
| **Total** | | **~8,558** | |

**Data flow diagram:**

```
Claude Code runtime
  |
  |-- Status event (stdin JSON) --> statusline.py --> stdout (ANSI status line)
  |                                    |
  |                                    +-- reads: /tmp/qline-cache.json (60s TTL)
  |                                    +-- reads: ~/.claude/qline.toml (user config)
  |                                    +-- reads: transcript_path (Phase 2 overhead)
  |                                    +-- reads: <package>/manifest.json (anchor, health)
  |                                    +-- writes: /tmp/qline-cache.json (system metrics cache)
  |                                    +-- writes: <package>/native/statusline/snapshots.jsonl (obs)
  |                                    |
  |                                    +-- imports: context_overhead.py
  |                                           |
  |                                           +-- Phase 1: static estimate from CLAUDE.md sizes
  |                                           +-- Phase 2: transcript-based anchor + cache metrics
  |
  +-- Hook events (stdin JSON) --> obs-*.py --> hook_utils.py + obs_utils.py
                                      |
                                      +-- writes: <package>/metadata/hook_events.jsonl
                                      +-- writes: <package>/metadata/.seq_counter
                                      +-- writes: <package>/metadata/.read_state
                                      +-- writes: <package>/custom/cache_metrics.jsonl
                                      +-- writes: <package>/manifest.json
                                      +-- writes: ~/.claude/observability/runtime/<sid>.json

Where <package> = ~/.claude/observability/sessions/<date>/<session_id>/
```

**Runtime artifact map:**

| Artifact | Path | Writer | Reader | TTL/Lifecycle |
|----------|------|--------|--------|---------------|
| System metrics cache | `/tmp/qline-cache.json` | statusline.py | statusline.py | 60s TTL |
| User config | `~/.claude/qline.toml` | User | statusline.py | Permanent |
| Session manifest | `<package>/manifest.json` | obs_utils.py, obs-stop-cache.py | statusline.py, context_overhead.py | Session lifetime |
| Hook events | `<package>/metadata/hook_events.jsonl` | obs-*.py | statusline.py (count scan) | Session lifetime |
| Seq counter | `<package>/metadata/.seq_counter` | obs_utils.py | obs_utils.py | Session lifetime |
| Read state | `<package>/metadata/.read_state` | obs-pretool-read.py | statusline.py | Session lifetime |
| Cache metrics | `<package>/custom/cache_metrics.jsonl` | obs-stop-cache.py | context_overhead.py | Session lifetime |
| Runtime map | `~/.claude/observability/runtime/<sid>.json` | obs-session-start.py | statusline.py | Session lifetime |
| Obs snapshots | `<package>/native/statusline/snapshots.jsonl` | statusline.py | (analysis) | Session lifetime |
| Deployed statusline | `~/.claude/statusline.py` | install.sh / update.sh | Claude Code settings | Until next update |

### 0.4 — Test Failure Taxonomy

**Execution environment:**
- Shell: `bash 3.2.57(1)-release (arm64-apple-darwin25)` (macOS default)
- Python: `python3` (system)
- macOS Darwin 25.2.0 (arm64)
- Run from worktree: `/Users/q/LAB/qLine/.worktrees/research`

**Results: 197/235 passed, 38 failed.**

#### Failure Classification Table

| # | Test | Category | Error (truncated) | Severity | Fix Category |
|---|------|----------|--------------------|----------|-------------|
| 1 | R-02a: model with glyph | Harness portability | `$'\U000f06a9'` not expanded by bash 3.2 (requires bash 4.2+ for `\U` 8-digit escapes) | Harness-only | Use printf or python to emit glyph |
| 2 | R-02b: dir with glyph | Harness portability | Same: `$'\U000f0770'` literal on bash 3.2 | Harness-only | Same fix as #1 |
| 3 | R-02f: duration with glyph | Harness portability | Same: `$'\U000f0954'` literal on bash 3.2 | Harness-only | Same fix as #1 |
| 4 | R-12a: input arrow | Fixture drift | Test expects `↑12.3k` but code renders `▲ 12.3k` (render_tokens is legacy stub; token_in uses `\u25b2`) | Cosmetic | Update test to match `▲` glyph in pill |
| 5 | R-12b: output arrow | Fixture drift | Test expects `↓4.1k` but code renders `▼ 4.1k` (same root cause as #4) | Cosmetic | Update test to match `▼` glyph in pill |
| 6 | R-13: single line output | Harness portability | macOS `wc -l` returns `       1` (padded), `assert_single_line` compares to `"1"` | Harness-only | Strip whitespace from `wc -l` output |
| 7 | CF-03a: overridden model color | Harness portability | macOS `mktemp` lacks `--suffix=.toml` (GNU extension); tempfile creation fails, downstream test gets empty input | Harness-only | Use `mktemp /tmp/qline-test-XXXX.toml` pattern |
| 8 | CF-04a: overridden width | Harness portability | Same `mktemp --suffix` failure | Harness-only | Same fix as #7 |
| 9 | CF-04b: overridden warn | Harness portability | Same `mktemp --suffix` failure | Harness-only | Same fix as #7 |
| 10 | CF-04c: overridden critical | Harness portability | Same `mktemp --suffix` failure | Harness-only | Same fix as #7 |
| 11 | C-01g: duration | Fixture drift | Test expects `45s` but default duration format is `"hm"` which renders `0h 00m` for 45000ms | Cosmetic | Update fixture or test expectation |
| 12 | C-09b: input tokens | Fixture drift | Test expects `↑12.3k` but code renders `▲` in pill format (same as #4) | Cosmetic | Update test assertion |
| 13 | C-09c: output tokens | Fixture drift | Test expects `↓4.1k` but code renders `▼` in pill format (same as #5) | Cosmetic | Update test assertion |
| 14 | C-10b: bar present | Fixture drift | Test expects `15%` in output; `used_percentage` field in fixture may not map to `context_used/context_total` ratio used by bar renderer | Cosmetic | Update fixture or assertion |
| 15 | C-10c: input tokens | Fixture drift | Test expects `↑281k` — same arrow glyph mismatch as #4 | Cosmetic | Update test assertion |
| 16 | C-10d: output tokens | Fixture drift | Test expects `↓141k` — same arrow glyph mismatch as #5 | Cosmetic | Update test assertion |
| 17 | L-01: no newline when line2 empty | Rendering regression | Expected 1 line, got 2. `render()` emits a trailing newline or second line even when line2 modules all return None | Blocks experiment | Investigate render() output assembly |
| 18 | L-02: force single line | Harness portability | macOS `wc -l` padding: got `       1` instead of `"1"` (same as #6) | Harness-only | Strip whitespace from `wc -l` output |
| 19 | L-11b: marker char | Harness portability | `$'\u229b'` not expanded by bash 3.2 (bash 3.2 does not support `\u` escapes either) | Harness-only | Use printf or python to emit char |
| 20 | STALE-03: stale git has dim | Fixture drift | Test calls `render_dir()` with `git_stale=True` and expects dim output, but `render_dir` does not handle `git_stale` — that is `render_git`'s domain | Cosmetic | Fix test to call `render_git` instead |
| 21 | T-obs-1: snapshot appended | Harness portability | macOS `wc -l` returns `       1`, assert compares to `"1"` | Harness-only | Strip whitespace |
| 22 | T-obs-3: throttle skips duplicate | Harness portability | Same `wc -l` padding issue | Harness-only | Strip whitespace |
| 23 | T-obs-4: meaningful change bypasses throttle | Harness portability | Same `wc -l` padding issue | Harness-only | Strip whitespace |
| 24 | T-obs-6: no snapshot without session_id | Harness portability | Same `wc -l` padding issue (comparing `       0` to `"0"`) | Harness-only | Strip whitespace |
| 25 | compound critical+bust | Rendering regression | Test expects `%!\U000f04bf` in bar suffix but actual output shows `%!` followed by bar content without the lightning bolt glyph at expected position | Blocks experiment | Investigate cache-busting suffix rendering in `render_context_bar` |
| 26 | compound warn+bust | Rendering regression | Same: busting suffix format changed from expected pattern | Blocks experiment | Same code path as #25 |
| 27 | compound normal+bust | Rendering regression | Same: busting suffix format changed from expected pattern | Blocks experiment | Same code path as #25 |
| 28 | spike below notable | Logic defect | `AssertionError` with no detail — `render_cache_delta` returns `None` (legacy stub) but test expects functional behavior | Blocks experiment | `render_cache_delta` is a legacy stub returning None; test expects live function |
| 29 | spike at notable | Logic defect | `TypeError: argument of type 'NoneType' is not iterable` — `render_cache_delta` returns None, test does `in result` | Blocks experiment | Same root cause as #28 |
| 30 | spike at spike | Logic defect | Same TypeError from None return | Blocks experiment | Same root cause as #28 |
| 31 | sys_overhead module | Logic defect | `TypeError: argument of type 'NoneType' is not iterable` — `render_sys_overhead` is legacy stub returning None, test expects live function | Blocks experiment | `render_sys_overhead` stubbed; functionality moved to `render_sys_overhead_pill` |
| 32 | phase2 anchor | Logic defect | `AssertionError: got 0.7728689669998925` — anchor calibration ratio drifts outside expected tolerance (test expects ratio near 1.0) | Blocks experiment | Review `_try_phase2_transcript` calibration logic in `context_overhead.py` |
| 33 | cache busting not degraded | Rendering regression | Test expects `[warning_glyph]` in bar when busting + degraded, but busting indicator format changed | Blocks experiment | Investigate cache-busting indicator rendering |
| 34 | busting critical color | Rendering regression | Test expects darkened critical color for sys segment; actual ANSI codes differ from expected pattern | Cosmetic | Color constant mismatch in test assertion |
| 35 | config thresholds | Logic defect | Cache hit rate computes as 0.992 (healthy) when test expects degraded at 60% with `warn=0.8`. The `cache_degraded` flag is `False` despite transcript setup targeting degradation | Blocks experiment | Review cache health threshold logic in `context_overhead.py` |
| 36 | per-segment coloring | Rendering regression | Test expects "darkened healthy" color for sys segment but actual ANSI codes use a different darkening formula | Cosmetic | Color constant mismatch in test assertion |
| 37 | forensics report | Path assumption | `from obs_utils import generate_overhead_report` fails — `run_py` adds `src/` to sys.path but `obs_utils` lives in `hooks/` | Harness-only | Add `hooks/` to sys.path in test |
| 38 | hook integration | Path assumption | Test hardcodes `~/.claude/hooks/obs-stop-cache.py` (pre-plugin path); file is now at `~/.claude/plugins/qline/hooks/obs-stop-cache.py` | Harness-only | Update path to plugin location |

#### Summary by Category

| Category | Count | Tests |
|----------|-------|-------|
| Harness portability | 14 | #1-3, 6-10, 18-19, 21-24 (bash 3.2 + macOS wc/mktemp) |
| Fixture drift | 9 | #4-5, 11-16, 20 (glyph changes, format changes, wrong function) |
| Rendering regression | 7 | #17, 25-27, 33-34, 36 (layout newline, cache-busting suffix, color formulas) |
| Logic defect | 6 | #28-32, 35 (legacy stubs, calibration drift, threshold logic) |
| Path assumption | 2 | #37-38 (sys.path, hardcoded hook location) |

### 0.5 — Must-Fix List

Only **logic defect** or **rendering regression** with severity **blocks experiment**:

| ID | Failure | Description | Affected Code Path | Fix Scope |
|----|---------|-------------|-------------------|-----------|
| MF-01 | L-01 (#17) | `render()` emits 2 lines when all line2 modules return None; downstream tests and status bar display assume single-line output | `statusline.py:render()` output assembly | Function-level |
| MF-02 | compound *+bust (#25-27) | Cache-busting suffix `%!\U000f04bf` not present in rendered bar output; tests for compound cache-busting + severity suffixes all fail | `statusline.py:render_context_bar()` suffix logic | Function-level |
| MF-03 | cache busting not degraded (#33) | Busting indicator format does not match test expectations; may indicate busting detection or indicator rendering changed | `statusline.py:render_context_bar()` busting indicator | Function-level |
| MF-04 | spike/cache_delta (#28-30) | `render_cache_delta` is a legacy stub returning None; tests expect live rendering of cache write spikes | `statusline.py:render_cache_delta()` — stub needs redirect to new module or tests need update | Function-level (test update if functionality moved) |
| MF-05 | sys_overhead (#31) | `render_sys_overhead` is a legacy stub returning None; tests expect live rendering | `statusline.py:render_sys_overhead()` — stub needs redirect or tests need update to call `render_sys_overhead_pill` | Function-level (test update) |
| MF-06 | phase2 anchor (#32) | Phase 2 anchor calibration ratio is 0.77 instead of near 1.0; indicates calibration formula drift in overhead estimation | `context_overhead.py:_try_phase2_transcript()` | Function-level — calibration constant or formula |
| MF-07 | config thresholds (#35) | Cache health threshold config not applied correctly; transcript yields 99.2% hit rate (healthy) when test designs for degraded state at 60% with warn=0.8 | `context_overhead.py` cache health classification | Function-level — threshold application logic |

**Note on MF-04 and MF-05:** These may be test-only fixes if the functionality genuinely moved to `render_cache_pill`/`render_sys_overhead_pill`. The tests are calling legacy stubs that were intentionally retired. Investigation during T1 will determine whether the tests should be updated to call the new functions, or whether the stubs should delegate.

**Total must-fix items: 7** (5 unique code paths, 2 potentially test-only updates).

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
| Deployed statusline | `~/.claude/statusline.py` |

---

## Acceptance Criteria

- [x] Repo state verification table completed — all checks documented
- [x] Plugin installation map table produced — every hook accounted for (16 hooks, 2 utils, 0 orphans)
- [x] Architecture map produced — data flow and runtime artifacts documented
- [x] Test harness run on live repo — full output captured (197/235 pass, 38 fail)
- [x] Every test failure classified into exactly one category (14 harness, 9 fixture, 7 rendering, 6 logic, 2 path)
- [x] Must-fix list bounded — 7 items, all blocking, no open-ended items
- [x] All deliverables use evidence format

---

## Risks

| Risk | Mitigation |
|------|------------|
| Test harness requires GNU tools not on macOS | Classified as harness portability — 16 of 38 failures are this category (bash 3.2 `\U` escapes, macOS `wc -l` padding, macOS `mktemp` no `--suffix`) |
| Active session writes to observability dirs during test run | Tests run with `QLINE_NO_COLLECT=1` and isolated temp dirs |
| Settings.json has hooks from other plugins mixed in | Filtered to qline-related entries only in 0.2 |
| Legacy stubs mask moved functionality | MF-04 and MF-05 need investigation in T1 to determine if test or code needs updating |

---

## Do Not Decide Here

- Whether any test failure warrants a code change (that's a Phase 1 decision after T0 is reviewed)
- Whether the architecture should change (that's T1-T4 territory)
- Whether the stale `/Users/q/qline` clone should be synced (explicit user decision)
