# qLine

A styled status-line renderer for Claude Code. ANSI truecolor, Nerd Font glyphs, TOML-configurable theming, system metrics, and git integration.

## What it looks like

```
 󰚩 Opus 4.6 (1M) │ 󰝰 myproject main@a3f7b2c │ 󰋑 ↑281k ↓141k █░░░░░░░░░ 15% │ $ 0.42 │ 󰥔 1m 30s
 󰓌 █░░░░ 22% │ 󰍛 ██░░░ 35% │ 󰋊 ██░░░ 37%
```

Line 1: model, project/git, context health (tokens + progress bar), cost, duration
Line 2: CPU, memory, disk — each with mini progress bars

## Features

- 12 modules across configurable multi-line layout
- Nerd Font MDI glyphs (Supplementary PUA — compatible with Claude Code's renderer)
- Nord-inspired "Muted Ocean" color palette with pill backgrounds
- Threshold-based color escalation (normal/warn/critical) on context, cost, CPU, memory, disk
- Git branch, short SHA, and dirty indicator merged into the project pill
- Worktree marker when working in a git worktree
- Token counts (input/output) in the context health pill
- Mini progress bars on system metrics
- Stale data dimming with JSON cache fallback when collectors timeout
- `NO_COLOR` support per https://no-color.org/
- Fully configurable via `~/.config/qline.toml`

## Install

```bash
# Install Nerd Font on the machine running your terminal
# (not the server — fonts render on the client)
brew install --cask font-ubuntu-sans-mono-nerd-font  # macOS
# or download from https://github.com/ryanoasis/nerd-fonts

# Install qLine
git clone https://github.com/yourusername/qLine.git
cd qLine
./install.sh
```

Set your terminal font to **UbuntuSansMono Nerd Font Mono** (or any Nerd Font).

## Configuration

All configuration is optional. Create `~/.config/qline.toml` to override defaults:

```toml
[layout]
force_single_line = false           # true to merge everything onto one line
line1 = ["model", "dir", "context_bar", "cost", "duration"]
line2 = ["cpu", "memory", "disk"]

[model]
enabled = true

[dir]
worktree_marker = "⊛"

[context_bar]
width = 10
warn_threshold = 40.0
critical_threshold = 70.0

[cost]
warn_threshold = 2.0
critical_threshold = 5.0

[duration]
format = "auto"                     # auto, hm, m, hms

[cpu]
warn_threshold = 60.0
critical_threshold = 85.0

[memory]
warn_threshold = 70.0
critical_threshold = 90.0

[disk]
path = "/"
warn_threshold = 80.0
critical_threshold = 95.0

[git]
enabled = true
dirty_marker = "*"

[agents]
enabled = false                     # disabled by default

[tmux]
enabled = false                     # disabled by default
```

### Duration formats

| Format | Example | Description |
|--------|---------|-------------|
| `auto` | `30s`, `2m 30s`, `1h 15m` | Smallest meaningful units (default) |
| `hm` | `0h 2m`, `1h 15m` | Hours and minutes only |
| `m` | `2m`, `75m` | Total minutes only |
| `hms` | `0h 2m 30s`, `1h 15m 0s` | All three units always |

### Disabling modules

Set `enabled = false` on any module, or remove it from the layout arrays.

### Colors and glyphs

Every module's `color`, `bg`, and `glyph` can be overridden in TOML. Colors are `#RRGGBB` hex.

## Architecture

Single Python file (`src/statusline.py`, ~1000 lines). No dependencies beyond Python 3.11+ stdlib.

```
stdin (JSON from Claude Code)
  → read (bounded, 200ms deadline)
  → normalize (sparse-safe field extraction)
  → load config (TOML merge)
  → collect system data (git, /proc, statvfs — 50ms timeouts)
  → render (module registry, multi-line layout)
  → stdout (ANSI styled lines)
```

## Tests

```bash
bash tests/test-statusline.sh                    # all sections
bash tests/test-statusline.sh --section renderer # one section
```

186 tests across 8 sections: parser, normalizer, renderer, layout, collector, cache, stale, command.

## Requirements

- Python 3.11+ (for `tomllib`)
- Nerd Font installed on the **client** terminal (not the server)
- Linux for system metrics (`/proc` filesystem); macOS gracefully degrades

## License

MIT
