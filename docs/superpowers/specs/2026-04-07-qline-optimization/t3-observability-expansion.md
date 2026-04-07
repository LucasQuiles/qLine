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

For every data source qLine currently reads, document what questions it can answer:

| Source | Location | Reader | Questions It Answers |
|--------|----------|--------|---------------------|
| Statusline stdin payload | Piped from Claude Code | `read_stdin_bounded()` | Current model, session_id, conversation state, cost, duration, turn count |
| Transcript JSONL | `~/.claude/projects/*/` (path from session) | `_read_transcript_tail()`, `_read_transcript_anchor()` | Cache create/read tokens per turn, baseline system overhead, model used |
| Hook input payloads | stdin to each hook script | `read_hook_input()` | Event-specific data: tool name, file paths, exit codes, task results |
| hook_events.jsonl | `<package>/metadata/hook_events.jsonl` | `_inject_obs_counters()` | Event counts by type, session timeline, tool usage patterns |
| artifact_index.jsonl | `<package>/metadata/artifact_index.jsonl` | Not currently read by statusline | Artifact/patch records (available but unused by render path) |
| manifest.json | `<package>/manifest.json` | `_read_manifest_anchor()` | Session health, overhead anchors, session start time, inventory snapshot |
| session_inventory.json | `<package>/metadata/session_inventory.json` | Used at session start | CLAUDE.md paths, MCP servers, plugin list, settings snapshot |
| custom/bash_commands.jsonl | `<package>/custom/bash_commands.jsonl` | Not read by statusline | Full bash command details (hash, exit code, preview) |
| custom/cache_metrics.jsonl | `<package>/custom/cache_metrics.jsonl` | `context_overhead.py` | Per-turn cache forensics (cache_create, cache_read, model, timestamp) |
| custom/reads.jsonl | `<package>/custom/reads.jsonl` | Not read by statusline | File read audit with reread tracking |
| custom/writes.jsonl | `<package>/custom/writes.jsonl` | Not read by statusline | File write/edit details (path, hash, line delta) |
| .read_state | `<package>/metadata/.read_state` | Obs read tracking | Reread detection state |
| .seq_counter | `<package>/metadata/.seq_counter` | `next_seq()` | Monotonic event ordering |
| /tmp/qline-cache.json | `/tmp/qline-cache.json` | statusline.py cache logic | Cached system metrics (CPU, mem, disk, git), last render state |
| Runtime session map | `~/.claude/observability/runtime/<sid>.json` | `resolve_package_root()` | Session ID → package root path mapping |
| qline.toml config | `~/.config/qline.toml` | `load_config()` | User preferences: enabled modules, thresholds, colors |
| Process/system stats | `/proc/stat`, `/proc/meminfo`, `os.statvfs()`, `git` commands | `collect_system_data()` | CPU %, memory %, disk %, git branch/SHA/dirty |
| Claude settings | `~/.claude/settings.json` | Session inventory scan | Enabled hooks, plugin paths, permission settings |

### 3.2 — Missing Visibility Identification

For each gap, assess whether it would materially improve debugging or session understanding:

| ID | Gap | Impact | Why It Matters | Current Workaround |
|----|-----|--------|---------------|-------------------|
| MV-01 | Per-hook latency and timeout counts | High | Slow hooks degrade CC responsiveness; no way to know which hook is slow without external timing | Manual stderr inspection |
| MV-02 | Source freshness / last-updated timestamps | High | Stale data is displayed without age indication; user can't tell if context bar reflects current state | Check file mtime manually |
| MV-03 | Transcript parse failures and skip reasons | Medium | Silent failures in transcript reading hide accuracy issues; `_read_transcript_tail()` swallows errors | None — failures are invisible |
| MV-04 | Statusline render latency and cache-hit stats | Medium | Can't measure statusline's own performance overhead or cache effectiveness | None |
| MV-05 | Hook coverage gaps by event/tool type | Medium | If a hook is unregistered or failing, events are silently lost; no way to detect missing coverage | Compare hooks.json against settings.json manually |
| MV-06 | Per-session data volume and artifact churn | Low | Large sessions may degrade scan performance; no volume metrics to predict | Count files/lines manually |
| MV-07 | Schema version markers for package compatibility | Low | No way to detect if an old session package uses a different schema than current code expects | Assume compatibility |
| MV-08 | Compaction impact on overhead anchors | Medium | After compaction, the overhead anchor may be stale; no signal tells statusline to re-anchor | None — silent staleness |
| MV-09 | Hook execution order and concurrency | Low | Multiple hooks on same event may race; no ordering guarantee visibility | Assume sequential |
| MV-10 | Session resume/continue detection | High | Resumed sessions may have stale state from prior invocation; no explicit resume signal | Check session.reentry event count |

### 3.3 — Proposed Schema Additions

For each high/medium impact gap, propose an additive schema. All proposals follow TX rules: additive only, JSONL sidecars preferred, no breaking changes.

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

**Implementation notes:**
- `run_fail_open()` already wraps every hook; add timing before/after the `main_fn()` call
- Writes are Tier 1 (recoverable) — failure to log perf data never blocks the hook
- Statusline can optionally render: slowest hook, timeout count, total hook overhead

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

**Implementation notes:**
- Each writer updates its corresponding timestamp on write
- Statusline reads these to compute "data age" per source
- Old manifests without these keys: graceful degradation (no age display)

#### 3.3.3 — Parse Diagnostic Sidecar

**For:** MV-03 (transcript parse failures) + MV-04 (render latency) — bundled into a single sidecar because both are statusline self-diagnostics with the same writer and lifecycle. T5 may reference either MV-03 or MV-04 independently but both map to this one schema proposal.

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

**Implementation notes:**
- Writes are best-effort (Tier 2) — never delay render for diagnostics
- Keeps last N entries (ring buffer or daily rotation) to bound file size
- Enables post-session analysis of statusline health

#### 3.3.4 — Package Schema Version

**For:** MV-07 (schema compatibility)

```
Location: manifest.json (additive key)

New key:
{
  "schema_version": "1.1.0"
}
```

**Implementation notes:**
- Semantic versioning: major = breaking layout change, minor = additive fields, patch = fixes
- Current schema is retroactively `1.0.0`
- Readers check version and degrade gracefully for unknown major versions

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
  "reason": "context_reset",
  "prior_anchor": <int>,  // old overhead anchor value
  "action": "re_anchor_on_next_stop"
}
```

**Implementation notes:**
- Written by `obs-precompact.py` after logging `compact.started`
- `context_overhead.py` checks for this event to force re-anchoring on the next Stop
- Falls within existing event envelope — no new file needed

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

**Implementation notes:**
- Computed at session start by `obs-session-start.py`
- Compares hooks.json entries against settings.json registrations and hook files on disk
- One-time cost at session start; no ongoing overhead

---

## Codebase Pointers

| What | Where | Key Lines |
|------|-------|-----------|
| Hook wrapper | `hooks/hook_utils.py` | `run_fail_open()` — instrument here for MV-01 |
| Obs counter scan | `src/statusline.py` | `_inject_obs_counters()` — linear scan of hook_events.jsonl |
| Transcript reading | `src/context_overhead.py` | `_read_transcript_tail()`, `_read_transcript_anchor()` |
| Manifest read/write | `hooks/obs_utils.py` | `update_manifest()`, `create_package()` |
| Session inventory | `hooks/obs-session-start.py` | Inventory scan at session start |
| Cache write | `hooks/obs-stop-cache.py` | Writes to custom/cache_metrics.jsonl |
| Precompact hook | `hooks/obs-precompact.py` | Compaction event logging |
| Metrics cache | `src/statusline.py` | `/tmp/qline-cache.json` read/write logic |

---

## Acceptance Criteria

- [ ] Source inventory table complete — every current data source documented with reader and questions answered
- [ ] Missing visibility table includes all identified gaps (currently 10; document any additional ones found)
- [ ] Schema proposals provided for all high and medium impact gaps
- [ ] Every proposal follows TX additive change rules
- [ ] Every proposal includes: location, writer, reader, schema, implementation notes
- [ ] Backward compatibility addressed for each proposal (what happens with old packages)
- [ ] No proposal requires changes to existing event types or manifest keys
- [ ] Proposals labeled with supported-vs-fragile classification where relevant

---

## Risks

| Risk | Mitigation |
|------|------------|
| Hook performance instrumentation adds latency to hooks | Timing overhead is ~1ms (datetime calls); measure to confirm |
| Diagnostics sidecar grows unbounded | Use ring buffer or daily rotation; bound at 1000 lines |
| Too many new sidecars fragment the package layout | Group related diagnostics; prefer extending existing files over creating new ones |

---

## Do Not Decide Here

- Which proposals to implement (that's T5)
- Whether new sidecars should be read by the statusline hot path or only for post-session analysis (T2 informs this)
- Priority ordering of gaps (T5 ranks by impact across all tracks)
