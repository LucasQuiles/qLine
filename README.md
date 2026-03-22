# qLine

A styled status-line renderer for [Claude Code](https://docs.anthropic.com/en/docs/build-with-claude/computer-use). Reads Claude's status JSON from stdin, emits a styled single-line output with ANSI truecolor, Nerd Font glyphs, and TOML-configurable theming.

```
 󰚩 Op4.6 │ 󰝰 myproject main@a3f │ ↑281k↓141k 󰋑 █░░░░░░░░░ 15% │ $0.42 │ 󰥔 1m30s │ 󰓌 ██░░░ 22% │ 󰍛 ██░░░ 35%
```

## Requirements

| Requirement | Notes |
|---|---|
| Python 3.10+ | 3.11+ recommended. 3.10 works but TOML config requires `pip install tomli` |
| Nerd Font | Install on the **client terminal**, not the server. Any Nerd Font works |
| Linux | System metrics use `/proc`. macOS gracefully degrades (no CPU/memory/disk bars) |
| Claude Code | The `statusLine` command hook that invokes qLine |

## Install

```bash
git clone https://github.com/LucasQuiles/qLine.git
cd qLine
./install.sh
```

The installer:
- Copies `statusline.py` and `obs_utils.py` to `~/.claude/`
- Detects your Python version and adjusts the shebang if needed
- Backs up `settings.json` before patching it
- Warns if `jq` is missing (needed for settings.json patching)
- Prints post-install instructions

**Nerd Font setup** (install on your local machine, not the server):
```bash
# macOS
brew install --cask font-ubuntu-sans-mono-nerd-font

# Linux
# Download from https://github.com/ryanoasis/nerd-fonts/releases
# Extract to ~/.local/share/fonts/ and run fc-cache -fv
```

Set your terminal font to any **Nerd Font Mono** variant.

**Manual install** (if you prefer not to run the script):
```bash
cp src/statusline.py ~/.claude/statusline.py
cp src/obs_utils.py ~/.claude/obs_utils.py
chmod +x ~/.claude/statusline.py
```
Then add to `~/.claude/settings.json`:
```json
{
  "statusLine": {
    "type": "command",
    "command": "/home/YOU/.claude/statusline.py"
  }
}
```

## Modules

### Core (enabled by default)

| Module | Glyph | Shows | Config Key |
|---|---|---|---|
| `model` | 󰚩 | Model name (e.g., `Op4.6`) | `[model]` |
| `dir` | 󰝰 | Project directory + git info | `[dir]` |
| `context_bar` | 󰋑 | Token counts + context usage bar | `[context_bar]` |
| `cost` | `$` | Session cost in USD | `[cost]` |
| `duration` | 󰥔 | Session duration | `[duration]` |

### System (enabled by default)

| Module | Glyph | Shows | Config Key |
|---|---|---|---|
| `cpu` | 󰓌 | CPU usage bar (Linux `/proc`) | `[cpu]` |
| `memory` | 󰍛 | Memory usage bar (Linux `/proc`) | `[memory]` |
| `disk` | 󰋊 | Disk usage bar | `[disk]` |
| `git` | 󰊢 | Branch, SHA, dirty state | `[git]` |

### Utility (disabled by default)

| Module | Glyph | Shows | Config Key |
|---|---|---|---|
| `agents` | 󰓌 | Active Claude agent count | `[agents]` |
| `tmux` | tmux | tmux session/pane count | `[tmux]` |

### Observability (disabled by default)

These modules read session event data from the observability package. They require the hooks infrastructure (`obs_utils.py` + session hooks in `~/.claude/hooks/`). Enable them in `~/.config/qline.toml`.

| Module | Glyph | Shows | Config Key |
|---|---|---|---|
| `obs_reads` | 󰑇 | File read count | `[obs_reads]` |
| `obs_rereads` | 󰓦 | Reread percentage | `[obs_rereads]` |
| `obs_writes` | 󰙏 | File write/edit count | `[obs_writes]` |
| `obs_bash` | 󰆍 | Bash command count | `[obs_bash]` |
| `obs_prompts` | 󰅺 | Prompt count | `[obs_prompts]` |
| `obs_tasks` | 󰄷 | Completed task count | `[obs_tasks]` |
| `obs_subagents` | 󰓁 | Subagent count | `[obs_subagents]` |
| `obs_failures` | 󰀩 | Tool failure count | `[obs_failures]` |
| `obs_compactions` | 󱃧 | Context compaction count | `[obs_compactions]` |
| `obs_health` | 󰕥 | Session health badge | `[obs_health]` |

## Configuration

All configuration is optional. qLine runs on sensible defaults with zero config.

```bash
# Copy the example config
cp qline.example.toml ~/.config/qline.toml
```

See `qline.example.toml` for all options with inline documentation. Key settings:

### Layout

```toml
[layout]
force_single_line = true    # merge all layout lines (default: true)
max_width = 200             # auto-wrap threshold in visible chars
line1 = ["model", "dir", "context_bar", "cost", "duration"]
line2 = ["cpu", "memory", "disk"]
line3 = ["obs_reads", "obs_rereads", "obs_writes", "obs_bash",
         "obs_prompts", "obs_tasks", "obs_subagents",
         "obs_failures", "obs_compactions", "obs_health"]
```

### Disabling modules

```toml
[cpu]
enabled = false

[memory]
enabled = false
```

Or remove them from the layout arrays.

### Enabling observability

```toml
[obs_reads]
enabled = true

[obs_writes]
enabled = true

[obs_bash]
enabled = true

[obs_health]
enabled = true
```

### Threshold colors

Modules with thresholds escalate color: normal (default) → warn (yellow) → critical (red).

```toml
[cost]
warn_threshold = 2.0        # USD
critical_threshold = 5.0

[context_bar]
warn_threshold = 40.0       # % context used
critical_threshold = 70.0
```

### Colors and glyphs

Every module supports `color`, `bg`, and `glyph` overrides:

```toml
[model]
glyph = "🤖 "
color = "#ff6600"
bg = "#1a1a2e"
```

### Duration formats

| Format | Example | Description |
|---|---|---|
| `auto` | `30s`, `2m30s`, `1h15m` | Smallest meaningful units (default) |
| `hm` | `0h2m`, `1h15m` | Hours and minutes only |
| `m` | `2m`, `75m` | Total minutes |
| `hms` | `0h2m30s`, `1h15m0s` | All three units |

## Architecture

Single Python file (`src/statusline.py`, ~1400 lines). No dependencies beyond Python stdlib (plus optional `tomli` for 3.10).

```
stdin (JSON from Claude Code)
  → read (bounded, 200ms deadline)
  → normalize (sparse-safe field extraction)
  → load config (TOML merge over defaults)
  → collect system data (git, /proc, statvfs — 50ms timeouts)
  → inject obs counters (cached, 30s refresh)
  → render (module registry → auto-wrap at max_width)
  → stdout (single ANSI styled line)
```

### Observability data flow

When obs modules are enabled, qLine reads event counts from the session package:

```
~/.claude/observability/sessions/YYYY-MM-DD/<session_id>/
  metadata/hook_events.jsonl  → event type counts
  custom/reads.jsonl          → read/reread counts
  manifest.json               → health state
```

Counts are cached in `/tmp/qline-cache.json` and refreshed every 30 seconds. The scan uses fast string matching (no JSON parse) for performance.

## Tests

```bash
bash tests/test-statusline.sh                    # all sections
bash tests/test-statusline.sh --section renderer # one section
bash tests/test-statusline.sh --section obs      # obs modules
```

195 tests across 9 sections: parser, normalizer, renderer, ANSI, command, layout, collector, cache, obs.

## Troubleshooting

**Glyphs show as boxes/squares**: Install a Nerd Font on your local terminal and set it as the terminal font. The font must be on the machine running the terminal emulator, not the remote server.

**No output at all**: Check that `~/.claude/statusline.py` exists and is executable. Run it manually: `echo '{"model":{"display_name":"Test"}}' | python3 ~/.claude/statusline.py`

**TOML config ignored on Python 3.10**: Install `tomli`: `pip install tomli`. Or upgrade to Python 3.11+.

**Obs modules show nothing**: They require the observability hook infrastructure. Check that `~/.claude/observability/sessions/` exists and has session data. The obs modules only render when counts are > 0.

**Status line too wide / gets clipped**: Set `max_width` in your TOML to match your terminal width. Default is 200.

**`jq` not found during install**: Install jq (`apt install jq` / `brew install jq`) or manually add the `statusLine` entry to `settings.json` (see Manual Install above).

## Uninstall

```bash
./uninstall.sh
# or manually:
rm ~/.claude/statusline.py ~/.claude/obs_utils.py
# Remove "statusLine" key from ~/.claude/settings.json
```

## License

MIT
