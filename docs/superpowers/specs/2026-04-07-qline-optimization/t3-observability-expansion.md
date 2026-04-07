# T3 — Observability Expansion

## Objective

Inventory every data source qLine currently reads or could read. Identify missing visibility that would materially improve debugging and session understanding. Propose additive schemas for new observability fields, sidecars, and events — all designed for backward compatibility.

## Non-Goals

- Implementing any new observability features (output is schema proposals only)
- Modifying metric accuracy (that's T1)
- Changing refresh strategy (that's T2)
- Adding external data sources (that's T4)

---

## Inputs

- T0: architecture map, runtime artifact map
- TX: additive change rules, hook event type registry, session package layout contract
- Live repo at `/Users/q/LAB/qLine`
- Active observability sessions for source inspection

---

## Tasks

### 3.1 — Current Source Inventory

Verified against codebase on 2026-04-07. Every source below confirmed by reading the actual reader function and tracing its call path through `main()`.

#### Primary Sources (read by statusline hot path)

| # | Source | Location | Reader Function | Code Location | Questions It Answers | Hot Path? |
|---|--------|----------|----------------|---------------|---------------------|-----------|
| 1 | Statusline stdin payload | Piped from Claude Code | `read_stdin_bounded()` | `statusline.py:401-426` | Current model, session_id, workspace/cwd, version, output_style, cost, duration, context_window (used_percentage, context_window_size, total_input/output_tokens, current_usage), added_dirs, worktree, agent_id, transcript_path | Yes — entry point, every invocation |
| 2 | Transcript JSONL | `~/.claude/projects/<hash>/<session_id>.jsonl` | `_read_transcript_tail()` (context_overhead.py:288), `_read_transcript_anchor()` (:394), `_read_transcript_anchor_with_read()` (:426) | Called via `_try_phase2_transcript()` (:473) from `inject_context_overhead()` (:716) | Cache create/read tokens per turn, first-turn anchor, cache hit rate, warm-restart detection, microcompact detection, context growth rate, turns-until-compact | Yes — Phase 2 overhead, every 30s |
| 3 | hook_events.jsonl | `<package>/metadata/hook_events.jsonl` | `_count_obs_events()` | `statusline.py:1832-1848` | Event counts by type: reads, writes, bash, failures, subagents, tasks, compactions, prompts | Yes — obs counters, every 30s |
| 4 | manifest.json (anchor) | `<package>/manifest.json` | `_read_manifest_anchor()` | `context_overhead.py:457-470` | Cached cache_anchor value for Phase 2 overhead | Yes — anchor lookup, once per session |
| 5 | manifest.json (health) | `<package>/manifest.json` | `_read_obs_health()` | `statusline.py:1866-1874` | Overall health status (healthy/degraded/incomplete) | Yes — health badge, every 30s |
| 6 | reads.jsonl | `<package>/custom/reads.jsonl` | `_count_rereads()` | `statusline.py:1851-1863` | Total file reads and reread counts for reread percentage | Yes — obs counters, every 30s |
| 7 | /tmp/qline-cache.json | `/tmp/qline-cache.json` (configurable via `QLINE_CACHE_PATH`) | `load_cache()` / `save_cache()` | `statusline.py:1301-1335` | Cached system metrics (git, cpu, mem, disk, agents, tmux), obs session data, overhead session cache, snapshot throttle state | Yes — cache layer for all modules, every invocation |
| 8 | Runtime session map | `~/.claude/observability/runtime/<sid>.json` | `resolve_package_root()` | `obs_utils.py:218-240` (imported by statusline.py:51) | Session ID to package_root path mapping | Yes — package resolution, once per session (cached) |
| 9 | qline.toml config | `~/.config/qline.toml` | `load_config()` | `statusline.py:304-317` | User preferences: module enables, thresholds, colors, glyphs, layout, overhead_source | Yes — theme/config, every invocation |
| 10 | Process/system stats | `/proc/stat`, `/proc/meminfo` (Linux), `sysctl`/`vm_stat` (macOS), `os.statvfs()`, `git` commands, `pgrep`, `tmux` commands | `collect_cpu()` (:1126), `collect_memory()` (:1214), `collect_disk()` (:1221), `collect_git()` (:1240), `collect_agents()` (:1270), `collect_tmux()` (:1281) | `statusline.py:1373` `collect_system_data()` orchestrator | CPU%, memory%, disk%, git branch/sha/dirty, Codex agent count, tmux sessions/panes | Yes — system modules, every invocation (skipped if QLINE_NO_COLLECT=1) |

#### Static Overhead Estimation Sources (read by context_overhead.py Phase 1)

| # | Source | Location | Reader Function | Code Location | Questions It Answers | Hot Path? |
|---|--------|----------|----------------|---------------|---------------------|-----------|
| 11 | CLAUDE.md files | `~/.claude/CLAUDE.md`, `.claude/CLAUDE.md`, `./CLAUDE.md` | `_estimate_static_overhead()` | `context_overhead.py:73-247` | File sizes for system overhead token estimation | Yes — Phase 1 fallback, cached 60s |
| 12 | MEMORY.md | `~/.claude/projects/<hash>/memory/MEMORY.md` | `_estimate_static_overhead()` | `context_overhead.py:99-123` | Memory index size for overhead estimation | Yes — Phase 1 fallback, cached 60s |
| 13 | MCP config files | `~/.mcp.json`, `~/.claude/.mcp.json`, `./.mcp.json` | `_estimate_static_overhead()` | `context_overhead.py:133-158` | MCP server count for tool overhead estimation | Yes — Phase 1 fallback, cached 60s |
| 14 | Claude settings (MCP) | `~/.claude/settings.json` | `_estimate_static_overhead()` | `context_overhead.py:149-157` | Legacy mcpServers count, enabledPlugins list | Yes — Phase 1 fallback, cached 60s |
| 15 | Plugin cache directory | `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` | `_estimate_static_overhead()` | `context_overhead.py:191-246` | Skill/agent/command counts from enabled plugins for overhead estimation | Yes — Phase 1 fallback, cached 60s |

#### Hook-Only Sources (not read by statusline)

| # | Source | Location | Writer | Reader | Questions It Answers |
|---|--------|----------|--------|--------|---------------------|
| 16 | Hook stdin payloads | Piped from Claude Code to each hook | Claude Code runtime | `read_hook_input()` (hook_utils.py:29) | Event-specific data: tool name, file paths, exit codes, task results, agent info |
| 17 | custom/.read_state.json | `<package>/custom/.read_state.json` | obs-pretool-read.py, obs-posttool-write.py, obs-posttool-edit.py | obs-pretool-read.py (for reread detection) | Per-file read count, last read/write seq |
| 18 | custom/cache_metrics.jsonl | `<package>/custom/cache_metrics.jsonl` | obs-stop-cache.py | obs-stop-cache.py (dedup via `_read_last_sidecar_entry`) | Per-turn cache forensics: cache_create, cache_read, model, compaction_count, 1h/5m tiers |
| 19 | custom/bash_commands.jsonl | `<package>/custom/bash_commands.jsonl` | obs-posttool-bash.py | Not currently read | Bash command details (hash, exit code, preview) |
| 20 | custom/write_diffs/*.patch | `<package>/custom/write_diffs/<seq>-<tool_use_id>.patch` | obs-posttool-write.py, obs-posttool-edit.py | Not currently read | Unified diff patches for each write/edit |
| 21 | artifact_index.jsonl | `<package>/metadata/artifact_index.jsonl` | obs_utils.py:register_artifact() | Not currently read | Artifact/patch registration records |
| 22 | errors.jsonl | `<package>/metadata/errors.jsonl` | obs_utils.py:record_error() | Not currently read | Structured error records (subsystem, severity, action) |
| 23 | .seq_counter | `<package>/metadata/.seq_counter` | obs_utils.py:next_seq() | obs_utils.py:next_seq() (hooks only) | Monotonic event ordering |
| 24 | session_inventory.json | `<package>/metadata/session_inventory.json` | obs-session-start.py:_scan_inventory() | Not currently read by statusline | CLAUDE.md paths/sizes, plugin list, hook counts by event, settings.json info |
| 25 | source_map.json | `<package>/source_map.json` | obs_utils.py:create_package() | Not currently read | Session metadata (cwd, transcript, source) |
| 26 | native/statusline/snapshots.jsonl | `<package>/native/statusline/snapshots.jsonl` | statusline.py:_try_obs_snapshot() | Not read back by statusline (analysis only) | Statusline state snapshots over time |
| 27 | native/transcripts/origin-path.txt | `<package>/native/transcripts/origin-path.txt` | obs-session-start.py | Not currently read | Original transcript file path |
| 28 | lifecycle-hook-faults.jsonl | `~/.claude/logs/lifecycle-hook-faults.jsonl` | hook_utils.py:log_hook_fault(), log_hook_diagnostic() | Not currently read | Hook crash records, diagnostic warnings |
| 29 | derived/session_summary.json | `<package>/derived/session_summary.json` | obs-session-end.py | Not currently read | Post-session summary (event counts, timing, status) |
| 30 | derived/overhead_report.json | `<package>/derived/overhead_report.json` | obs_utils.py:generate_overhead_report() | Not currently read | Full-session overhead analysis |
| 31 | ~/.claude/tasks/<session_id>/*.json | `~/.claude/tasks/<id>/*.json` | Claude Code runtime | precompact-preserve.py, session-end-summary.py | Open task list for compaction handoff |
| 32 | ~/.claude/plans/*.md | `~/.claude/plans/*.md` | User/Claude Code | precompact-preserve.py, session-end-summary.py | Active plan name for compaction handoff |

#### Spec Corrections

1. **`custom/writes.jsonl` does NOT exist.** The spec table listed it as a source, but no code writes to `custom/writes.jsonl`. Write tracking goes to: (a) `hook_events.jsonl` via `file.write.diff` events, and (b) `custom/write_diffs/*.patch` files. There is no `writes.jsonl` sidecar.

2. **`.read_state` location corrected.** The actual path is `custom/.read_state.json` (not `metadata/.read_state`). It is NOT read by the statusline — only by hooks (obs-pretool-read, obs-posttool-write, obs-posttool-edit). The statusline gets reread counts from `custom/reads.jsonl` instead via `_count_rereads()`.

3. **`cache_metrics.jsonl` is primarily read by obs-stop-cache.py itself** (for deduplication via `_read_last_sidecar_entry`), not by `context_overhead.py`. The overhead monitor reads the raw transcript JSONL directly, not the sidecar.

4. **Missing from spec: 15 additional sources identified.** Sources #11-15 (5 static overhead estimation inputs), #22 (errors.jsonl), #25-32 (8: source_map, snapshots, origin-path, fault ledger, derived outputs x2, tasks, plans) were not in the original 17-source table. Total: 17 original + 15 new = 32.

5. **`session_inventory.json` is NOT "used at session start" by the statusline.** It is written at session start by `obs-session-start.py` and never read by statusline.py.

---

### 3.2 — Missing Visibility Identification

Each gap verified against the codebase. Existing gaps confirmed, additional gaps discovered.

#### Original Gaps (MV-01 through MV-10) — Verified

| ID | Gap | Verified? | Impact | Justification | Current Workaround |
|----|-----|-----------|--------|---------------|-------------------|
| MV-01 | Per-hook latency and timeout counts | **Confirmed.** `run_fail_open()` (hook_utils.py:82-92) wraps `main_fn()` with no timing. No timing data recorded anywhere for hook execution. | **High** | 16 hooks fire on every event cycle. A single slow hook (e.g., obs-stop-cache reading 50KB transcript tail) invisibly adds 200-500ms. No way to detect degradation without external timing. | Manual `time` command wrapping or stderr inspection |
| MV-02 | Source freshness / last-updated timestamps | **Confirmed.** `_inject_obs_counters()` (statusline.py:1877-1928) refreshes on a 30s TTL via `last_count_ts`, but no per-source freshness is tracked or displayed. The user sees stale data without any age indicator. | **High** | After a 30s cache window, the displayed obs counts may be 30-60s old. During active sessions with compaction, the difference between 5s-old and 55s-old data matters for user trust. System metrics (git, cpu, mem, disk) have a 60s cache TTL but no staleness indicator either. | Check file mtime manually |
| MV-03 | Transcript parse failures and skip reasons | **Confirmed.** `_read_transcript_tail()` (context_overhead.py:288-391) has `except OSError: return None` and silently skips malformed JSON lines via bare `except (json.JSONDecodeError, ValueError): continue`. No failures are logged, counted, or surfaced. `_read_transcript_anchor()` (:394-423) has the same silent-skip pattern. | **Medium** | Transcript parsing is the most fragile data path — it depends on CC's undocumented JSONL format, which varies across PRELIM/FINAL entries, sidechain entries, and subagent responses. Silent failures hide accuracy issues (T1 found MF-06 phase2 anchor calibration drift — transcript parsing is the likely root cause). | None — failures are invisible |
| MV-04 | Statusline render latency and cache-hit stats | **Confirmed.** `main()` (statusline.py:2006-2029) calls `read_stdin_bounded()`, `normalize()`, `collect_system_data()`, `_inject_obs_counters()`, `inject_context_overhead()`, `render()`, and `_try_obs_snapshot()` with no timing instrumentation on any of them. The cache hit/miss ratio for `/tmp/qline-cache.json` is not tracked. | **Medium** | The statusline runs on every CC status event. If it exceeds ~100ms, it impacts CC's perceived responsiveness. Currently no way to measure its own overhead or detect performance regression. The cache layer silently falls through on miss with no counter. | None |
| MV-05 | Hook coverage gaps by event/tool type | **Confirmed.** `obs-session-start.py:_scan_inventory()` writes hook counts by event type to `session_inventory.json` (lines 73-83), but: (a) this is a simple count, not a coverage analysis; (b) it does not compare against hooks.json registrations; (c) it is not read by the statusline or any post-session analysis. | **Medium** | If a hook is removed from settings.json but left in hooks.json (or vice versa), events are silently dropped. T0 found 0 orphans currently, but this can drift. The one-time session_inventory scan could detect this if enhanced. | Compare hooks.json against settings.json manually (T0 did this) |
| MV-06 | Per-session data volume and artifact churn | **Confirmed.** No code measures the total size of a session package or counts artifacts. `_count_obs_events()` reads the entire hook_events.jsonl file on every 30s refresh — a linear scan that grows with session length. | **Low** | Long sessions (500+ events) with many patches create large packages. The linear scan in `_count_obs_events()` has no awareness of file size. Currently manageable but becomes a concern at scale. | Count files/lines manually |
| MV-07 | Schema version markers for package compatibility | **Confirmed.** `manifest.json` has no `schema_version` field. `create_package()` (obs_utils.py:129-212) writes a fixed structure. `_read_manifest_anchor()` and `_read_obs_health()` do `m.get()` calls that are sparse-safe, but there's no way to detect if a package was written by an older version with a different layout. | **Low** | Currently low impact because the schema has been stable. Becomes important when T3 proposals add new fields — old packages won't have them, and the code must handle that gracefully. Adding a version marker now prevents future compatibility confusion. | Assume compatibility |
| MV-08 | Compaction impact on overhead anchors | **Confirmed.** `obs-precompact.py` emits `compact.started` event and updates `manifest.compactions[]`, but does NOT signal that the overhead anchor needs re-calibration. `_try_phase2_transcript()` (context_overhead.py:473) uses `session_cache["turn_1_anchor"]` which is set once and never invalidated after compaction. The compaction grace period logic (lines 632-656) suppresses `cache_busting` for a few turns but does not re-anchor. | **Medium** | After compaction, the first-turn anchor is stale because compaction rewrites the context. The overhead bar continues showing the pre-compaction system overhead percentage, which overstates real overhead on the now-smaller context. The `compaction_suppress_until_turn` mechanism only suppresses busting alerts, not the stale anchor display. | None — silent staleness. Context growth rate (`context_growth_per_turn`) partially compensates by estimating new turns-until-compact. |
| MV-09 | Hook execution order and concurrency | **Confirmed.** Hooks are registered in `hooks.json` as flat arrays per event type. CC's hook runner invokes them sequentially in array order (verified by behavior), but this is undocumented and could change. No ordering metadata is recorded. | **Low** | Currently no functional issue — hooks are idempotent and append-only. If CC ever parallelizes hook execution, the seq counter (fcntl-locked) would still maintain ordering, but timestamp-based forensics could be misleading. | Assume sequential (matches current CC behavior) |
| MV-10 | Session resume/continue detection | **Confirmed.** `obs-session-start.py` detects reentry (lines 127-137) and emits `session.reentry` event, but the statusline does NOT read this signal. `_inject_obs_counters()` does not check for reentry events. `inject_context_overhead()` does not distinguish fresh sessions from resumed ones — it just checks if `overhead_ts` is stale. | **High** | Resumed sessions may have stale cached state from a prior invocation. The 30s TTL on obs cache and overhead cache means the first 30 seconds of a resumed session display old data. The warm-cache detection in `_try_phase2_transcript()` (lines 510-533) partially handles this at the transcript level, but the obs counters and health display are fully stale until the next 30s refresh. | Check `session.reentry` event count in hook_events.jsonl manually |

#### Additional Gaps Discovered

| ID | Gap | Impact | Justification | Current Workaround |
|----|-----|--------|---------------|-------------------|
| MV-11 | Hook fault/diagnostic ledger not surfaced | **Medium** | `hook_utils.py` writes faults and diagnostics to `~/.claude/logs/lifecycle-hook-faults.jsonl` (line 17). This ledger records every hook crash (with full traceback), timeout, and diagnostic message. It is never read by the statusline or any hook. A hook could be crashing on every invocation, and the user would have no indication except checking this file manually. | Read the JSONL file manually |
| MV-12 | errors.jsonl not surfaced to statusline | **Low** | `obs_utils.py:record_error()` writes structured errors with severity, subsystem, and action to `<package>/metadata/errors.jsonl`. These are never read by the statusline. The health subsystem (`update_health()`) partially covers this via degraded status, but the specific error details (what failed, when, how many times) are invisible. | Read errors.jsonl manually |
| MV-13 | Transcript path discovery failure invisible | **Medium** | `inject_context_overhead()` (context_overhead.py:764-779) scans `~/.claude/projects/` to find the transcript JSONL when the payload doesn't include `transcript_path`. If the scan fails (no matching file), Phase 2 overhead silently falls back to Phase 1 estimation. The user sees "estimated" source but has no signal that the transcript was simply not found (vs. not yet written). | None — appears as "estimated" without explanation |
| MV-14 | Static overhead estimation accuracy unknown at runtime | **Low** | `_estimate_static_overhead()` (context_overhead.py:73-247) computes a token estimate from file sizes, MCP server counts, and plugin stubs. The calibration ratio (measured vs estimated, lines 537-543) is computed but only stored in the session cache — never displayed or logged to any sidecar. The user cannot see whether the estimate was 80% accurate or 50% accurate. | Inspect the session cache in `/tmp/qline-cache.json` manually |
| MV-15 | Session package creation failure undetectable | **Medium** | If `obs-session-start.py` fails at Tier 0 (cannot create dirs/manifest), it prints to stderr and exits 0 (fail-open). The statusline will then silently operate without obs integration for the entire session — no error indicator, no degraded mode, no "obs unavailable" badge. `_inject_obs_counters()` simply returns early if `package_root is None`. | Check stderr output or notice missing obs modules in statusline |

---

### 3.3 — Proposed Schema Additions

For each high/medium impact gap, verified against codebase with implementation complexity estimates and backward compatibility analysis.

#### 3.3.1 — Hook Performance Sidecar

**For:** MV-01 (per-hook latency)

```
Location: <package>/metadata/hook_perf.jsonl
Writer: hook_utils.py (instrument run_fail_open())
Reader: statusline.py (new module or obs_health enhancement)

Schema per line:
{
  "seq": <int>,
  "ts": "<ISO8601>",
  "hook": "<hook_name>",
  "event": "<event_type>",
  "elapsed_ms": <float>,
  "timed_out": <bool>,
  "exit_code": <int>
}
```

**Verification findings:**

- **Writer location confirmed.** `run_fail_open()` at `hook_utils.py:82-92` is the single wrapper for all 16 hooks. Adding `time.monotonic()` before/after `main_fn()` is a 5-line change. The wrapper already catches Exception and calls `log_hook_fault()`, so adding timing is architecturally clean.
- **Package root availability:** Hooks already resolve `package_root` inside their `main()` functions, but `run_fail_open()` runs OUTSIDE `main()` — it wraps it. The timing data would need to be passed to a writer that knows the package root. Two approaches: (a) write to a fixed location (e.g., the fault ledger path), or (b) add a post-main callback that receives timing + package_root.
- **Reader location:** `_inject_obs_counters()` at `statusline.py:1877` already reads from the package root. Adding a `hook_perf.jsonl` scan here (tail last N entries, compute p50/p99 latency) would be a small addition.
- **Backward compatibility:** New file — old packages simply won't have it. Readers must tolerate `FileNotFoundError`.

**Implementation complexity:** Small. The core timing is trivial. The challenge is getting the package_root into the `run_fail_open()` scope — requires a minor refactor of the wrapper interface (e.g., passing a `package_root_fn` callback or using an env var set by the first hook in a batch).

**Alternative (simpler):** Write timing to the existing fault ledger (`~/.claude/logs/lifecycle-hook-faults.jsonl`) as `level: "perf"` records. This avoids the package_root problem entirely but loses per-session structure.

**Dependency classification:** Supported. Uses only qLine-owned hook infrastructure (`run_fail_open`, package dirs). No CC internals.

---

#### 3.3.2 — Source Freshness Manifest Keys

**For:** MV-02 (source freshness)

```
Location: manifest.json (additive keys)

New keys:
{
  "source_freshness": {
    "hook_events_last_seq": <int>,
    "hook_events_last_ts": "<ISO8601>",
    "cache_metrics_last_ts": "<ISO8601>",
    "transcript_last_read_ts": "<ISO8601>",
    "manifest_last_write_ts": "<ISO8601>"
  }
}
```

**Verification findings:**

- **Writer locations:**
  - `hook_events_last_seq/ts`: `append_event()` at `obs_utils.py:276-312` already computes seq and ts. Adding a manifest update here would add an flock cycle per event — potentially expensive. Better approach: update these keys in `_inject_obs_counters()` AFTER the scan, using the last entry's seq/ts.
  - `cache_metrics_last_ts`: Written by `obs-stop-cache.py` which already calls `update_manifest_if_absent_batch()`. Adding a `source_freshness` update is straightforward.
  - `transcript_last_read_ts`: Written by `inject_context_overhead()` at `context_overhead.py:716` which already updates session_cache. Could stamp this into manifest via `update_manifest()`.
  - `manifest_last_write_ts`: Self-referential — every manifest write updates this. Must be the last field written to avoid racing.

- **Reader location:** `_inject_obs_counters()` or a new `_inject_source_freshness()` in statusline.py. The freshness data would compute `now - last_ts` per source and inject into state for rendering (e.g., dim/warning colors for stale sources).

- **Backward compatibility:** Additive manifest keys. `manifest.get("source_freshness", {})` gracefully returns empty dict on old packages. Sparse-safe.

- **Concern:** Writing to manifest on every event creates additional flock contention. The manifest is already flock-protected, and multiple hooks write to it. Better to batch freshness updates at specific moments (session start, stop, periodic from statusline).

**Dependency classification:** Supported. Uses only qLine manifest keys and hook infrastructure.

**Implementation complexity:** Medium. The schema is simple, but the writer placement requires care to avoid adding flock overhead to the hot event path. Best approach: write freshness data to the session cache (already in `/tmp/qline-cache.json`), and optionally persist to manifest only at session end.

---

#### 3.3.3 — Parse Diagnostic Sidecar

**For:** MV-03 (transcript parse failures) + MV-04 (render latency)

```
Location: <package>/native/statusline/diagnostics.jsonl
Writer: statusline.py, context_overhead.py
Reader: statusline.py (obs_health module enhancement)

Schema per line:
{
  "ts": "<ISO8601>",
  "component": "transcript_tail" | "transcript_anchor" | "manifest" | "obs_counters" | "render",
  "outcome": "success" | "partial" | "skip" | "error",
  "elapsed_ms": <float>,
  "detail": "<optional string: skip reason, error message, or partial read info>",
  "cache_hit": <bool>  // for render: was /tmp/qline-cache.json used?
}
```

**Verification findings:**

- **Writer: context_overhead.py** — `_read_transcript_tail()` at line 288 has 3 failure modes: `OSError` on file open (line 313), JSON parse failure (line 329, silently skipped), and no usable turns found (line 361, returns None). Each would emit a diagnostic. `_read_transcript_anchor()` (:394) has the same 3 failure modes. Currently all failures return `None` with no trace.

- **Writer: statusline.py** — `main()` at line 2006 calls 6 major functions sequentially. Wrapping each with `time.monotonic()` and emitting diagnostics is straightforward. The `_inject_obs_counters()` function (line 1877) already loads/saves the cache — instrumenting its cache-hit path is a 2-line addition.

- **Writer location confirmed:** `native/statusline/` directory already exists (used for `snapshots.jsonl` at line 1978). Adding `diagnostics.jsonl` alongside it follows the existing pattern.

- **Reader placement:** The diagnostics file can be read by an enhanced `render_obs_health()` module (statusline.py) to show a warning indicator when parse failures exceed a threshold.

- **Backward compatibility:** New file — old packages won't have it. The `obs_health` module currently shows manifest health status; it would gain a secondary signal from diagnostics if available.

- **Size bounding:** The statusline runs on every CC status event (potentially many times per second during active output). At ~100 bytes per line, 1000 invocations = ~100KB. A rotation mechanism (keep last 500 lines) or write-only-on-failure approach is essential.

**Dependency classification:** Supported. Self-diagnostics for qLine's own render pipeline. No CC internals.

**Implementation complexity:** Medium. The timing instrumentation is trivial, but the concern is write overhead — the statusline is latency-sensitive, and adding a JSONL append to every invocation conflicts with the "never delay render for diagnostics" principle. Best approach: buffer diagnostics in the session cache and flush to the sidecar only on error/partial outcomes or every Nth invocation.

---

#### 3.3.4 — Package Schema Version

**For:** MV-07 (schema compatibility)

```
Location: manifest.json (additive key)

New key:
{
  "schema_version": "1.1.0"
}
```

**Verification findings:**

- **Writer location:** `create_package()` at `obs_utils.py:161-186` writes the initial manifest. Adding `"schema_version": "1.1.0"` is a single-line addition to the manifest dict.

- **Reader locations:**
  - `_read_manifest_anchor()` (context_overhead.py:457) — would check version and degrade if unknown major version.
  - `_read_obs_health()` (statusline.py:1866) — same.
  - All manifest readers in hooks use bare `json.load()` + `.get()` calls — already sparse-safe.

- **Backward compatibility:** Old manifests without `schema_version` are treated as `1.0.0` by readers (`m.get("schema_version", "1.0.0")`). Old readers encountering a manifest with `schema_version` will ignore the field (unknown keys are already tolerated). Fully backward-compatible.

- **Versioning policy:** Follows TX rules (section 2). Major = breaking layout change (would require manifest migration). Minor = additive fields (like all T3 proposals). Patch = fixes. Current schema is retroactively `1.0.0`.

**Dependency classification:** Supported. Versioning is internal to qLine manifest schema.

**Implementation complexity:** Trivial. One line added to `create_package()`. Reader checks are optional — the version is informational for debugging and future migration tooling.

---

#### 3.3.5 — Compaction Impact Signal

**For:** MV-08 (compaction staleness)

```
Location: hook_events.jsonl (new event type, following TX rules)

New event:
{
  "seq": <int>,
  "ts": "<ISO8601>",
  "event": "compact.anchor_invalidated",
  "session_id": "<sid>",
  "data": {
    "reason": "context_reset",
    "prior_anchor": <int>,
    "action": "re_anchor_on_next_stop"
  },
  "origin_type": "native_snapshot",
  "hook": "obs-precompact"
}
```

**Verification findings:**

- **Writer location:** `obs-precompact.py` at line 58 already calls `append_event()` with `compact.started`. Adding a second `append_event()` for `compact.anchor_invalidated` immediately after is a 10-line addition.

- **Reader location:** `_try_phase2_transcript()` at `context_overhead.py:473` would need to check for this event. Currently it uses `session_cache["turn_1_anchor"]` (set once, never invalidated). The invalidation signal would trigger `del session_cache["turn_1_anchor"]` on next overhead refresh, forcing re-anchoring from the next Stop event's transcript data.

- **Integration with existing compaction handling:** `_try_phase2_transcript()` already has compaction awareness (lines 632-656) via `obs_compactions` count and `compaction_suppress_until_turn`. The anchor invalidation signal would complement this — the suppression handles cache_busting alerts, while the invalidation forces a fresh anchor measurement.

- **Backward compatibility:** New event type in existing JSONL envelope. Follows the `{ seq, ts, event, session_id, data, origin_type, hook }` contract from TX section 1.4. Old readers that don't recognize `compact.anchor_invalidated` will skip it (they only match known event types). Old obs-precompact.py will not emit it — the anchor remains stale (current behavior, acceptable degradation).

- **Alternative considered:** Instead of a new event type, set a manifest flag (`"anchor_invalidated": true`). Rejected because: (a) the event ledger provides a timeline (when exactly was it invalidated), and (b) manifest flags need explicit clearing, which adds complexity.

**Dependency classification:** Observed-stable. Depends on `PreCompact` hook continuing to fire before compaction. The hook event itself is documented, but the precise compaction lifecycle timing is observed-stable.

**Implementation complexity:** Small. Writer is ~10 lines in obs-precompact.py. Reader requires ~15 lines in `_try_phase2_transcript()` to detect the event and clear the cached anchor. The event scan could piggyback on the existing `_count_obs_events()` call.

---

#### 3.3.6 — Hook Coverage Report

**For:** MV-05 (hook coverage gaps)

```
Location: <package>/metadata/session_inventory.json (additive section)

New section:
{
  "hook_coverage": {
    "registered_hooks": ["obs-session-start", "obs-stop-cache", ...],
    "registered_events": ["SessionStart", "Stop", "PostToolUse", ...],
    "settings_hooks_count": <int>,
    "orphaned_settings_entries": [...],
    "unregistered_hook_files": [...]
  }
}
```

**Verification findings:**

- **Writer location:** `obs-session-start.py:_scan_inventory()` at line 24 already reads `settings.json` hooks (lines 73-83) and writes `session_inventory.json`. The enhancement would add a coverage comparison section.

- **Data sources for coverage analysis:**
  1. `hooks/hooks.json` (via `${CLAUDE_PLUGIN_ROOT}/hooks/hooks.json`) — the plugin's own hook registry. Readable from disk at session start.
  2. `~/.claude/settings.json` hooks section — the runtime registration. Already read by `_scan_inventory()`.
  3. `hooks/*.py` files on disk — the actual hook implementations. Glob-scannable.

- **Comparison logic:** For each event type in hooks.json, verify a corresponding settings.json entry exists with a matching path. For each `.py` file in hooks/, verify it's either registered (in hooks.json + settings.json) or is a utility module. Report orphans and gaps.

- **Reader location:** Not intended for statusline hot path. This is a one-time diagnostic at session start, useful for:
  (a) Post-session analysis of coverage
  (b) A future `obs_health` enhancement that warns about coverage drift

- **Backward compatibility:** Additive section in existing `session_inventory.json`. Old readers that don't know about `hook_coverage` will ignore it. Old `obs-session-start.py` without this enhancement will not write the section — coverage analysis simply isn't available for old packages.

**Dependency classification:** Supported. Reads hooks.json (qLine-owned), settings.json (documented CC surface), and local hook files.

- **T0 findings:** T0 section 0.2 manually verified 0 orphans, 0 unregistered files across all 16 hooks. This proposal automates that check for every session.

**Implementation complexity:** Small-Medium. The comparison logic is ~40 lines of Python (read hooks.json, compare against settings.json hook entries, glob hooks/*.py, compute differences). The `_scan_inventory()` function already does half the work. The only complexity is that `CLAUDE_PLUGIN_ROOT` env var may not be set — needs fallback to detect plugin root from the script's own `__file__` path.

---

#### 3.3.7 — Session Resume Signal (NEW)

**For:** MV-10 (session resume/continue detection)

```
Location: Session cache in /tmp/qline-cache.json (statusline-side)
Writer: _inject_obs_counters() in statusline.py
Reader: inject_context_overhead() in context_overhead.py

Logic:
On each _inject_obs_counters() call:
  1. Read hook_events.jsonl count of "session.reentry" events
  2. If count > session_cache.get("last_known_reentry_count", 0):
     → Set session_cache["resume_detected"] = True
     → Clear stale overhead cache: del session_cache["overhead_ts"]
     → Clear stale anchor: del session_cache["turn_1_anchor"]
     → Update session_cache["last_known_reentry_count"]
```

**Verification findings:**

- **Event already exists.** `obs-session-start.py:129-137` already emits `session.reentry` events. The count is available via `_count_obs_events()` in the `ec` dict as `ec.get("session.reentry", 0)`.

- **Cache invalidation path:** `inject_context_overhead()` checks `session_cache.get("overhead_ts", 0)` at line 751. If we clear `overhead_ts` on resume detection, the next call will force a fresh overhead computation. Similarly, clearing `turn_1_anchor` forces re-anchoring.

- **Backward compatibility:** No new files or events — purely a logic change in how existing data is consumed. Old packages with no `session.reentry` events will report count 0, and the comparison `0 > 0` is False, so no action taken.

**Implementation complexity:** Trivial. ~10 lines added to `_inject_obs_counters()`. No new files, no new events, no schema changes. This is the highest-ROI gap fix because it uses existing data that's already being collected but not consumed.

**Dependency classification:** Fragile. Depends on `session.reentry` events continuing to be emitted by `obs-session-start.py` when called with an existing session_id. The hook fires on SessionStart (documented), but the reentry detection logic is qLine-internal, and the session_id reuse behavior on resume/continue is observed-stable (T4 classifies it as speculative).

---

#### 3.3.8 — Hook Fault Surfacing (NEW)

**For:** MV-11 (hook fault ledger not surfaced)

```
Location: /tmp/qline-cache.json (session cache, "_obs" namespace)
Writer: statusline.py (new _check_hook_faults() function)
Reader: render_obs_health() module in statusline.py

Logic:
Periodically (every 60s via cache TTL):
  1. Stat ~/.claude/logs/lifecycle-hook-faults.jsonl for mtime
  2. If mtime > last_known_mtime:
     → Read last 10 lines (tail scan, similar to _count_obs_events pattern)
     → Count entries with level="fault" in the last 5 minutes
     → If count > 0: set state["obs_hook_faults"] = count
  3. render_obs_health() shows warning indicator when faults > 0
```

**Verification findings:**

- **Fault ledger location:** `hook_utils.py:17` defines `_LEDGER_PATH = ~/.claude/logs/lifecycle-hook-faults.jsonl`. Records include `ts`, `hook`, `event`, `level` (fault/diagnostic/warning/info), `message`, `traceback`.

- **Reader placement:** `_inject_obs_counters()` already runs on a 30s TTL. Adding a fault check at 60s intervals (separate TTL) keeps the overhead minimal. The fault ledger is small (hooks rarely crash), so a tail scan of the last 2KB is sufficient.

- **Backward compatibility:** No new files. The fault ledger already exists. If it doesn't exist, `stat()` raises FileNotFoundError, handled by the usual try/except pattern.

**Implementation complexity:** Small. ~20 lines for the checker + 5 lines for render_obs_health enhancement.

**Dependency classification:** Supported. Reads qLine's own fault ledger at a documented path. No CC internals.

---

## Codebase Pointers

| What | Where | Key Lines |
|------|-------|-----------|
| Hook wrapper | `hooks/hook_utils.py` | `run_fail_open()` line 82 — instrument here for MV-01 |
| Obs counter scan | `src/statusline.py` | `_inject_obs_counters()` line 1877 — linear scan of hook_events.jsonl |
| Reread count scan | `src/statusline.py` | `_count_rereads()` line 1851 — linear scan of reads.jsonl |
| Health read | `src/statusline.py` | `_read_obs_health()` line 1866 — manifest health lookup |
| Transcript reading | `src/context_overhead.py` | `_read_transcript_tail()` line 288, `_read_transcript_anchor()` line 394 |
| Overhead injection | `src/context_overhead.py` | `inject_context_overhead()` line 716 — orchestrates Phase 1/2 |
| Phase 2 transcript | `src/context_overhead.py` | `_try_phase2_transcript()` line 473 — anchor, hit rate, growth |
| Static estimation | `src/context_overhead.py` | `_estimate_static_overhead()` line 73 — reads CLAUDE.md, MCP, plugins |
| Manifest read/write | `hooks/obs_utils.py` | `update_manifest()` line 379, `create_package()` line 129 |
| Package resolver | `hooks/obs_utils.py` | `resolve_package_root()` line 218 |
| Session inventory | `hooks/obs-session-start.py` | `_scan_inventory()` line 24 |
| Cache write | `hooks/obs-stop-cache.py` | Writes to custom/cache_metrics.jsonl line 240 |
| Precompact hook | `hooks/obs-precompact.py` | `compact.started` event line 58 |
| Fault ledger | `hooks/hook_utils.py` | `_LEDGER_PATH` line 17, `log_hook_fault()` line 62 |
| Obs snapshot | `src/statusline.py` | `_try_obs_snapshot()` line 1931 |
| Cache layer | `src/statusline.py` | `load_cache()` line 1301, `save_cache()` line 1315 |
| System collectors | `src/statusline.py` | `collect_system_data()` line 1373 (git, cpu, mem, disk, agents, tmux) |
| Precompact preserve | `hooks/precompact-preserve.py` | Reads `~/.claude/tasks/` line 52, `~/.claude/plans/` line 107 |
| Session end summary | `hooks/obs-session-end.py` | `generate_session_summary()` line 85, `generate_overhead_report()` line 222 |
| Main entrypoint | `src/statusline.py` | `main()` line 2006 — full data flow: read -> normalize -> collect -> inject -> render -> snapshot |

---

## Acceptance Criteria

- [x] Source inventory table complete — 32 data sources documented (10 hot-path, 5 static estimation, 17 hook/analysis-only)
- [x] Missing visibility table includes all identified gaps — 15 total (10 original MV-01 through MV-10 verified, 5 additional MV-11 through MV-15 discovered)
- [x] Schema proposals provided for all high and medium impact gaps — 8 proposals (3.3.1-3.3.8)
- [x] Every proposal follows TX additive change rules — no existing events/keys modified
- [x] Every proposal includes: location, writer, reader, schema, implementation notes
- [x] Backward compatibility addressed for each proposal — all sparse-safe
- [x] No proposal requires changes to existing event types or manifest keys
- [x] Proposals labeled with supported-vs-fragile classification where relevant

---

## Impact Summary

| Gap | Impact | Proposal | Complexity | ROI |
|-----|--------|----------|-----------|-----|
| MV-10 Session resume | High | 3.3.7 | Trivial | **Highest** — uses existing data, fixes real staleness bug |
| MV-01 Hook latency | High | 3.3.1 | Small | High — enables performance debugging |
| MV-02 Source freshness | High | 3.3.2 | Medium | Medium — useful but complexity concern |
| MV-08 Compaction anchor | Medium | 3.3.5 | Small | High — fixes known staleness path |
| MV-03+04 Parse diagnostics | Medium | 3.3.3 | Medium | Medium — enables self-diagnostics |
| MV-05 Hook coverage | Medium | 3.3.6 | Small-Medium | Medium — automates T0 manual check |
| MV-11 Fault surfacing | Medium | 3.3.8 | Small | High — surfaces crash data already collected |
| MV-07 Schema version | Low | 3.3.4 | Trivial | Low — future-proofing |
| MV-13 Transcript discovery | Medium | (no dedicated schema — addressed by 3.3.3 diagnostics) | — | — |
| MV-15 Package creation failure | Medium | (no dedicated schema — addressed by 3.3.8 fault surfacing) | — | — |

---

## Risks

| Risk | Mitigation |
|------|------------|
| Hook performance instrumentation adds latency to hooks | Timing overhead is ~1ms (datetime calls); write to fixed-path ledger avoids package resolution cost |
| Diagnostics sidecar grows unbounded | Write only on error/partial; cap at 500 lines via ring buffer |
| Too many new sidecars fragment the package layout | Only 1 new sidecar proposed (hook_perf.jsonl); all other data goes into existing files (manifest, session_inventory, session cache) |
| Manifest flock contention from freshness writes | Write freshness to session cache (/tmp/qline-cache.json), not manifest; persist to manifest only at session end |
| Session cache growth from multiple sessions | Session cache is already keyed by session_id within `_obs` namespace; add TTL-based eviction for sessions older than 24h |

---

## Do Not Decide Here

- Which proposals to implement (that's T5)
- Whether new sidecars should be read by the statusline hot path or only for post-session analysis (T2 informs this)
- Priority ordering of gaps (T5 ranks by impact across all tracks)
