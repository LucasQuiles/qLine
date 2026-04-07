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

**Executed 2026-04-07.**

Official Anthropic Claude Code documentation was consulted for every surface qLine depends on. Primary sources: [Hooks reference](https://code.claude.com/docs/en/hooks), [Statusline docs](https://code.claude.com/docs/en/statusline), [Plugins reference](https://code.claude.com/docs/en/plugins-reference), [Context windows API docs](https://platform.claude.com/docs/en/build-with-claude/context-windows).

| Surface | What qLine Depends On | Documented? | Doc Source | Notes |
|---------|----------------------|-------------|------------|-------|
| Statusline stdin JSON payload | Field names: `model`, `cwd`, `session_id`, `context_window.*`, `cost.*`, `transcript_path`, `version`, `output_style`, `worktree` | **Yes** | [code.claude.com/docs/en/statusline](https://code.claude.com/docs/en/statusline) — "Available data" table + full JSON schema accordion | Complete field listing with types and absence/null semantics. qLine's `normalize()` reads `workspace.current_dir` (documented preferred), `model.display_name` (documented), `context_window.used_percentage` (documented), `cost.total_cost_usd` / `cost.total_duration_ms` (documented). **Gap:** qLine also reads `conversation` dict — this is NOT in current docs; likely removed or renamed. `num_turns` also not documented. `added_dirs` moved to `workspace.added_dirs`. |
| Statusline refresh behavior | How often CC calls the statusline command; conditions that trigger refresh | **Yes** | [code.claude.com/docs/en/statusline](https://code.claude.com/docs/en/statusline) — "How status lines work" section | "Runs after each new assistant message, when permission mode changes, or when vim mode toggles. Updates are debounced at 300ms. If a new update triggers while script is still running, the in-flight execution is cancelled." This is event-driven, not polling. |
| Hook lifecycle events | `SessionStart`, `Stop`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `UserPromptSubmit`, `PreCompact`, `SubagentStop`, `TaskCompleted`, `SessionEnd` | **Yes** | [code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks) — event table | All 10 events qLine uses are documented. Docs list 24 total events (more than qLine uses). **Notable:** docs now list `PostCompact` as a supported event (qLine does not use it yet). Also `Notification`, `SubagentStart`, `StopFailure`, `TeammateIdle`, `InstructionsLoaded`, `ConfigChange`, `CwdChanged`, `FileChanged`, `WorktreeCreate`, `WorktreeRemove`, `Elicitation`, `ElicitationResult` are documented events qLine does not use. |
| Hook input payload schema | JSON structure passed to each hook type via stdin | **Yes** | [code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks) — event-specific payload sections | Common fields: `session_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`, `agent_id`, `agent_type`. Per-event payloads well-documented. Stop event payload: common fields only (no cache metrics in Stop payload itself — cache data comes from transcript, not from the hook input). |
| Hook timeout behavior | What happens when a hook exceeds timeout; does CC kill the process? | **Yes** | [code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks) — timeout section | Default: 600s for command hooks (10 minutes), 30s for prompt, 60s for agent, 30s for HTTP. "When timeout expires, hook is cancelled. For command hooks: process is terminated." **Important:** qLine uses 2s (Stop) and 5s (all others), well under defaults. The custom `timeout` field in hooks.json is documented and respected. |
| Hook exit code semantics | Exit 0 = success; nonzero = ? (abort tool? log warning? ignore?) | **Yes** | [code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks) — exit code table | Exit 0 = success (parses stdout JSON). Exit 2 = blocking error (ignores stdout, uses stderr). Exit 1 or other = non-blocking error (shows stderr in verbose mode, continues). **Critical detail:** Exit 1 does NOT block — only exit 2 blocks. qLine hooks always exit 0 (fail-open), so this is correctly implemented. |
| `${CLAUDE_PLUGIN_ROOT}` substitution | Variable expansion in hooks.json command paths | **Yes** | [code.claude.com/docs/en/plugins-reference](https://code.claude.com/docs/en/plugins-reference) — environment variables section | Documented: resolves to plugin installation directory. "Both are substituted inline anywhere they appear in skill content, agent content, hook commands, and MCP or LSP server configs. Both are also exported as environment variables to hook processes and MCP or LSP server subprocesses." Also documents `${CLAUDE_PLUGIN_DATA}` for persistent data. **Note:** closed Windows bug #32486 where expansion failed — fixed. |
| Transcript JSONL format | Structure of conversation transcript files; location; update timing | **Partial** | `transcript_path` field documented in [statusline docs](https://code.claude.com/docs/en/statusline). Closed issue [#27724](https://github.com/anthropics/claude-code/issues/27724) confirms no public JSONL schema docs exist. | The `transcript_path` field is documented in the statusline JSON schema. The transcript is described as "a JSONL file — one JSON object per line" in third-party references. **However, the internal schema of each JSONL line is NOT officially documented.** No Anthropic doc specifies field names within transcript entries (e.g., `stop_reason`, `usage.cache_creation_input_tokens`, `type`, `message.id`). qLine's `obs-stop-cache.py` parses specific transcript entry fields — this is entirely undocumented. |
| Session ID semantics | When session_id changes; behavior on resume/continue; uniqueness guarantees | **Partial** | [statusline docs](https://code.claude.com/docs/en/statusline) documents `session_id` as "Unique session identifier" | The field exists and is documented in statusline JSON. **Gaps:** No documentation on: (a) when session_id changes vs persists on resume/continue, (b) uniqueness guarantees (UUID format?), (c) whether `--resume` reuses the same session_id. The SessionStart hook payload includes `source: "startup|resume|clear|compact"` which implies session_id persists across resume, but this is not explicitly stated. |
| Context window budget | Max tokens, output reserve, compaction trigger thresholds | **Partial** | [platform.claude.com context-windows](https://platform.claude.com/docs/en/build-with-claude/context-windows), [statusline docs](https://code.claude.com/docs/en/statusline) | `context_window_size` documented (200000 or 1000000). `used_percentage` formula documented: "calculated from input tokens only: input_tokens + cache_creation_input_tokens + cache_read_input_tokens. It does not include output_tokens." **Gaps:** CC internal constants qLine extracted from decompiled source (CC_OUTPUT_RESERVE=20000, CC_AUTOCOMPACT_BUFFER=13000, CC_WARNING_OFFSET=20000, CC_ERROR_OFFSET=20000, CC_BLOCKING_BUFFER=3000) are NOT documented anywhere. These are speculative extractions. |
| Cache behavior | cache_creation_input_tokens, cache_read_input_tokens fields in API responses | **Yes** | [statusline docs](https://code.claude.com/docs/en/statusline) — context_window.current_usage schema | `current_usage` object documented with: `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`. The `current_usage` object is `null` before the first API call. These are standard Anthropic API fields. Issue [#42646](https://github.com/anthropics/claude-code/issues/42646) reports inflated `used_percentage` after `/clear` due to cache_read inclusion. |
| Plugin installation | .claude-plugin/plugin.json schema; hooks.json schema; symlink discovery | **Yes** | [code.claude.com/docs/en/plugins-reference](https://code.claude.com/docs/en/plugins-reference) — complete schema documentation | Full plugin.json schema documented. hooks.json wrapped in `{"hooks": {...}}` documented. Plugin directory structure documented. Plugin caching: "Claude Code copies marketplace plugins to local plugin cache (~/.claude/plugins/cache)." For `--plugin-dir` installations (which is how qLine works via symlink), files are used in-place. **Note:** Symlink behavior is supported but described briefly: "create symbolic links to external files within your plugin directory. Symlinks are honored during the copy process." |

**Summary of documentation coverage:**
- **Fully documented (7):** Statusline stdin payload, statusline refresh, hook events, hook payload schema, hook timeout, exit codes, `${CLAUDE_PLUGIN_ROOT}`, cache `current_usage` fields, plugin installation
- **Partially documented (3):** Transcript JSONL (path yes, internal schema no), session ID (field yes, lifecycle semantics no), context window budget (sizes yes, internal thresholds no)
- **Not documented (0 complete gaps, but significant undocumented internals):** CC internal constants (output reserve, compaction buffer, warning/error offsets) used by `context_overhead.py`

### 4.2 — Public Issue Scan

**Executed 2026-04-07.** Searched `anthropics/claude-code` GitHub issues via `gh search issues`.

**Search areas and coverage:**

| Topic | Search Terms Used | Issues Found | Relevant to qLine |
|-------|------------------|-------------|-------------------|
| Statusline | `statusline`, `statusline refresh update`, `statusline missing fields`, `statusline session_id`, `context_window used_percentage` | 20+ | 8 relevant |
| Hook reliability | `hook PostToolUse PreToolUse timeout`, `hook timeout kill`, `hook not firing`, `hook exit code block` | 10+ | 6 relevant |
| Session/transcript | `session transcript resume continue`, `transcript JSONL format` | 0 direct hits | 2 related from cross-topic |
| Context/cache | `context cache compaction compact`, `cache_creation_input_tokens`, `compaction trigger threshold` | 10+ | 6 relevant |
| Plugin | `plugin hooks.json .claude-plugin` | 1 | 1 relevant |

**Relevant issues impacting qLine:**

| Issue # | Title | Status | Impact on qLine | Affected Surface | Severity |
|---------|-------|--------|-----------------|------------------|----------|
| [#37163](https://github.com/anthropics/claude-code/issues/37163) | Statusline should update after compact | Open (stale) | qLine's context bar goes stale after compaction until next assistant message triggers refresh. Cache/context metrics become misleading. | Statusline refresh | Medium |
| [#35816](https://github.com/anthropics/claude-code/issues/35816) | Status line does not refresh after /compact | Open (stale) | Same as above — confirmed: statusline is NOT refreshed after manual `/compact`. qLine displays pre-compaction context% until next turn. | Statusline refresh | Medium |
| [#40279](https://github.com/anthropics/claude-code/issues/40279) | Statusline collapses to 1 line on terminal resize | Open | qLine's multi-line output could be truncated on resize. May affect context bar visibility. | Statusline rendering | Low |
| [#42646](https://github.com/anthropics/claude-code/issues/42646) | `context_window.used_percentage` includes cache_read after /clear | Open | After `/clear`, used_percentage may be inflated by stale cache_read_input_tokens. qLine's context bar would show inflated usage. | Context window metrics | Medium |
| [#17959](https://github.com/anthropics/claude-code/issues/17959) | `used_percentage` doesn't match internal context warning | Open | CC's internal warning threshold uses a different formula than `used_percentage`. qLine's thresholds based on `used_percentage` may not align with when CC actually warns/errors. Explains discrepancy in qLine's CC internal constants. | Context window budget | High |
| [#28167](https://github.com/anthropics/claude-code/issues/28167) | Context percentage only counts input tokens — misleading at ~20% | Open | Confirms `used_percentage` excludes output tokens. qLine's overhead estimation must account for this. Already handled by qLine per TX constants. | Context window metrics | Low (already handled) |
| [#34202](https://github.com/anthropics/claude-code/issues/34202) | Compaction trigger threshold (150K) does not scale with 1M context | Open (dup) | CC's autocompact trigger may not scale properly with 1M windows. qLine's compaction-related overhead estimates depend on knowing when compaction fires. | Context window budget | Medium |
| [#24147](https://github.com/anthropics/claude-code/issues/24147) | Cache read tokens consume 99.93% of usage quota | Open | Architectural issue: CLAUDE.md re-reads cause massive cache_read accumulation. Affects qLine's cache health computation if cache_read inflates context metrics. | Cache behavior | Medium |
| [#23751](https://github.com/anthropics/claude-code/issues/23751) | Compaction fails 'Conversation too long' at 48% context | Open | Compaction can fail at unexpected thresholds. qLine's overhead monitor assumes compaction succeeds when triggered. | Context window budget | Medium |
| [#44075](https://github.com/anthropics/claude-code/issues/44075) | SubagentStart hooks not fired for background agents | Open | qLine does not use SubagentStart, but SubagentStop (which qLine uses) could have similar gaps for background agents. Subagent session tracking may miss events. | Hook reliability | Low |
| [#29881](https://github.com/anthropics/claude-code/issues/29881) | Stop hook not fired when Claude stalls mid-turn | Open | If Stop hook fails to fire, `obs-stop-cache.py` misses cache metrics for that turn. Cache health goes stale. | Hook reliability (Stop) | High |
| [#33712](https://github.com/anthropics/claude-code/issues/33712) | Stop hook does not fire when response contains newlines | Open (stale) | Similar to above — Stop hook reliability affects cache metric capture. WSL-specific but indicates fragility. | Hook reliability (Stop) | Medium |
| [#31114](https://github.com/anthropics/claude-code/issues/31114) | UserPromptSubmit hooks not fired when user sends mid-turn | Open (stale) | qLine's prompt tracking via `obs-prompt-submit.py` may miss prompts sent during active turns. | Hook reliability | Low |
| [#40010](https://github.com/anthropics/claude-code/issues/40010) | SessionEnd: agent-type hooks silently ignored | Open | qLine uses command-type hooks (not affected), but indicates hook type handling inconsistencies. | Hook reliability | Low |
| [#44308](https://github.com/anthropics/claude-code/issues/44308) | PreCompact/PostCompact hooks have no visibility into what's being lost | Open | qLine's `obs-precompact.py` and `precompact-preserve.py` fire but cannot see what context is being compacted away. Limits preservation effectiveness. | Hook payload (PreCompact) | Medium |
| [#27361](https://github.com/anthropics/claude-code/issues/27361) | JSONL transcripts missing final message_stop, output token counts unreliable | Closed (stale) | If transcript entries lack `stop_reason` or have unreliable token counts, `obs-stop-cache.py`'s backward scan may miss or misparse entries. | Transcript JSONL | Medium |
| [#27724](https://github.com/anthropics/claude-code/issues/27724) | No public documentation for audit.jsonl / session transcript format | Closed (stale) | Confirms there is no official schema for transcript JSONL entries. qLine's transcript parsing is entirely based on observation. | Transcript JSONL | High (confirms fragility) |
| [#32486](https://github.com/anthropics/claude-code/issues/32486) | `${CLAUDE_PLUGIN_ROOT}` not expanded on Windows | Closed (fixed) | Windows-only, not affecting qLine (macOS primary). Confirms variable expansion is a known surface with past bugs. | Plugin installation | Low |

**Search areas with no direct relevant issues:**
- **Session/transcript resume**: Searched `session transcript resume continue` and `session_id resume stale` — zero results. Session resume behavior is underdocumented but no reported bugs.
- **Hook timeout kills**: Searched `hook timeout kill` — zero results. Timeout termination appears to work as documented with no reported issues.

### 4.3 — Adjacent Pattern Comparison

**Executed 2026-04-07.** Compared three patterns only where they inform T2/T3 design choices.

#### Pattern 1: Event-Driven vs Polling Refresh

**Where used:** tmux status bar (polling), Starship prompt (event-driven), Powerlevel10k (event-driven with cached state).

**How they work:**
- **tmux:** Pure polling with `status-interval` (default 15s). Forks subprocesses on every tick. Event-driven only for pane/window switches and command completion. CPU-intensive at low intervals. No debounce — every tick runs all status scripts.
- **Starship:** Event-driven — `starship prompt` is called by shell hooks at prompt-display time (after each command completes). Uses Rayon parallelism for module evaluation. Configurable per-module timeouts. No periodic polling.
- **Claude Code statusline:** Event-driven — runs "after each new assistant message, when permission mode changes, or vim mode toggles." Debounced at 300ms. In-flight executions cancelled by new triggers. This is closer to Starship than tmux.

**What qLine could learn:**
- qLine already benefits from CC's event-driven architecture. The 300ms debounce is a known quantity.
- **Gap:** No refresh on compaction (issue [#37163](https://github.com/anthropics/claude-code/issues/37163), [#35816](https://github.com/anthropics/claude-code/issues/35816)). Starship's model avoids this because it triggers on every prompt. CC's model misses compaction events because compaction is not a "new assistant message."
- **Applicable to T2:** If T2 proposes caching strategies, cache invalidation should align with event triggers (assistant message, compaction) rather than time-based TTLs that may expire between events.

**Applicability:** Directly applicable to T2 cache TTL design. The 300ms debounce means qLine should not cache with TTLs shorter than 300ms (redundant). The compaction gap means cache should also be invalidated on compaction-adjacent events (PreCompact hook could signal staleness).

#### Pattern 2: Prompt/Status Cache Invalidation

**Where used:** Powerlevel10k instant prompt, Starship module caching, tmux-cpu cache.

**How they work:**
- **Powerlevel10k:** Caches the entire rendered prompt to `~/.cache/p10k-instant-prompt-*.zsh`. Invalidated on next shell launch (not on filesystem events). Known bug: cache files grow unboundedly via append-only writes, degrading performance over time. No time-based expiry — only rewritten on shell init.
- **Starship:** No explicit cache layer — each module runs fresh on every prompt. Performance comes from parallelism and fast Rust implementation, not caching. Timeout-based — modules that exceed their timeout are skipped.
- **tmux-cpu cache example:** Uses file-based cache at `/tmp/tmux-cpu-cache` with `stat`-based age checking (e.g., refresh if file older than N seconds). Simple time-based TTL.
- **qLine:** Uses `/tmp/qline-cache.json` with 60s TTL for system metrics (CPU, memory via `/proc`). Separate from CC-provided data which arrives fresh on every statusline invocation.

**What qLine could learn:**
- Powerlevel10k's append-only cache growth bug is a cautionary tale. qLine's `/tmp/qline-cache.json` is a full rewrite each time (not append), so it avoids this.
- Time-based TTL (60s) for system metrics is appropriate since they change slowly. For CC-provided context data, no TTL is needed — data arrives fresh via stdin on every invocation.
- **Key insight:** qLine's cache serves a different purpose than prompt caches. It caches *expensive local computations* (CPU, memory, disk), not CC data. The CC data pipeline is push-based, not pull-based.

**Applicability:** Moderately applicable to T2. The 60s TTL for system metrics is sound. If T2 proposes caching transcript reads or manifest reads, event-based invalidation (on Stop hook, compaction) is superior to time-based TTL.

#### Pattern 3: Lightweight Telemetry Sidecars

**Where used:** OpenTelemetry OTLP File Exporter, `otel-file-exporter` (PyPI), CloudWatch local agents.

**How they work:**
- **OTLP File Exporter:** Official OTel spec. Preferred file extension: `.jsonl`. Data encoded per OTLP JSON Encoding. Files contain exactly one type: traces, metrics, or logs. Each line is a self-contained record.
- **otel-file-exporter (PyPI):** Lightweight Python implementation. Writes traces/logs/metrics to local JSONL files. No external backends required. Zero-dependency pattern for local dev and CI.
- **qLine's observability:** Uses append-only JSONL for `hook_events.jsonl`, `cache_metrics.jsonl`, `reads.jsonl`, `bash_commands.jsonl`. Structured snapshots for `manifest.json`. Write diffs as individual patch files. Atomic writes with temp-file + rename.

**What qLine could learn:**
- qLine's JSONL sidecar pattern already aligns well with OTel file exporter conventions. The separation by data type (events vs cache metrics vs reads) matches OTel's "one type per file" principle.
- **OTel's schema_version convention:** OTel file exports include a schema URL in each record for forward compatibility. qLine's JSONL files lack a schema version field — adding one would enable forward-compatible parsing if record formats change.
- **Rotation/cleanup:** OTel exporters support file rotation (max size, max age). qLine's JSONL files grow unboundedly within a session — not a problem for typical session lengths but could matter for very long sessions.

**Applicability:** Directly applicable to T3. If T3 proposes new sidecar formats or restructures existing ones, adopting a `schema_version` field in each JSONL record would improve forward compatibility. The existing append-only + temp-file atomic write pattern is solid and should be preserved.

### 4.4 — Supported vs Unsupported Dependency Table

**Executed 2026-04-07. Primary deliverable.**

| Surface | Classification | Evidence | qLine Features Affected | Risk if Surface Changes |
|---------|---------------|----------|------------------------|------------------------|
| stdin JSON `model` field | **Supported** | Documented at [statusline docs](https://code.claude.com/docs/en/statusline): `model.id`, `model.display_name` in available data table and full JSON schema | Model display module (`render_model()`) | Low — field is prominently documented with examples |
| stdin JSON `session_id` | **Supported** | Documented at [statusline docs](https://code.claude.com/docs/en/statusline): "Unique session identifier" in field table | Session package resolution (`_inject_obs_counters`, `_try_obs_snapshot`, runtime map lookup) | Low — field exists. Medium for lifecycle semantics (see UR-03) |
| stdin JSON `context_window.*` | **Supported** | Documented: `context_window_size`, `used_percentage`, `remaining_percentage`, `total_input_tokens`, `total_output_tokens`, `current_usage` all listed with descriptions. `used_percentage` formula explicitly documented. | Context bar (`render_context_bar()`), overhead estimation (`inject_context_overhead()`), token pill display | Low — well-documented with formula. Known issue [#42646](https://github.com/anthropics/claude-code/issues/42646) (post-clear inflation) |
| stdin JSON `cost.*` | **Supported** | Documented: `cost.total_cost_usd`, `cost.total_duration_ms`, `cost.total_api_duration_ms`, `cost.total_lines_added`, `cost.total_lines_removed` | Cost display (`render_cost()`), duration display (`render_duration()`) | Low |
| stdin JSON `workspace.*` | **Supported** | Documented: `workspace.current_dir`, `workspace.project_dir`, `workspace.added_dirs` | Dir display (`render_dir()`), worktree detection | Low |
| stdin JSON `transcript_path` | **Supported** | Documented: "Path to conversation transcript file" | Transcript reading (`_read_transcript_tail()`, `_read_transcript_anchor()`), passed to hooks via common payload | Low — field is stable |
| stdin JSON `version` | **Supported** | Documented in field table | Version display, version-sensitive behavior gating | Low |
| stdin JSON `output_style.name` | **Supported** | Documented in field table | Output style display | Low |
| stdin JSON `worktree` | **Supported** | Documented: `worktree.name`, `worktree.path`, `worktree.branch`, `worktree.original_cwd`, `worktree.original_branch` | Worktree marker in dir display | Low — optional field with documented absence semantics |
| stdin JSON `conversation` (dict) | **Fragile** | NOT in current official documentation. `normalize()` reads this field but it does not appear in the [statusline docs](https://code.claude.com/docs/en/statusline) available data table. May be a legacy field that was renamed/restructured. | Context overhead (if used), overhead estimation | High — undocumented field could be removed without notice |
| stdin JSON `current_usage` (top-level fallback) | **Observed-stable** | `normalize()` reads both `context_window.current_usage` and top-level `current_usage` as fallback. Only `context_window.current_usage` is documented. | Token display fallback path | Medium — fallback path depends on undocumented location |
| Hook `Stop` event common payload | **Supported** | Documented: `session_id`, `transcript_path`, `cwd`, `hook_event_name` in common fields. Stop-specific: common fields only. | `obs-stop-cache.py` uses `session_id` and `transcript_path` to locate and parse transcript | Low for common fields. Note: cache metrics are NOT in the Stop payload — they come from transcript parsing (see next row) |
| Hook `PostToolUse` event payload | **Supported** | Documented: `tool_name`, `tool_input`, `tool_response`, `tool_use_id` | `obs-posttool-write.py`, `obs-posttool-bash.py`, `obs-posttool-edit.py` — tool tracking | Low — well-documented payload |
| Hook `PreToolUse` event payload | **Supported** | Documented: `tool_name`, `tool_input`, `tool_use_id` | `obs-pretool-read.py` — file read tracking | Low |
| Hook `SessionStart` event payload | **Supported** | Documented: `source` ("startup\|resume\|clear\|compact"), `model` | `obs-session-start.py` — session package creation, reentry detection | Low |
| Hook `PreCompact` event payload | **Supported** | Listed as supported event. Payload: common fields. | `obs-precompact.py`, `precompact-preserve.py` | Medium — issue [#44308](https://github.com/anthropics/claude-code/issues/44308) notes no visibility into what's being lost |
| Hook `SubagentStop` event payload | **Supported** | Documented: `agent_id`, `agent_type`, `agent_transcript_path`, `last_assistant_message` | `obs-subagent-stop.py` | Low |
| Transcript JSONL internal schema | **Fragile** | NOT documented (confirmed by closed [#27724](https://github.com/anthropics/claude-code/issues/27724)). qLine parses: entry `type`, `message.id`, `stop_reason`, `usage.cache_creation_input_tokens`, `usage.cache_read_input_tokens`, `usage.input_tokens`. Issue [#27361](https://github.com/anthropics/claude-code/issues/27361) reports missing `message_stop` events. | `obs-stop-cache.py` backward scan, `_read_transcript_tail()`, `_read_transcript_anchor()` in `context_overhead.py` | High — undocumented internal format; any restructuring breaks cache metrics and anchor derivation |
| Transcript file location | **Supported** | `transcript_path` is provided by CC in both statusline stdin JSON and hook common payload. qLine does not guess the path — it receives it. | `_read_transcript_tail()` path resolution | Low — CC provides the path directly |
| Session ID stability on resume | **Speculative** | Not documented whether `session_id` persists on `--resume`. SessionStart `source` field includes "resume" as a value, implying same session context, but session_id behavior on resume is not specified. Never validated across CC versions. | Package reuse (`resolve_package_root()`), stale state avoidance, runtime map lookup | High — if session_id changes on resume, runtime map breaks |
| `cache_creation_input_tokens` in `current_usage` | **Supported** | Documented at [statusline docs](https://code.claude.com/docs/en/statusline): "tokens written to cache" in current_usage. Standard Anthropic API field. | Cache health computation in `context_overhead.py`, cache delta display | Low |
| `cache_read_input_tokens` in `current_usage` | **Supported** | Documented at [statusline docs](https://code.claude.com/docs/en/statusline): "tokens read from cache" in current_usage. | Cache health computation | Low. Known issue [#24147](https://github.com/anthropics/claude-code/issues/24147) (cache read inflation) |
| Context window `context_window_size` | **Supported** | Documented: "200000 by default, or 1000000 for models with extended context" | Context bar denominator | Low |
| CC internal constants (output reserve, compaction buffer, etc.) | **Speculative** | Extracted from decompiled CC v2.1.92 source. Constants: `CC_OUTPUT_RESERVE=20000`, `CC_AUTOCOMPACT_BUFFER=13000`, `CC_WARNING_OFFSET=20000`, `CC_ERROR_OFFSET=20000`, `CC_BLOCKING_BUFFER=3000`. NOT documented anywhere. Issue [#17959](https://github.com/anthropics/claude-code/issues/17959) confirms `used_percentage` differs from internal warning formula. | `context_overhead.py` lines 55-59: overhead estimation, effective window calculation | High — any CC update can change these; they are implementation details |
| Plugin `hooks.json` schema | **Supported** | Documented at [plugins reference](https://code.claude.com/docs/en/plugins-reference): `{"hooks": {...}}` wrapper, event names, matcher, hook types, timeout field | Hook registration in `hooks/hooks.json` | Low |
| `${CLAUDE_PLUGIN_ROOT}` expansion | **Supported** | Documented at [plugins reference](https://code.claude.com/docs/en/plugins-reference): "substituted inline anywhere they appear in hook commands" and "exported as environment variables to hook processes" | All 16 hook command paths in `hooks/hooks.json` | Low — documented, past Windows bug [#32486](https://github.com/anthropics/claude-code/issues/32486) fixed |
| Hook `Stop` reliability (always fires) | **Fragile** | Issues [#29881](https://github.com/anthropics/claude-code/issues/29881) (not fired on stall), [#33712](https://github.com/anthropics/claude-code/issues/33712) (not fired with newlines), [#40029](https://github.com/anthropics/claude-code/issues/40029) (not fired in VSCode). Multiple platforms affected. | `obs-stop-cache.py` depends on Stop firing to capture cache metrics | High — if Stop doesn't fire, entire cache metric pipeline for that turn is lost |
| Statusline refresh on compaction | **Fragile** | Issues [#37163](https://github.com/anthropics/claude-code/issues/37163), [#35816](https://github.com/anthropics/claude-code/issues/35816): statusline does NOT refresh after compaction. | Context bar shows stale pre-compaction data until next assistant message | Medium — misleading display but self-corrects on next turn |

**Classification summary:**
- **Supported (17):** model, session_id, context_window.*, cost.*, workspace.*, transcript_path, version, output_style, worktree, hook payloads (Stop/PostToolUse/PreToolUse/SessionStart/PreCompact/SubagentStop), cache token fields, context_window_size, hooks.json schema, `${CLAUDE_PLUGIN_ROOT}`
- **Observed-stable (1):** top-level `current_usage` fallback
- **Fragile (4):** `conversation` dict field, transcript JSONL internal schema, Stop hook reliability, statusline post-compaction refresh
- **Speculative (2):** session_id stability on resume, CC internal constants

### 4.5 — Upstream Risk Register

**Executed 2026-04-07.** One entry per fragile or speculative dependency.

| ID | Surface | Classification | Risk Description | Likelihood | Impact | Mitigation Options |
|----|---------|---------------|-----------------|------------|--------|-------------------|
| UR-01 | Transcript JSONL internal schema | Fragile | Anthropic may restructure transcript entry fields (`type`, `message.id`, `stop_reason`, `usage.*`) without notice, since no public schema exists ([#27724](https://github.com/anthropics/claude-code/issues/27724) confirmed). Past issue [#27361](https://github.com/anthropics/claude-code/issues/27361) showed missing `message_stop` events. Any change breaks `obs-stop-cache.py` backward scan and `_read_transcript_anchor()` in `context_overhead.py`. | High | High | (a) Wrap all transcript field access in try/except with graceful degradation. (b) Version-tag transcript parsing logic so qLine can ship multiple parsers. (c) Reduce transcript dependency by sourcing cache metrics from `current_usage` in statusline stdin JSON instead. (d) Add transcript schema validation in test suite to detect breakage early. |
| UR-02 | CC internal constants | Speculative | Constants extracted from decompiled CC v2.1.92 source (`CC_OUTPUT_RESERVE`, `CC_AUTOCOMPACT_BUFFER`, `CC_WARNING_OFFSET`, etc.) can change in any CC update. Issue [#17959](https://github.com/anthropics/claude-code/issues/17959) confirms internal warning formula differs from `used_percentage`. | High | Medium | (a) Replace speculative constants with observational calibration from real sessions (T1's approach). (b) Make constants user-configurable in `qline.toml`. (c) Derive effective thresholds from behavior (observe when compaction actually fires) rather than hardcoding assumed values. (d) Gate constants behind CC version check and maintain a version map. |
| UR-03 | Session ID stability on resume | Speculative | No documentation specifies whether `session_id` persists when user does `--resume`, `--continue`, or `/clear`. If session_id changes on resume, `resolve_package_root()` returns a stale package and runtime map (`~/.claude/observability/runtime/<sid>.json`) lookup fails silently. | Medium | High | (a) `obs-session-start.py` already handles `source: "resume"` — verify it creates/updates runtime map correctly. (b) Add defensive lookup: if runtime map miss, scan recent session packages. (c) Test resume behavior explicitly by observing session_id across resume operations. |
| UR-04 | `conversation` dict in stdin JSON | Fragile | The `conversation` field is read by `normalize()` but does NOT appear in official [statusline docs](https://code.claude.com/docs/en/statusline). It may be a legacy field that was renamed, restructured, or removed. Any code path depending on it has no upstream guarantee. | High | Medium | (a) Audit `normalize()` to determine what `conversation` fields are actually consumed and whether equivalent data is available from documented fields. (b) Remove dependency if documented alternatives exist (e.g., `context_window.*` provides context data). (c) Add graceful degradation if field is absent. |
| UR-05 | Stop hook reliability | Fragile | Multiple open issues report Stop hook not firing: stall mid-turn ([#29881](https://github.com/anthropics/claude-code/issues/29881)), newlines in response ([#33712](https://github.com/anthropics/claude-code/issues/33712)), VSCode ([#40029](https://github.com/anthropics/claude-code/issues/40029)). When Stop doesn't fire, `obs-stop-cache.py` never runs, and cache metrics for that turn are lost. | Medium | High | (a) Do not rely solely on Stop hook for cache metrics — also derive from `current_usage` in statusline stdin (which is always available). (b) Add staleness detection: if statusline sees new turns without corresponding cache events, log a warning. (c) Accept that Stop may occasionally not fire and design cache health to degrade gracefully (interpolate from last-known metrics). |
| UR-06 | Statusline post-compaction refresh | Fragile | Statusline does not refresh after `/compact` or auto-compact (issues [#37163](https://github.com/anthropics/claude-code/issues/37163), [#35816](https://github.com/anthropics/claude-code/issues/35816)). Context bar shows stale pre-compaction data until next assistant message. | High | Medium | (a) Use `PreCompact` or `PostCompact` hook to write a staleness marker that the next statusline invocation detects. (b) When stale marker exists, show a visual indicator (e.g., dimmed bar, "stale" suffix). (c) Accept the gap — it self-corrects on the next turn. |
| UR-07 | Top-level `current_usage` fallback | Observed-stable | `normalize()` reads `current_usage` from both `context_window.current_usage` (documented) and top-level (undocumented). If the undocumented location is removed, the fallback path breaks. | Low | Low | (a) Prefer the documented `context_window.current_usage` path. (b) The fallback is already a fallback — if removed, the documented path still works. (c) Remove the undocumented fallback in a future cleanup if confirmed unnecessary. |

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

- [x] Documentation audit table filled for all 12 surfaces with yes/no/partial and source references — **12 surfaces audited, 7 fully documented, 3 partial, 0 complete gaps**
- [x] Public issue scan covers all 5 search areas with relevant issues documented — **18 relevant issues catalogued across all 5 areas; 2 areas had no direct hits (noted with search terms)**
- [x] Adjacent pattern comparison limited to 3 patterns with explicit applicability judgment — **3 patterns compared: event-driven refresh, cache invalidation, telemetry sidecars**
- [x] Supported-vs-unsupported table classifies all surfaces identified in Task 4.1 and any additional discovered during the scan — **24 surfaces classified: 17 supported, 1 observed-stable, 4 fragile, 2 speculative**
- [x] Upstream risk register populated for all fragile/speculative dependencies — **7 risks registered (UR-01 through UR-07) covering all 6 fragile+speculative surfaces**
- [x] Every classification backed by evidence (doc link, issue number, or version comparison)
- [x] No speculative claims presented as fact — uncertainty is explicit

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
