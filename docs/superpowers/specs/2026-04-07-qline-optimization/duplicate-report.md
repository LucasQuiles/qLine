# qLine Duplicate-Intent Function Report

## Summary
- Total functions extracted: 116
- Categories with 3+ functions: 11
- Duplicate groups found: 14 (5 high, 5 medium, 4 low confidence)

## Function Catalog

### src/statusline.py (2049 lines, 46 functions)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 304 | `load_config` | config | Load TOML config with per-section merge over defaults |
| 322 | `_parse_hex` | string-utils | Parse #RRGGBB hex color to (R,G,B) tuple |
| 332 | `style` | rendering | Wrap text in ANSI truecolor escape sequences |
| 356 | `style_dim` | rendering | Apply ANSI dim attribute to text |
| 366 | `_darken_hex` | string-utils | Darken a hex color by a factor |
| 377 | `_visible_len` | string-utils | Return visible character count stripping ANSI escapes |
| 384 | `_run_cmd` | file-ops | Run a subprocess with timeout, return stdout or None |
| 401 | `read_stdin_bounded` | file-ops | Single-read bounded binary stdin reader for statusline |
| 431 | `normalize` | data-transform | Create normalized internal state from raw CC payload |
| 553 | `_sanitize_fragment` | string-utils | Remove newlines and control chars from text fragment |
| 558 | `_format_cost` | string-utils | Format cost USD with appropriate decimal precision |
| 565 | `_format_duration` | string-utils | Format duration_ms in human-readable form |
| 599 | `_abbreviate_count` | string-utils | Abbreviate token counts (1234 -> 1.2k) |
| 610 | `_pill` | rendering | Wrap text as a styled pill with bg and rounded caps |
| 632 | `format_tokens` | rendering | Format token counts as up/down arrow pills |
| 639 | `render_bar` | rendering | Render context progress bar with threshold coloring |
| 670 | `render_model` | rendering | Render model name module |
| 680 | `render_dir` | rendering | Render directory pill |
| 698 | `render_context_bar` | rendering | Render context health bar with severity |
| 954 | `render_tokens` | rendering | Legacy stub (unused) |
| 959 | `render_sys_overhead` | rendering | Legacy stub (unused) |
| 964 | `render_cache_delta` | rendering | Legacy stub (unused) |
| 969 | `render_sys_overhead_pill` | rendering | Render system overhead pill |
| 982 | `render_token_in` | rendering | Render input token pill |
| 992 | `render_token_out` | rendering | Render output token pill |
| 1002 | `render_cache_pill` | rendering | Render combined cache pill |
| 1026 | `render_cache_rate` | rendering | Render cache hit rate pill |
| 1037 | `render_turns_pill` | rendering | Render turns-until-compact pill |
| 1047 | `render_cost` | rendering | Render cost module with $/hr rate |
| 1073 | `render_duration` | rendering | Render duration module |
| 1086 | `_collect_cpu_proc` | metrics | Linux CPU load from /proc/loadavg |
| 1104 | `_collect_cpu_sysctl` | metrics | macOS CPU load from sysctl |
| 1126 | `collect_cpu` | metrics | Collect CPU load (platform dispatch) |
| 1135 | `_collect_memory_proc` | metrics | Linux memory from /proc/meminfo |
| 1172 | `_collect_memory_sysctl` | metrics | macOS memory from vm_stat |
| 1214 | `collect_memory` | metrics | Collect memory usage (platform dispatch) |
| 1221 | `collect_disk` | metrics | Collect disk usage percentage |
| 1240 | `collect_git` | metrics | Collect git branch, SHA, dirty status |
| 1270 | `collect_agents` | metrics | Count running Codex instances |
| 1281 | `collect_tmux` | metrics | Collect tmux session/pane counts |
| 1301 | `load_cache` | cache | Load statusline cache file |
| 1315 | `save_cache` | cache | Atomically save statusline cache |
| 1348 | `_cache_module` | cache | Save module data to cache dict |
| 1356 | `_apply_cached` | cache | Apply cached data if fresh enough |
| 1373 | `collect_system_data` | metrics | Run all enabled system collectors |
| 1415 | `_render_system_metric` | rendering | Shared renderer for cpu/memory/disk |
| 1454 | `render_git` | rendering | Render git branch@sha |
| 1474-1486 | `render_cpu/memory/disk` | rendering | Delegates to _render_system_metric |
| 1489 | `render_agents` | rendering | Render active agents count |
| 1509 | `render_tmux` | rendering | Render tmux session info |
| 1527-1636 | `render_obs_*` (10 fns) | rendering | Render obs counter modules |
| 1681 | `render_line` | rendering | Render a single line from module names |
| 1711 | `_render_wrapped` | rendering | Render modules into auto-wrapped rows |
| 1767 | `render` | rendering | Top-level render from state + layout |
| 1824 | `_compute_context_pct` | metrics | Compute context usage percentage |
| 1832 | `_count_obs_events` | file-ops | Fast line-scan of hook_events.jsonl for counts |
| 1851 | `_count_rereads` | file-ops | Count total reads and rereads from reads.jsonl |
| 1866 | `_read_obs_health` | file-ops | Read overall health from manifest |
| 1877 | `_inject_obs_counters` | data-transform | Inject obs event counters into state |
| 1943 | `_try_obs_snapshot` | logging/telemetry | Append status snapshot to session package |
| 2018 | `main` | other | Status-line entrypoint |

### src/context_overhead.py (811 lines, 10 functions)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 73 | `_estimate_static_overhead` | metrics | Estimate system token overhead from local sources |
| 255 | `_extract_usage` | data-transform | Extract usage dict and requestId from transcript entry |
| 288 | `_read_transcript_tail` | file-ops | Read trailing turns from session transcript JSONL |
| 394 | `_read_transcript_anchor` | file-ops | Read first-turn cache_creation from transcript start |
| 426 | `_read_transcript_anchor_with_read` | file-ops | Read first-turn system overhead from cache_read on warm restart |
| 457 | `_read_manifest_anchor` | file-ops | Read cache_anchor from manifest |
| 473 | `_try_phase2_transcript` | metrics | Attempt Phase 2 measured overhead from transcript |
| 670 | `compute_context_thresholds` | metrics | Compute exact CC context thresholds |
| 699 | `_apply_overhead_from_cache` | cache | Copy overhead fields from session cache to state |
| 719 | `inject_context_overhead` | metrics | Inject overhead monitor data into state |

### hooks/hook_utils.py (143 lines, 8 functions)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 22 | `read_stdin_with_timeout` | file-ops | Read stdin with select timeout |
| 29 | `read_hook_input` | file-ops | Read and parse hook JSON input from stdin |
| 47 | `_write_ledger_record` | error-handling | Atomic JSONL append to the fault ledger |
| 62 | `log_hook_fault` | error-handling | Write a fault-level record with traceback |
| 82 | `run_fail_open` | error-handling | Run hook main with crash resistance |
| 99 | `sanitize_task_list_id` | string-utils | Mirror Claude's task-list directory sanitization |
| 107 | `log_hook_diagnostic` | logging/telemetry | Write a diagnostic or warning record |
| 127 | `is_strict` | validation | Check if strict-mode env flag is set |
| 133 | `block_stop` | other | Print stop-block decision and exit |

### hooks/obs_utils.py (609 lines, 18 functions)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 63 | `_now_iso` | string-utils | Return UTC ISO timestamp string |
| 67 | `_load_read_state` | file-ops | Load read state sidecar JSON |
| 77 | `_save_read_state` | file-ops | Write read state sidecar atomically with eviction |
| 106 | `_atomic_jsonl_append` | file-ops | O_APPEND JSONL write with mkdir |
| 129 | `create_package` | session-management | Create session observability package |
| 218 | `resolve_package_root` | session-management | Lookup package_root for session_id |
| 248 | `next_seq` | session-management | Atomic file-based monotonic counter |
| 276 | `append_event` | logging/telemetry | Append JSONL record to hook_events.jsonl |
| 315 | `record_error` | error-handling | Append structured error to errors.jsonl |
| 342 | `register_artifact` | logging/telemetry | Append artifact registration record |
| 370 | `_read_manifest` | file-ops | Read and parse manifest from open file |
| 379 | `update_manifest` | session-management | flock-protected manifest merge |
| 401 | `update_manifest_array` | session-management | flock-protected manifest array append |
| 429 | `generate_overhead_report` | metrics | Generate overhead report from full transcript |
| 519 | `update_manifest_if_absent_batch` | session-management | Write multiple keys if gate_key absent |
| 546 | `update_health` | session-management | Update subsystem health state |

### hooks/obs-session-start.py (2 functions)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 12 | `_file_stats` | file-ops | Return file stats dict (path, lines, bytes, mtime) |
| 24 | `_scan_inventory` | session-management | Scan Claude runtime environment and write inventory |
| 107 | `main` | other | Session start hook entrypoint |

### hooks/obs-session-end.py (4 functions)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 24 | `_count_lines` | file-ops | Fast line count via raw read |
| 33 | `_load_manifest` | file-ops | Load manifest.json returning {} on error |
| 43 | `validate_finalization` | validation | Validate session finalization status |
| 85 | `generate_session_summary` | data-transform | Generate quick session summary |
| 109 | `main` | other | Session end hook entrypoint |

### hooks/obs-prompt-submit.py (2 functions)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 32 | `_detect_plan_mode` | validation | Detect plan mode triggers in prompt |
| 38 | `main` | other | Prompt submit hook entrypoint |

### hooks/obs-pretool-read.py (1 function)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 37 | `main` | other | PreToolUse(Read) hook entrypoint |

### hooks/obs-posttool-bash.py (2 functions)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 44 | `_hash16` | string-utils | SHA-256 truncated to 16 hex chars |
| 49 | `main` | other | PostToolUse(Bash) hook entrypoint |

### hooks/obs-posttool-edit.py (3 functions)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 28 | `_build_patch_from_structured` | data-transform | Build unified diff from structured patch |
| 57 | `_build_patch_from_strings` | data-transform | Build unified diff from old/new strings |
| 74 | `main` | other | PostToolUse(Edit) hook entrypoint |

### hooks/obs-posttool-write.py (2 functions)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 41 | `_build_patch` | data-transform | Build unified-diff-like patch for Write |
| 70 | `main` | other | PostToolUse(Write) hook entrypoint |

### hooks/obs-posttool-failure.py (1 function)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 19 | `main` | other | PostToolUseFailure hook entrypoint |

### hooks/obs-precompact.py (1 function)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 22 | `main` | other | PreCompact obs hook entrypoint |

### hooks/obs-stop-cache.py (4 functions)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 36 | `_extract_latest_cache_metrics` | data-transform | Extract cache metrics from last transcript entry |
| 96 | `_extract_usage_from_entry` | data-transform | Extract (usage, model, entry_id) from transcript entry |
| 123 | `_read_last_sidecar_entry` | file-ops | Read last non-empty line of sidecar JSONL |
| 144 | `_read_compaction_count` | file-ops | Read compaction count from manifest |
| 155 | `main` | other | Stop cache hook entrypoint |

### hooks/obs-subagent-stop.py (1 function)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 18 | `main` | other | SubagentStop obs hook entrypoint |

### hooks/obs-task-completed.py (1 function)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 26 | `main` | other | TaskCompleted obs hook entrypoint |

### hooks/precompact-preserve.py (4 functions)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 21 | `main` | other | PreCompact preservation hook entrypoint |
| 52 | `_get_open_tasks` | file-ops | Read non-completed tasks from session task directory |
| 95 | `_resolve_task_list_id` | string-utils | Resolve local task-list directory ID |
| 107 | `_get_active_plan` | file-ops | Find most recently modified plan file |

### hooks/session-end-summary.py (4 functions)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 21 | `main` | other | SessionEnd summary hook entrypoint |
| 53 | `_count_open_tasks` | file-ops | Count non-completed tasks |
| 89 | `_resolve_task_list_id` | string-utils | Resolve local task-list directory ID |
| 101 | `_get_active_plan` | file-ops | Find most recently modified plan file name |

### hooks/subagent-stop-gate.py (1 function)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 39 | `main` | other | SubagentStop handoff gate entrypoint |

### hooks/task-completed-gate.py (3 functions)

| Line | Name | Category | Purpose |
|------|------|----------|---------|
| 25 | `main` | other | TaskCompleted evidence gate entrypoint |
| 75 | `_check_git_changes` | validation | Tri-state git probe (dirty/clean/unknown) |
| 89 | `_has_code_evidence` | validation | Check if task text suggests code implementation |

---

## Duplicate Groups

### HIGH Confidence

#### H1: Stdin Reading / JSON Parsing

**Intent:** Read JSON from stdin with timeout, parse, validate as dict.

| Function | File | Line |
|----------|------|------|
| `read_stdin_with_timeout` + `read_hook_input` | hooks/hook_utils.py | 22, 29 |
| `read_stdin_bounded` | src/statusline.py | 401 |

**Differences:**
- `hook_utils.read_hook_input` uses `select` on `sys.stdin` (text mode), reads up to 1MB, 2s timeout.
- `statusline.read_stdin_bounded` uses `select` on `sys.stdin.buffer` (binary mode), reads up to 512KB, 0.2s deadline.
- Both parse JSON, validate isinstance(dict), return dict|None.

**Recommendation:** KEEP_SEPARATE. The two have deliberately different contracts: hooks need 2s timeout and text-mode for Claude Code's pipe semantics; the statusline needs 200ms deadline and binary-mode for byte-budget enforcement. They share intent but the implementation differences are load-bearing.

---

#### H2: _resolve_task_list_id (Exact Clone)

**Intent:** Resolve the local task-list directory ID from env override or session_id.

| Function | File | Line |
|----------|------|------|
| `_resolve_task_list_id` | hooks/precompact-preserve.py | 95 |
| `_resolve_task_list_id` | hooks/session-end-summary.py | 89 |

**Differences:** NONE. Identical implementation, identical docstring, identical logic: check `CLAUDE_CODE_TASK_LIST_ID` env var, call `sanitize_task_list_id`, fall back to session_id.

**Recommendation:** CONSOLIDATE. Move to `hook_utils.py` where `sanitize_task_list_id` already lives. Both files already import from `hook_utils`. Estimated savings: ~12 lines of pure duplication.

**Keep:** The `hook_utils.py` version (to be created).

---

#### H3: _get_active_plan (Near-Clone)

**Intent:** Find the most recently modified plan file in `~/.claude/plans/`.

| Function | File | Line |
|----------|------|------|
| `_get_active_plan` | hooks/precompact-preserve.py | 107 |
| `_get_active_plan` | hooks/session-end-summary.py | 101 |

**Differences:**
- `precompact-preserve` returns `f"Active plan: {name}"` (full sentence).
- `session-end-summary` returns `os.path.basename(latest)` (bare filename).
- Same `glob.glob` + `max(key=os.path.getmtime)` + `log_hook_diagnostic` pattern.

**Recommendation:** CONSOLIDATE. Extract a shared `_find_latest_plan() -> str | None` to `hook_utils.py` that returns the bare filename. Let callers format the output. Estimated savings: ~20 lines.

**Keep:** Neither; create a shared `_find_latest_plan` in `hook_utils.py`.

---

#### H4: _extract_usage / _extract_usage_from_entry (Semantic Duplicate)

**Intent:** Extract usage dict from a transcript JSONL entry, handling both `message.usage` and `toolUseResult.usage` paths, skipping streaming stubs.

| Function | File | Line |
|----------|------|------|
| `_extract_usage` | src/context_overhead.py | 255 |
| `_extract_usage_from_entry` | hooks/obs-stop-cache.py | 96 |

**Differences:**
- `context_overhead._extract_usage` returns `(usage, request_id)` -- uses `requestId` for dedup.
- `obs-stop-cache._extract_usage_from_entry` returns `(usage, model, entry_id)` -- also extracts model name and uses message `id` or `uuid` for dedup.
- Both check `stop_reason is not None` to skip streaming stubs.
- Both handle the `message` and `toolUseResult` branches identically.

**Recommendation:** CONSOLIDATE. Create a single `_extract_usage_full(entry) -> (usage, model, request_id, entry_id)` in a shared location (likely `obs_utils.py` since both consumers already depend on it). Each caller destructures only what it needs. Estimated savings: ~25 lines.

**Keep:** Create unified version in `obs_utils.py`.

---

#### H5: JSONL Atomic Append (Two Implementations)

**Intent:** Atomically append a JSON line to a file using O_APPEND.

| Function | File | Line |
|----------|------|------|
| `_write_ledger_record` | hooks/hook_utils.py | 47 |
| `_atomic_jsonl_append` | hooks/obs_utils.py | 106 |

**Differences:**
- `hook_utils._write_ledger_record` always writes to `_LEDGER_PATH`, does `os.makedirs` every call, returns nothing.
- `obs_utils._atomic_jsonl_append` writes to any path, caches `_dirs_ensured` for mkdir skip, returns bool success.
- Both use identical `os.open(path, O_WRONLY | O_APPEND | O_CREAT, 0o644)` + `os.write` + `os.close`.

**Recommendation:** CONSOLIDATE. Replace `_write_ledger_record` body with a call to `_atomic_jsonl_append(_LEDGER_PATH, record)`. The `hook_utils` module does not currently import from `obs_utils` (deliberate isolation), but the reverse dependency already exists. Alternative: inline the 3-line O_APPEND pattern into `_write_ledger_record` as a thin wrapper that calls `_atomic_jsonl_append`. Estimated savings: ~10 lines, plus architectural clarity.

**Keep:** `obs_utils._atomic_jsonl_append` (more general, returns status).

---

### MEDIUM Confidence

#### M1: Manifest Loading (3 Implementations)

**Intent:** Load and parse `manifest.json` from a package root, returning {} on error.

| Function | File | Line |
|----------|------|------|
| `_read_manifest(manifest_path, f)` | hooks/obs_utils.py | 370 |
| `_load_manifest(package_root)` | hooks/obs-session-end.py | 33 |
| `_read_obs_health(package_root)` (partial) | src/statusline.py | 1866 |
| `_read_manifest_anchor(package_root)` (partial) | src/context_overhead.py | 457 |
| `_read_compaction_count(package_root)` (partial) | hooks/obs-stop-cache.py | 144 |

**Differences:**
- `obs_utils._read_manifest` takes an open file object (used inside flock blocks).
- `obs-session-end._load_manifest` takes package_root, opens the file, returns full manifest dict.
- `statusline._read_obs_health` opens manifest and extracts `health.overall`.
- `context_overhead._read_manifest_anchor` opens manifest and extracts `cache_anchor`.
- `obs-stop-cache._read_compaction_count` opens manifest and reads `len(compactions)`.

**Recommendation:** INVESTIGATE. The last three are single-field extractors that each independently open+parse manifest.json. A shared `load_manifest(package_root) -> dict` function in `obs_utils.py` (similar to what `_load_manifest` in `obs-session-end.py` already is) would let all callers do `m = load_manifest(root); m.get("health", {}).get("overall")`. However, these are in different processes (hooks vs statusline), so no runtime sharing. The consolidation benefit is purely DRY/maintenance.

**Keep:** Promote `_load_manifest` to `obs_utils.py` as a public function.

---

#### M2: Task Directory Reading (Two Implementations)

**Intent:** Read task JSON files from `~/.claude/tasks/<session_id>/` and filter by status.

| Function | File | Line |
|----------|------|------|
| `_get_open_tasks(session_id)` | hooks/precompact-preserve.py | 52 |
| `_count_open_tasks(session_id)` | hooks/session-end-summary.py | 53 |

**Differences:**
- `_get_open_tasks` builds a formatted string of task entries with subjects, IDs, and blocked-by info.
- `_count_open_tasks` returns `(total_open, in_progress)` counts only.
- Both iterate `os.listdir(task_path)`, open each `.json` file, parse it, check `status in ("pending", "in_progress")`.

**Recommendation:** CONSOLIDATE. Extract a shared `_iter_open_tasks(session_id) -> list[dict]` that returns the raw task dicts. Each caller formats as needed. Estimated savings: ~20 lines.

**Keep:** Create shared `_iter_open_tasks` in `hook_utils.py`.

---

#### M3: Timestamp Generation (Multiple Patterns)

**Intent:** Generate an ISO 8601 UTC timestamp string.

| Function/Pattern | File | Line |
|------------------|------|------|
| `_now_iso()` | hooks/obs_utils.py | 63 |
| `datetime.now(timezone.utc).isoformat()` (inline) | hooks/hook_utils.py | 71 |
| `datetime.now(timezone.utc).isoformat()` (inline) | hooks/obs-posttool-bash.py | 123 |
| `datetime.now(tz=timezone.utc).isoformat()` (inline) | hooks/obs-session-start.py | 18, 50, 87 |
| `datetime.now(timezone.utc).isoformat()` (inline) | src/statusline.py | 1961 |

**Differences:** All produce the same output. `_now_iso()` wraps the one-liner. The inline patterns are identical.

**Recommendation:** CONSOLIDATE. The `_now_iso()` function exists in `obs_utils.py` and is already imported by several hooks. Replace inline `datetime.now(timezone.utc).isoformat()` calls in `hook_utils.py:71` and `obs-posttool-bash.py:123` with `_now_iso()` imports. For `obs-session-start.py`, the 3 inline uses could import `_now_iso`. For `statusline.py`, it already imports from `obs_utils` via the guarded path. Low risk, high consistency. Estimated savings: ~6 lines + import consistency.

**Keep:** `obs_utils._now_iso`.

---

#### M4: SHA-256 Hash Truncation (Two Implementations)

**Intent:** Compute SHA-256 of a string and truncate to 16 hex chars.

| Function | File | Line |
|----------|------|------|
| `_hash16(s)` | hooks/obs-posttool-bash.py | 44 |
| Inline: `hashlib.sha256(prompt.encode()).hexdigest()[:16]` | hooks/obs-prompt-submit.py | 66 |
| Inline: `hashlib.sha256(patch_content.encode()).hexdigest()[:16]` | hooks/obs-posttool-edit.py | 122 |
| Inline: `hashlib.sha256(patch_content.encode()).hexdigest()[:16]` | hooks/obs-posttool-write.py | 122 |
| Inline: `hashlib.sha256(command.encode()).hexdigest()[:16]` | hooks/obs-posttool-failure.py | 54 |

**Differences:** All do `hashlib.sha256(s.encode()).hexdigest()[:16]`. The `_hash16` function in bash hook wraps this. The 4 inline uses are identical one-liners.

**Recommendation:** CONSOLIDATE. Move `_hash16` to `hook_utils.py` and replace all 5 inline/local usages. Estimated savings: ~8 lines + single definition for the truncation length.

**Keep:** Create `hash16` in `hook_utils.py`.

---

#### M5: OBS_ROOT Override Pattern (Boilerplate Clone)

**Intent:** Check `OBS_ROOT` env var and build kwargs dict for `resolve_package_root`.

| Pattern | Files | Approx occurrences |
|---------|-------|--------------------|
| `obs_root = os.environ.get("OBS_ROOT")` / `kwargs = {"obs_root": obs_root} if obs_root else {}` | obs-session-start.py, obs-session-end.py, obs-prompt-submit.py, obs-pretool-read.py, obs-posttool-bash.py, obs-posttool-edit.py, obs-posttool-write.py, obs-posttool-failure.py, obs-precompact.py, obs-subagent-stop.py, obs-task-completed.py, obs-stop-cache.py, statusline.py (x2) | 14 |

**Differences:** None. Exact same 3-line boilerplate in every hook.

**Recommendation:** CONSOLIDATE. Add a helper `resolve_package_root_env(session_id) -> str | None` to `obs_utils.py` that internalizes the `OBS_ROOT` env var check. Every hook replaces 4 lines with 1. Estimated savings: ~42 lines of boilerplate across 14 sites.

**Keep:** Create `resolve_package_root_env` in `obs_utils.py`.

---

### LOW Confidence

#### L1: Transcript JSONL Tail Reading (Two Approaches)

**Intent:** Read trailing lines from a session transcript JSONL by seeking near EOF.

| Function | File | Line |
|----------|------|------|
| `_read_transcript_tail` | src/context_overhead.py | 288 |
| `_extract_latest_cache_metrics` | hooks/obs-stop-cache.py | 36 |

**Differences:**
- `_read_transcript_tail` reads 50KB tail, collects ALL usage turns with requestId dedup, computes exponential-decay cache hit rate.
- `_extract_latest_cache_metrics` reads 8KB tail, finds only the LAST completed entry, extracts granular cache fields (1h/5m breakdown).
- Different tail window sizes, different dedup strategies, different output shapes.

**Recommendation:** KEEP_SEPARATE. Despite sharing the tail-seek + JSONL parse pattern, they serve fundamentally different purposes: rolling window analysis vs single-turn extraction. The data shapes and scan strategies are too different to merge without adding complexity.

---

#### L2: Read State Sidecar Access

**Intent:** Load/save custom/.read_state.json for reread tracking.

| Function | File | Consumer |
|----------|------|----------|
| `_load_read_state` / `_save_read_state` | hooks/obs_utils.py | obs-pretool-read.py, obs-posttool-edit.py, obs-posttool-write.py |

**Differences:** Single implementation, used by 3 hooks.

**Recommendation:** KEEP_SEPARATE. Already properly centralized in `obs_utils.py`. No duplication.

---

#### L3: render_obs_* Module Renderers (Structural Similarity)

**Intent:** Render an observability counter as a pill.

| Functions | File | Lines |
|-----------|------|-------|
| `render_obs_reads`, `render_obs_writes`, `render_obs_bash`, `render_obs_subagents`, `render_obs_tasks`, `render_obs_compactions`, `render_obs_prompts` | src/statusline.py | 1527-1621 |

**Differences:** Each extracts a different state key and uses a different glyph. Otherwise identical: `n = state.get(key); if not n: return None; return _pill(f"{glyph}{n}", cfg, theme=theme)`.

**Recommendation:** INVESTIGATE. These 7 functions are structurally identical and could be replaced by a data-driven factory (like `_render_system_metric` already does for cpu/memory/disk). A `_render_obs_counter(state, theme, state_key, theme_key)` function + a registry dict would eliminate ~60 lines. The two with threshold coloring (`render_obs_rereads`, `render_obs_failures`) need the threshold path, which `_render_system_metric` already supports.

**Keep:** Create `_render_obs_counter` and refactor.

---

#### L4: generate_overhead_report vs _try_phase2_transcript

**Intent:** Analyze a session transcript for cache/overhead metrics.

| Function | File | Line |
|----------|------|------|
| `generate_overhead_report` | hooks/obs_utils.py | 429 |
| `_try_phase2_transcript` | src/context_overhead.py | 473 |

**Differences:**
- `generate_overhead_report` reads the ENTIRE transcript, computes session-level aggregates (total cache read/create, overall hit rate, busting events), writes to derived/overhead_report.json. Called at session end.
- `_try_phase2_transcript` reads only the trailing window, computes rolling cache state, detects busting/degradation in real time. Called on every statusline render.
- Completely different execution contexts and output shapes.

**Recommendation:** KEEP_SEPARATE. Different lifecycle points (end-of-session vs per-render), different analysis scopes (full session vs trailing window), different outputs. Merging would harm both.

---

## Recommendations

Ranked by impact (lines saved x risk reduction x maintenance benefit):

| Rank | Group | Action | Lines Saved | Files Touched | Risk |
|------|-------|--------|-------------|---------------|------|
| 1 | M5: OBS_ROOT boilerplate | Add `resolve_package_root_env` to obs_utils.py | ~42 | 13 hooks + obs_utils | Very low |
| 2 | H4: _extract_usage | Unify to `_extract_usage_full` in obs_utils.py | ~25 | context_overhead.py, obs-stop-cache.py, obs_utils.py | Low |
| 3 | H2: _resolve_task_list_id | Move to hook_utils.py | ~12 | precompact-preserve.py, session-end-summary.py, hook_utils.py | Very low |
| 4 | H3: _get_active_plan | Extract `_find_latest_plan` to hook_utils.py | ~20 | precompact-preserve.py, session-end-summary.py, hook_utils.py | Very low |
| 5 | M2: Task directory reading | Extract `_iter_open_tasks` to hook_utils.py | ~20 | precompact-preserve.py, session-end-summary.py, hook_utils.py | Low |
| 6 | L3: render_obs_* | Factory pattern for 7 counter renderers | ~60 | statusline.py | Low |
| 7 | M4: SHA-256 hash16 | Move `_hash16` to hook_utils.py | ~8 | 4 hook files + hook_utils.py | Very low |
| 8 | M3: _now_iso inlines | Replace inline timestamps with _now_iso import | ~6 | 3 hook files + statusline.py | Very low |
| 9 | H5: JSONL atomic append | Use _atomic_jsonl_append in hook_utils | ~10 | hook_utils.py | Low (import direction) |
| 10 | M1: Manifest loading | Promote _load_manifest to obs_utils.py | ~15 | obs-session-end.py, statusline.py, context_overhead.py, obs-stop-cache.py | Low |

**Total estimated consolidation: ~218 lines eliminated, 14 groups resolved.**

### Priority Implementation Order

**Phase A (Quick wins, no risk):** H2 + H3 + M4 + M3 (items 3, 4, 7, 8)
- All involve moving exact clones to hook_utils.py
- ~46 lines, 0 behavioral change

**Phase B (Medium effort, low risk):** M5 + M2 + M1 (items 1, 5, 10)
- Boilerplate elimination across hooks
- ~77 lines, minimal behavioral change

**Phase C (Architectural improvement):** H4 + L3 + H5 (items 2, 6, 9)
- Requires careful interface design for shared extraction and rendering
- ~95 lines, some API surface changes
