# TX — Data Contracts & Cross-Cutting Standards

## Objective

Define the shared artifact formats, public interface preservation rules, replay harness conventions, experiment template, and evidence standards referenced by all track runners (T1-T5).

## Non-Goals

- Implementing any changes to qLine source code
- Designing new features or optimizations (those belong in T1-T4)
- Defining the experiment ranking methodology (that belongs in T5)

---

## 1. Public Interface Registry

These surfaces are the current public contract. No track may propose breaking changes to these in the first optimization pass. Additions must be additive and versioned.

### 1.1 Plugin Manifest

| Surface | Path | Contract |
|---------|------|----------|
| Plugin metadata | `.claude-plugin/plugin.json` | Fields: name, version, description, author. Version bump required for any behavioral change. |
| Hook registration | `hooks/hooks.json` | Event matchers, timeout values, command paths via `${CLAUDE_PLUGIN_ROOT}`. New hooks additive only. |

### 1.2 Statusline Interface

| Surface | Contract |
|---------|----------|
| stdin payload | JSON object from Claude Code. Fields used: `cwd`, `model`, `session_id`, `conversation`, `duration_ms`, `total_cost_usd`, `num_turns`. Sparse-safe: missing fields produce graceful degradation, never errors. |
| stdout | Single ANSI-styled line (or multi-line if configured). Exit 0 always. |
| Environment | `NO_COLOR`, `QLINE_NO_COLLECT`, `QLINE_CONFIG` respected. |
| Config file | `~/.config/qline.toml` — TOML format, optional. All keys have defaults. |

### 1.3 Session Package Layout

| Path Pattern | Contract |
|-------------|----------|
| `~/.claude/observability/sessions/<YYYY-MM-DD>/<session_id>/` | Package root. Created by `obs-session-start.py`. |
| `manifest.json` | Session metadata, health state, overhead anchors. Schema must remain backward-compatible. |
| `source_map.json` | Lookup key for resolving package root from session_id. |
| `metadata/hook_events.jsonl` | Append-only event ledger. Each line is a self-contained JSON object with `seq`, `ts`, `event`, `session_id`. |
| `metadata/errors.jsonl` | Fault/warning records. Same append-only contract. |
| `metadata/artifact_index.jsonl` | Artifact/patch records. |
| `metadata/.seq_counter` | Atomic monotonic counter file. |
| `metadata/session_inventory.json` | Session environment snapshot (CLAUDE.md paths, MCP servers, plugins, settings). Written once at session start. Schema backward-compatible. |
| `custom/*.jsonl` | Per-domain detail ledgers (bash_commands, cache_metrics, reads, writes). |
| `runtime/<session_id>.json` | Quick-lookup mapping: session_id to package root. |

### 1.4 Hook Event Types

Current event types in `hook_events.jsonl`. New types may be added; existing types must not be renamed or restructured.

| Event Type | Origin Hook | Payload Contract |
|------------|-------------|-----------------|
| `session.started` | obs-session-start | package_root, inventory snapshot |
| `session.reentry` | obs-session-start | reentry count |
| `session.ended` | obs-session-end | summary stats |
| `read.pretool` | obs-pretool-read | path, bytes, mtime |
| `write.posttool` | obs-posttool-write | path, hash, line_delta |
| `bash.executed` | obs-posttool-bash | command_hash, exit_code, preview |
| `edit.posttool` | obs-posttool-edit | changed_files list |
| `failure.posttool` | obs-posttool-failure | tool_name, error |
| `prompt.observed` | obs-prompt-submit | prompt_hash, length, plan_mode |
| `cache.observed` | obs-stop-cache | cache_create, cache_read, model |
| `compact.started` | obs-precompact | compact_seq, trigger_reason |
| `subagent.spawned` | obs-subagent-stop | subagent_id, source |
| `task.completed` | obs-task-completed | task_id, result_summary |

---

## 2. Additive Change Rules

### New Manifest Keys
- Place under a dedicated namespace (e.g., `"qline_v2": { ... }`) or use clearly named top-level additive fields
- Never remove or rename existing keys
- Consumers must tolerate missing new keys (sparse-safe)

### New Sidecars
- Place under `custom/` (domain-specific detail) or `native/statusline/` (statusline-specific state)
- Use `.jsonl` for append-only ledgers, `.json` for point-in-time snapshots
- Include a `schema_version` field in the first line or file header

### New Hook Event Types
- Add only when no existing event type can carry the signal cleanly
- Must follow the same `{ seq, ts, event, session_id, ... }` envelope
- Register in this contract doc before implementation

### New Hooks
- Append to `hooks/hooks.json`; never reorder existing entries
- Use `${CLAUDE_PLUGIN_ROOT}` for paths
- Default timeout: 5s (2s for Stop event)
- Must follow fail-open contract (exit 0 always)

---

## 3. Replay Harness Conventions

### Purpose
Tracks T1 and T2 need a replay mechanism to run qLine metric and render paths against known inputs and validate outputs.

### Dataset Structure

```
tests/replay/
├── fixtures/              ← static JSON payloads (existing + new)
│   ├── from-tests/        ← symlinks or copies from tests/fixtures/statusline/
│   └── synthetic/         ← edge-case fixtures authored during research
├── sessions/              ← curated real session package snapshots
│   └── <descriptive-name>/
│       └── <session_id>/  ← full package tree (manifest, hook_events, custom/*)
├── transcripts/           ← transcript fragments for cache/anchor validation
│   └── <scenario-name>.jsonl
└── expected/              ← expected outputs for regression comparison
    └── <fixture-name>.expected.txt
```

### Replay Execution Contract

A replay run:
1. Sets `QLINE_NO_COLLECT=1` (no live system metrics)
2. Pipes a fixture JSON to `src/statusline.py` via stdin
3. Optionally sets `QLINE_OBS_ROOT=<session-package>` to point at a curated session
4. Captures stdout (rendered statusline) and stderr (diagnostics)
5. Compares against expected output if available
6. Records: fixture name, metric values extracted, pass/fail, delta from expected

### Curated Session Selection

Select 3-5 real sessions from `~/.claude/observability/sessions/` that represent:
- Short session (< 10 events)
- Medium session (50-200 events, multiple tool types)
- Long session (500+ events, compaction present)
- Session with subagents
- Session with failures/errors

Copy the package tree (not symlink — sessions are mutable during active use).

---

## 4. Experiment Template

Every experiment proposed in T1-T4 and ranked in T5 must use this format:

```markdown
### EXP-<track>-<seq>: <title>

**Hypothesis:** What we expect to be true or to improve.

**Changed source(s):** File(s) and function(s) modified.

**Measurement method:** How we validate the hypothesis (replay, benchmark, manual inspection).

**Metrics captured:**
- Latency delta: <before> → <after> (ms)
- Correctness delta: <description>
- Fragility risk: low / medium / high (with justification)
- Observability gain: <description or "none">

**Claude-version sensitivity:** Does this depend on documented behavior, undocumented behavior, or internal-only signals?

**Implementation cost:** trivial / small / medium / large

**Evidence:** <link to replay output, benchmark log, or inline table>
```

---

## 5. Evidence Standards

### Claimed Issues
Every accuracy gap, latency bottleneck, or missing visibility claim must include:
- **Reproduction artifact:** fixture, session snapshot, or command that demonstrates the issue
- **Severity:** critical (wrong output), major (misleading output), minor (suboptimal but correct)
- **Affected metric:** which statusline module or observability field
- **Root cause hypothesis:** what code path or assumption is wrong
- **Confidence:** high (reproduced deterministically), medium (reproduced intermittently), low (theoretical)

### Supported vs Fragile Classification

For any qLine behavior that depends on Claude Code internals:

| Classification | Definition | Example |
|---------------|------------|---------|
| **Supported** | Documented in official Anthropic docs or stable across 3+ CC versions | stdin JSON fields, hook event schema |
| **Observed-stable** | Not documented but consistent across tested CC versions | transcript JSONL format, `/tmp` paths |
| **Fragile** | Known to change between CC versions or depends on undocumented timing | transcript line ordering, cache_create token counts, compaction trigger thresholds |
| **Speculative** | Inferred from behavior, never validated against multiple versions | internal context budgets, deferred tool loading heuristics |

---

## 6. Compatibility Boundaries

### Python Version
- Target: Python 3.11+ (macOS system Python or user-installed)
- Fallback: Python 3.10 with optional `tomli` for TOML config
- No pip dependencies in core statusline or hooks

### Claude Code Version
- Developed against: CC v2.1.92
- Constants in `context_overhead.py` are version-tagged (lines 48-52)
- Any version-sensitive behavior must be labeled in the fragility classification

### File System
- macOS primary (HFS+/APFS)
- Linux secondary (ext4/btrfs) — `/proc` metrics gracefully absent on macOS
- No Windows support assumed
