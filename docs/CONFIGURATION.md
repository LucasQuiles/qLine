# Configuration Reference

Everything here is optional. qLine works fine without a config file. But if you want to tinker — and honestly, who doesn't — here's every knob you can turn.

## Config file location

```
~/.config/qline.toml
```

Create it from the example in the repo:
```bash
cp qline.example.toml ~/.config/qline.toml
```

### TOML support by Python version

| Python | What happens |
|---|---|
| 3.11+ | Built-in `tomllib`. Just works. |
| 3.10 + `tomli` | `pip install tomli`. Just works. |
| 3.10 without `tomli` | Config file is silently ignored. Defaults used. |
| 3.9 and below | Not supported at all. |

If qLine can't parse your config (wrong path, syntax error, missing library), it falls back to defaults. No crash, no error, just defaults. You can validate your TOML with:

```bash
python3 -c "import tomllib; tomllib.load(open('$HOME/.config/qline.toml','rb'))"
```

---

## `[layout]` — Global settings

```toml
[layout]
force_single_line = true     # merge all layout lines into one
max_width = 200              # auto-wrap threshold in visible characters
display_mode = "both"        # "icon" | "text" | "both"
line1 = ["model", "dir", "context_bar", "cost", "duration"]
line2 = ["cpu", "memory", "disk", "agents", "tmux"]
line3 = ["obs_reads", "obs_rereads", "obs_writes", "obs_bash",
         "obs_prompts", "obs_tasks", "obs_subagents",
         "obs_failures", "obs_compactions", "obs_health"]
```

| Key | Type | Default | What it does |
|---|---|---|---|
| `force_single_line` | bool | `true` | Merge all `lineN` arrays into one stream. Claude Code reads only the first line of stdout, so this should probably stay `true`. |
| `max_width` | int | `200` | Auto-wrap long lines at this many visible characters. Set lower if your terminal is narrow. |
| `display_mode` | string | `"both"` | Global default for label rendering. Modules can override this individually. |
| `line1` ... `line5` | array | (see above) | Module names in render order. Up to 5 lines. A module must appear in a line to render, even if `enabled = true`. |

### Display mode values

| Value | Renders as | Notes |
|---|---|---|
| `"both"` | `󰚩 Claude 3` | Icon + text label. Default. Most readable. |
| `"icon"` | `󰚩 3` | Icon + value only. Compact. |
| `"text"` | `Claude 3` | Text only. No Nerd Font needed. |

---

## `[separator]` — Module separator

```toml
[separator]
char = "│"       # the character between modules
dim = true       # render it dimmed
```

---

## `[pill]` — Pill styling

```toml
[pill]
left = ""        # left cap character (e.g., "" for rounded)
right = ""       # right cap character (e.g., "" for rounded)
```

When both `left` and `right` are set, modules render with colored end caps for a rounded pill look. Leave empty for flat styling.

---

## Core modules

### `[model]`

| Key | Default | What |
|---|---|---|
| `enabled` | `true` | |
| `glyph` | `"󰚩 "` | nf-md-robot |
| `color` | `"#d8dee9"` | |
| `bg` | `"#3b4252"` | |
| `bold` | `false` | Bold text |

Shows the model name (e.g., `Op4.6`, `Sonnet`). Also shows output style if non-default (e.g., `Op4.6:verbose`).

### `[dir]`

| Key | Default | What |
|---|---|---|
| `enabled` | `true` | |
| `glyph` | `"󰝰 "` | nf-md-folder_open |
| `color` | `"#9bb8d3"` | |
| `bg` | `"#2e3440"` | |
| `worktree_marker` | `"⊛"` | Shown when running in a git worktree |

Shows directory basename, git branch + short SHA, dirty marker (`*`), worktree marker, and added dirs count (e.g., `+2dir`).

### `[context_bar]`

| Key | Default | What |
|---|---|---|
| `enabled` | `true` | |
| `glyph` | `"󰋑 "` | nf-md-heart |
| `color` | `"#b5d4a0"` | Normal color |
| `bg` | `"#2e3440"` | |
| `width` | `10` | Progress bar character width |
| `warn_threshold` | `40.0` | % context used → warn color |
| `warn_color` | `"#f0d399"` | |
| `critical_threshold` | `70.0` | % context used → critical color |
| `critical_color` | `"#d06070"` | |

Shows token I/O (`↑50k↓20k`), a progress bar, and percentage.

### `[cost]`

| Key | Default | What |
|---|---|---|
| `enabled` | `true` | |
| `glyph` | `"$"` | |
| `color` | `"#e0956a"` | |
| `bg` | `"#2e3440"` | |
| `warn_threshold` | `2.0` | USD → warn |
| `critical_threshold` | `5.0` | USD → critical |

Formats cost with smart precision: sub-cent shows `0.3¢`, normal shows `$1.50`, over $100 shows whole dollars. Also shows `$/hr` rate after 60 seconds.

### `[duration]`

| Key | Default | What |
|---|---|---|
| `enabled` | `true` | |
| `glyph` | `"󰥔 "` | nf-md-clock_outline |
| `color` | `"#8eacb8"` | |
| `bg` | `"#2e3440"` | |
| `format` | `"auto"` | `auto` / `hm` / `m` / `hms` |

---

## System modules

### `[cpu]`, `[memory]`, `[disk]`

All three share the same config shape:

| Key | CPU default | Memory default | Disk default | What |
|---|---|---|---|---|
| `enabled` | `true` | `true` | `true` | |
| `glyph` | `"󰓌 "` | `"󰍛 "` | `"󰋊 "` | |
| `color` | `"#a8d4d0"` | `"#a8d4d0"` | `"#a8d4d0"` | |
| `width` | `5` | `5` | `5` | Bar width in characters |
| `warn_threshold` | `60.0` | `70.0` | `80.0` | % → warn |
| `critical_threshold` | `85.0` | `90.0` | `95.0` | % → critical |
| `show_threshold` | `0` | `0` | `0` | Hide below this % |

Disk also has:
| Key | Default | What |
|---|---|---|
| `path` | `"/"` | Which filesystem to check |

**Platform behavior:**
- **Linux:** CPU from `/proc/stat`, memory from `/proc/meminfo`
- **macOS:** CPU from `sysctl vm.loadavg`, memory from `vm_stat`
- **Disk:** `os.statvfs` everywhere

### `[git]`

| Key | Default | What |
|---|---|---|
| `enabled` | `true` | |
| `dirty_marker` | `"*"` | Appended to branch name when working tree is dirty |

Git info is merged into the `dir` pill (not rendered as a separate module).

---

## `[agents]` — Process detection

| Key | Default | What |
|---|---|---|
| `enabled` | `true` | |
| `glyph` | `"󰚩 "` | Claude main icon |
| `sub_glyph` | `"󰜗 "` | Sub-agent icon |
| `codex_glyph` | `"󰄷 "` | Codex icon |
| `label` | `"Claude"` | Text label for claude main |
| `sub_label` | `"Sub"` | Text label for sub-agents |
| `codex_label` | `"Codex"` | Text label for codex |
| `color` | `"#b48ead"` | |
| `bg` | `"#2e3440"` | |
| `show_breakdown` | `true` | `false` = single total count |
| `inner_separator` | `" │ "` | Between breakdown segments |
| `display_mode` | `""` | `""` = use global; or `"icon"` / `"text"` / `"both"` |
| `warn_threshold` | `5` | Total count → warn |
| `critical_threshold` | `8` | Total count → critical |
| `show_threshold` | `0` | Hide below this count |

Uses a single `ps -eo pid=,ppid=,comm=` call to classify processes by parent-child relationships. See the README's [agent detection section](../README.md#agent-detection) for details.

---

## `[tmux]`

| Key | Default | What |
|---|---|---|
| `enabled` | `false` | Off by default |
| `glyph` | `"tmux "` | |
| `color` | `"#8eacb8"` | |
| `bg` | `"#2e3440"` | |

Shows `tmux 3s/12p` (3 sessions, 12 panes).

---

## Observability modules

All disabled by default. All share the same basic config shape:

| Key | Default | What |
|---|---|---|
| `enabled` | `false` | |
| `glyph` | (varies) | |
| `color` | (varies) | |
| `bg` | `"#2e3440"` | |

Modules with thresholds also have `warn_threshold`, `critical_threshold`, `warn_color`, `critical_color`.

| Module | Glyph | Tracks | Extra config |
|---|---|---|---|
| `obs_reads` | `"󰑇 "` | File read count | — |
| `obs_rereads` | `"󰓦 "` | Reread percentage | warn 30, critical 50 |
| `obs_writes` | `"󰙏 "` | File write count | — |
| `obs_bash` | `"󰆍 "` | Bash command count | — |
| `obs_prompts` | `"󰅺 "` | User prompt count | — |
| `obs_tasks` | `"󰄷 "` | Completed task count | — |
| `obs_subagents` | `"󰓁 "` | Subagent spawn count (historical) | — |
| `obs_failures` | `"󰀩 "` | Tool failure count | warn 1, critical 5 |
| `obs_compactions` | `"󱃧 "` | Context compaction count | — |
| `obs_health` | `"󰕥 "` | Session health badge | `degraded_color`, `failed_color` |

`obs_health` shows a colored shield icon: green for healthy, yellow for degraded, red for failed/incomplete.

---

## Environment variables

These are mostly for testing and debugging:

| Variable | What it does |
|---|---|
| `NO_COLOR=1` | Disables all ANSI color output |
| `QLINE_NO_COLLECT=1` | Skips all system data collection (git, cpu, memory, disk, agents, tmux) |
| `QLINE_PROC_DIR` | Override `/proc` path (for testing Linux collectors on other systems) |
| `QLINE_CACHE_PATH` | Override cache file path (default: `/tmp/qline-cache.json`) |
| `OBS_ROOT` | Override observability data root directory |
