# qLine Module Reference

Reference for the 37 modules in the default 3-line layout, plus optional modules available via config.

Most modules return `None` when their data is absent or zero, hiding themselves. Exceptions: `obs_health` shows a dim placeholder when health is unknown but a session exists; `cpu`, `memory`, and `disk` render whenever their data fields are present, including at 0%.

## Configuration

Modules that have a section in `DEFAULT_THEME` (most obs modules, cost, duration, git, cpu, memory, disk, agents, tmux) can be toggled and customized via `~/.config/qline.toml`. Modules without their own theme section (`token_counts`, `token_out_counts`, `cache_rate`, `sys_overhead_pill`, `cache_read`, `cache_delta`, `turns`) inherit from the `tokens` or parent theme sections and cannot be individually toggled via config — they are always on when present in the layout.

```toml
# ~/.config/qline.toml

[layout]
show_labels = false    # prepend text labels to modules that have a "label" key
max_width = 120        # terminal width for line wrapping (default 120)
max_lines = 3          # CC status bar line limit

# Per-module toggle (only works for modules with their own theme section):
[obs_failures]
enabled = true         # false to hide

# Per-module label override:
[obs_bash]
label = "sh"           # custom label (when show_labels = true)
```

Labels only apply to modules that have a `"label"` key in their theme section. Modules without a theme section (like `token_counts`) are not labeled.

---

## Line 1 — Session Identity & Context Health

| Module | Glyph | Example | Source | Calculation |
|--------|-------|---------|--------|-------------|
| `model` | 󰚩 | `Opus4.6[1M]` | `payload.model.display_name` or `payload.model` (string) | Strips "Claude " prefix, compacts spaces, appends `[{size}]` from `context_window_size` |
| `token_counts` | ▲ | `▲71.4k` | `context_window.total_input_tokens` | Abbreviated count (1234→1.2k, 12345→12.3k, 1234567→1.2M) |
| `token_out_counts` | ▼ | `▼484k` | `context_window.total_output_tokens` | Same abbreviation |
| `context_bar` | 󰋑 | `██▓▓▓▓▓▓░░░░░󰋑79%` | `context_window.used_percentage`, `sys_overhead_tokens` (from transcript) | Dual-fill bar: █=system overhead, ▓=conversation, ░=free. Width auto-sizes to `max_width - 55`. Percentage shows CC's raw `used_percentage`. Severity: warn at 80% of autocompact threshold, critical at threshold. |
| `cache_rate` | 󰓅 | `󰓅99%` | Transcript analysis (trailing turn window) | Exponential-decay weighted cache hit rate: `cache_read / (cache_read + cache_create)` across recent turns. Decay factor 0.7, newest turn weighted 1.0. |
| `duration` | 󰥔 | `󰥔3h30m` | `cost.total_duration_ms` or top-level `duration_ms` | Compact format: drops leading 0h, no spaces. `45s`, `2m30s`, `1h15m`, `3h30m`. |

### Context Bar Alert System

When an alert condition is detected, the bar's inline glyph flashes and a full-text banner replaces lines 2-3 for 5 seconds (onset tracked in `/tmp/qline-alert.json` with session_id isolation). After 5s, the banner collapses to the inline glyph.

| Priority | Key | Trigger | Severity |
|----------|-----|---------|----------|
| 1 | bust | `cache_busting == True` (hit rate < 0.3 for 3+ turns) | Critical |
| 2 | expired | Cache idle timeout (full rebuild detected) | Warning |
| 3 | micro | `microcompact_suspected == True` (drop ratio < 0.5, abs drop > 5000) | Warning |
| 4 | bloat | System overhead ≥ 50% of context window | Critical |
| 5 | heavy | CC raw `used_percentage` ≥ autocompact threshold | Critical |
| 6 | compact | `turns_until_compact` ≤ 10 | Critical |
| 7 | turns | `turns_until_compact` ≤ 50 | Warning |
| 8 | degraded | `cache_degraded == True` (hit rate < 0.8 but not busting) | Warning |

---

## Line 2 — Overhead, Observability & Metrics

### Cache & Overhead Group

| Module | Glyph | Example | Source | Calculation |
|--------|-------|---------|--------|-------------|
| `sys_overhead_pill` | 󰑖 | `󰑖17.1k™` | Transcript first-turn `cache_creation_input_tokens` | System overhead = first turn's cache creation (the prompt + CLAUDE.md + tools). `™` suffix = token marker. `≈` suffix when estimated (no transcript yet). |
| `cache_read` | © | `©307k™` | Transcript latest turn `cache_read_input_tokens` | Last turn's cache read — how many tokens were served from cache. |
| `cache_delta` | 󰍻 | `󰍻 +454™` | Transcript latest turn `cache_creation_input_tokens` | Last turn's cache creation delta — new tokens added to cache. Spike coloring: >5000 red, >1000 yellow. |
| `turns` | 󰐕 | `󰐕475` | `inject_context_overhead` → `session_turn_count` | Incremented each invocation. Counts completed API turns in this session. |

### Observability Counters

Sources vary per module. Most are from `hook_events.jsonl` but reads, health, and faults come from different files. All cached with 5-second TTL in `/tmp/qline-cache.json`.

| Module | Glyph | Label | Source File | Event/Key | What It Counts |
|--------|-------|-------|-------------|-----------|----------------|
| `obs_reads` | 󰑇 | reads | `custom/reads.jsonl` | Line count | Total file read operations |
| `obs_rereads` | ® | reread | `custom/reads.jsonl` | Lines with `is_reread: true` | Re-read percentage: `reread_count / total_reads * 100`. Warn at 30%, critical at 50%. |
| `obs_writes` | 󰙏 | writes | `metadata/hook_events.jsonl` | `file.write.diff` | File write/edit operations |
| `obs_bash` | 󰆍 | bash | `metadata/hook_events.jsonl` | `bash.executed` | Shell command executions |
| `obs_failures` | 󰀩 | fails | `metadata/hook_events.jsonl` | `tool.failed` | Tool use failures (PostToolUseFailure events). Warn at 1, critical at 5. Disabled by default. |
| `obs_prompts` | 󰅺 | prompts | `metadata/hook_events.jsonl` | `prompt.observed` | User prompt submissions |
| `obs_tasks` | 󰌘 | tasks | `metadata/hook_events.jsonl` | `task.completed` | Task completions |
| `obs_subagents` | 󰀦 | agents | `metadata/hook_events.jsonl` | `subagent.stopped` | Subagent completions |
| `obs_health` | 󰕥 | health | `manifest.json` | `health.overall` | Obs subsystem health: healthy (green), degraded (yellow), failed (red). Glyph-only when healthy. Shows dim placeholder `󰕥 ―` when health is unknown but session exists. |
| `obs_compactions` | 󰔠 | compact | `metadata/hook_events.jsonl` | `compact.started` | Context compaction count. Prefix `x`. Hidden when 0. |
| `obs_hook_faults` | 󰀩 | faults | `~/.claude/logs/lifecycle-hook-faults.jsonl` | `level == "fault"` within last hour | Hook crashes. 32KB reverse scan with timestamp filter. Warn at 1, critical at 5. |

### Session Metrics

| Module | Glyph | Label | Example | Source | Calculation |
|--------|-------|-------|---------|--------|-------------|
| `lines_changed` | — | lines | `+2.5k/-800` | `cost.total_lines_added`, `cost.total_lines_removed` | Abbreviated add/remove counts joined by `/` |
| `session_count` | # | sess | `#91` | Scan of `~/.claude/observability/sessions/{today}/` | Count of session directories containing snapshot files. Cached 60s. |
| `daily_cost` | 󰃭 | today | `󰃭$226` | Scan of last snapshot line per session for today | Sum of `cost_usd` from last snapshot of each today's session. Warn at $200, critical at $400. Cached 60s. |
| `weekly_cost` | — | week | `$764/wk` | Same scan, filtered to current week (Mon-Sun) | Sum across all days since Monday. Warn at $1000, critical at $2000. |
| `api_efficiency` | ⏱ | api% | `⏱53%` | `cost.total_api_duration_ms` / `cost.total_duration_ms` | Percentage of wall clock time spent on API calls. Capped at 100%. |
| `cost_per_ktok` | — | $/kt | `$/k0.16` | `cost_usd` / (`output_tokens` / 1000) | Cost efficiency per 1k output tokens. 3 decimal places when < $0.01. |
| `io_ratio` | — | io | `io:0.7x` | `output_tokens` / `input_tokens` | Output-to-input token ratio. >1.0x = verbose output, <1.0x = input-heavy. |
| `tokens_per_turn` | — | t/turn | `tok/t60.5k` | `output_tokens` / `session_turn_count` | Average output tokens generated per turn. |
| `free_context` | ▼ | free | `▼116kfree` | `context_total` - `context_used_corrected` | Remaining context budget. Hidden when ≤ 0. |
| `growth_rate` | — | grow | `gro:489/t` | `inject_context_overhead` → `context_growth_per_turn` | Average context growth per turn from trailing window. Positive deltas only. |
| `cost` | $ | cost | `$68.37\|19.47/hr` | `cost.total_cost_usd`, `cost.total_duration_ms` | Total session cost + hourly rate. Pipe separator before rate. Warn at $2, critical at $5. |

---

## Line 3 — System & Environment

| Module | Glyph | Label | Example | Source | Calculation |
|--------|-------|-------|---------|--------|-------------|
| `dir` | 󰝰 | dir | `󰝰 qLine` | `workspace.current_dir` or `cwd` | Basename of working directory. `⊛` marker when in git worktree. Dims when git data is stale. |
| `git` | 󰘬 | git | `main@30edbac*` | `git rev-parse`, `git status` | Branch@SHA with `*` dirty marker. Truncated to 20 chars in compact mode. |
| `cpu` | 󰓌 | cpu | `󰓌 ░░░░░7%` | `/proc/loadavg` (Linux) or `sysctl` (macOS) | 5-bar mini-graph + percentage. Renders at any value including 0%. Warn at 60%, critical at 85%. |
| `memory` | 󰍛 | mem | `󰍛 ██░░░55%` | `/proc/meminfo` (Linux) or `vm_stat` (macOS) | 5-bar mini-graph + percentage. Renders at any value including 0%. Warn at 70%, critical at 90%. |
| `disk` | 󰋊 | disk | `󰋊 █░░░░24%` | `os.statvfs("/")` | 5-bar mini-graph + percentage. Renders at any value including 0%. Warn at 80%, critical at 95%. |

### Overflow

When line 2 has more modules than fit within `max_width`, overflow modules are appended to line 3 after the system metrics, separated by `│`.

---

## Optional Modules (not in default layout)

These are registered in `MODULE_RENDERERS` but not in `DEFAULT_LINE1/2/3`. Add them to a layout line in config to activate.

| Module | What | Config |
|--------|------|--------|
| `agents` | Running Codex/agent instance count | `[agents] enabled = true`. Disabled by default. |
| `tmux` | Tmux session/pane count | `[tmux] enabled = true`. Disabled by default. |
| `turns_pill` | Turns-until-compact countdown (vs `turns` which shows session turn count) | Replace `turns` with `turns_pill` in layout. |
| `tokens` | Legacy combined token pill (replaced by `token_counts` + `token_out_counts`) | Stub, returns None. |
| `sys_overhead` | Legacy overhead renderer (replaced by `sys_overhead_pill`) | Stub, returns None. |
| `cache_pill` | Legacy combined cache (replaced by `cache_read` + `cache_delta`) | Stub, returns None. |
| `token_in` / `token_out` | Legacy token aliases (delegate to `token_counts` / `token_out_counts`) | For old config compat. |
| `cache_writes` | Alias for `cache_delta` | For old config compat. |

---

## Data Flow

```
CC stdin (JSON) ──→ normalize() ──→ state dict
                                      │
                    collect_system_data ──→ cpu/mem/disk/git
                    _inject_obs_counters ──→ obs events + faults + costs
                    inject_context_overhead ──→ overhead/cache/turns/growth
                                      │
                                      ▼
                              render(state, theme)
                                      │
                    ┌─────────────────┼──────────────────┐
                  line1             line2               line3
              render_wrapped   render_line2_piped   render_wrapped
                    │           (width-aware,        (+ overflow)
                    │            overflow→line3)
                    ▼
               3-line output ──→ CC status bar
```

### Caching

| Data | TTL | Storage |
|------|-----|---------|
| Obs event counts, reads, health | 5s | `/tmp/qline-cache.json` → `_obs.{session_id}` |
| Hook fault count, parse errors | 5s | Same cache, `last_fault_ts` gate |
| Daily/weekly cost, session count | 60s | Same cache, `last_cost_scan_ts` gate |
| Context overhead, cache metrics | 5s | Same cache, `overhead_ts` gate |
| System collectors (cpu/mem/disk/git) | 60s (`CACHE_MAX_AGE_S`) | Same cache, per-module timestamps |
| Alert onset | Persistent | `/tmp/qline-alert.json` (session_id isolated) |

### Error Handling

System collectors (`collect_system_data`) wrap each collector in `try/except Exception`. On exception, stale cached values are applied if within the 60s TTL. However, collectors that return early without data (e.g., missing `/proc/loadavg` on macOS) do not raise — they leave state empty, and the module hides. This means a collector that silently fails will cause its module to disappear rather than show stale data.

The obs injection (`_inject_obs_counters`), overhead injection (`inject_context_overhead`), and snapshot writer (`_try_obs_snapshot`) each have top-level `try/except Exception: pass` wrappers. Individual sub-operations (file reads, JSON parsing, cache writes) also swallow exceptions. The statusline will never crash CC — but individual modules may disappear if their data source becomes unreadable.
