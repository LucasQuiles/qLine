# qLine

A styled status-line renderer for [Claude Code](https://docs.anthropic.com/en/docs/build-with-claude/computer-use). Reads Claude's status JSON on stdin and emits styled output with ANSI truecolor, Nerd Font glyphs, and TOML-configurable theming.

```
󰚩 Opus4.6[1M]│▓▓▓▓░░░░░░ 󰋑41%│ ▲9.0k │ ▼300k │ 󰓅99% │ 󰥔3h10m
 󰑖37.1k™ │©408k™|󰍻 +1.0k™│ 󰅺34 │ 󰑇376 │ ®93% │ 󰙏110 │ 󰆍404 │ 󰀩33 │ 󰌘17 │ 󰀦31 │ 󰕥 │ $83.88|26.44/hr
 󰝰 qline │ main@bca0083  10s│ 󰓌 ░░░░░ 10%  10s│ 󰍛 ██░░░ 57%  10s│ 󰋊 █░░░░ 25%  10s│...
```

**Line 1** — Model, context bar, tokens in/out, cache hit rate, cost, duration
**Line 2** — System overhead, cache read/write, obs counters (prompts, reads, rereads, writes, bash, failures, tasks, subagents, health), cost rate
**Line 3** — Directory, git branch@sha with freshness, CPU/memory/disk with freshness, analytics

---

## Table of Contents

1. [Requirements](#requirements)
2. [Quick Start](#quick-start)
3. [Step-by-Step Install](#step-by-step-install)
4. [Platform Notes](#platform-notes)
5. [Verify Your Install](#verify-your-install)
6. [Modules](#modules)
7. [Configuration](#configuration)
8. [Observability Setup](#observability-setup)
9. [Architecture](#architecture)
10. [Tests](#tests)
11. [Troubleshooting](#troubleshooting)
12. [Uninstall](#uninstall)

---

## Requirements

| Requirement | Minimum | Recommended | Notes |
|---|---|---|---|
| Python | 3.10 | 3.11+ | 3.10 works but needs `pip install tomli` for TOML config |
| Nerd Font | Any | UbuntuSansMono | Install on the **client terminal**, not the remote server |
| OS | Linux / macOS / WSL | Linux | `cpu` and `memory` use `/proc` (Linux only); `disk` uses `os.statvfs` (works everywhere) |
| Claude Code | Any version with `statusLine` support | Latest | The `statusLine` command hook invokes qLine |
| jq | — | Any | Only needed by `install.sh` to patch `settings.json`; not a runtime dependency |
| git | Any | Any | Only needed to clone the repo |

### What if I don't meet a requirement?

- **Python 3.10 without tomli**: qLine still works — it uses built-in defaults. You just can't customize via `~/.config/qline.toml` until you install `tomli` or upgrade to 3.11+.
- **No Nerd Font**: Everything works, but glyphs render as boxes (□) or question marks. The data is still there and readable.
- **macOS or WSL1 without `/proc`**: Core modules (model, dir, context, cost, duration, git) work fine. `cpu` and `memory` show nothing (they need `/proc`). `disk` works everywhere via `os.statvfs`. WSL2 has `/proc` so all modules work.
- **No jq**: The install script warns you and skips patching `settings.json`. You'll need to add the `statusLine` entry manually (see [Manual Install](#manual-install)).

---

## Quick Start

```bash
git clone https://github.com/LucasQuiles/qLine.git
cd qLine
./install.sh
# Restart Claude Code
```

That's it for most Linux systems. Read on if you hit issues or want to customize.

---

## Step-by-Step Install

### 1. Clone the repository

```bash
git clone https://github.com/LucasQuiles/qLine.git
cd qLine
```

### 2. Check your Python version

```bash
python3 --version
```

qLine requires **Python 3.10+**. If your default `python3` is older:

```bash
# Check if a newer version is available
python3.11 --version 2>/dev/null || python3.12 --version 2>/dev/null

# The installer auto-detects the newest available Python.
# If your only option is 3.10, install tomli for TOML config support:
pip install tomli          # or pip3 install tomli
```

**Common Python scenarios:**

| System | Default Python | What happens |
|---|---|---|
| Ubuntu 22.04 | 3.10 | Works. TOML config needs `pip install tomli` |
| Ubuntu 24.04 | 3.12 | Works out of the box |
| macOS (Homebrew) | 3.12+ | Works out of the box |
| Debian 11 | 3.9 | Too old. Install 3.11+ via `deadsnakes` PPA or pyenv |
| WSL2 (Ubuntu) | Matches distro | Same as native Ubuntu |
| Amazon Linux 2 | 3.7 | Too old. Use `amazon-linux-extras install python3.11` |

### 3. Install a Nerd Font

Nerd Fonts provide the glyphs (icons) in the status line. **Install the font on the machine running your terminal emulator** — if you SSH into a server, the font goes on your laptop, not the server.

**macOS:**
```bash
brew install --cask font-ubuntu-sans-mono-nerd-font
```

**Linux (local desktop):**
```bash
# Download from https://github.com/ryanoasis/nerd-fonts/releases
# Choose any Mono variant (UbuntuSansMono, JetBrainsMono, FiraCode, etc.)
mkdir -p ~/.local/share/fonts
unzip UbuntuSansMonoNerdFont.zip -d ~/.local/share/fonts/
fc-cache -fv
```

**Windows Terminal / WSL:**
1. Download a Nerd Font `.zip` from https://github.com/ryanoasis/nerd-fonts/releases
2. Extract and install the `.ttf` files (right-click → Install for all users)
3. In Windows Terminal: Settings → Profile → Appearance → Font face → select the Nerd Font

**VS Code integrated terminal:**
Add to `settings.json`:
```json
{
  "terminal.integrated.fontFamily": "'UbuntuSansMono Nerd Font Mono'"
}
```

After installing, set your terminal font to the **Mono** variant (e.g., `UbuntuSansMono Nerd Font Mono`). The "Mono" variant ensures glyphs don't break character-width alignment.

### 4. Run the installer

```bash
./install.sh
```

The installer will:

1. **Find Python** — scans for `python3.13` down to `python3`, picks the newest
2. **Version check** — rejects anything below 3.10, warns about 3.10 missing `tomllib`
3. **Check for `~/.claude/`** — fails if Claude Code hasn't been run yet (run Claude Code once first)
4. **Copy files** — installs `statusline.py` and `obs_utils.py` to `~/.claude/`
5. **Fix shebang** — if `python3` is too old but a newer version exists, rewrites the shebang
6. **Patch `settings.json`** — adds the `statusLine` command binding (backs up first)
7. **Print next steps** — config location, font reminder

**Example output:**
```
=== qLine Install ===
Python: python3.12 (3.12)
Installed: /home/you/.claude/statusline.py
Installed: /home/you/.claude/obs_utils.py
Backup: /home/you/.claude/backups/statusline-install-20260322-143012/settings.json.bak
statusLine binding added to /home/you/.claude/settings.json

=== Setup Complete ===
  Restart Claude Code to activate.

  Optional: copy the example config to customize:
    cp /home/you/qLine/qline.example.toml ~/.config/qline.toml

  Nerd Font required for glyphs — install on your LOCAL terminal:
    https://github.com/ryanoasis/nerd-fonts
```

### 5. Restart Claude Code

The status line appears at the bottom of the Claude Code interface after restart. No further action needed — it works with zero configuration.

### Upgrading

```bash
cd qLine
./update.sh
# Restart Claude Code
```

This pulls the latest changes and re-runs the installer. qLine does not auto-update — run this when you want the latest version.

The installer always overwrites `statusline.py` and `obs_utils.py` with the repo versions. Your `~/.config/qline.toml` is never touched.

### Manual Install

If you prefer not to run the script, or if it doesn't work on your system:

```bash
# Copy the files
cp src/statusline.py ~/.claude/statusline.py
cp src/obs_utils.py ~/.claude/obs_utils.py
chmod +x ~/.claude/statusline.py

# If python3 is too old (below 3.10), fix the shebang to a newer version.
# Replace python3.12 with whichever version you have:
#   Linux:  sed -i '1s|.*|#!/usr/bin/env python3.12|' ~/.claude/statusline.py
#   macOS:  sed -i '' '1s|.*|#!/usr/bin/env python3.12|' ~/.claude/statusline.py
# Or simply edit line 1 of the file in any text editor.
```

Then add to `~/.claude/settings.json` (create it if it doesn't exist):
```json
{
  "statusLine": {
    "type": "command",
    "command": "/home/YOU/.claude/statusline.py"
  }
}
```

Replace `/home/YOU` with your actual home directory. The path **must be absolute**.

If `settings.json` already has content, merge the `statusLine` key into the existing object — don't replace the file.

---

## Platform Notes

### Linux (native)

Full support. All modules work including `/proc`-based system metrics.

### macOS

Core modules work (model, dir, context, cost, duration, git). System metrics (`cpu`, `memory`) require `/proc` and will silently produce no output. `disk` works via `os.statvfs`.

`sed -i` in the install script uses GNU syntax. If you hit errors, install GNU sed: `brew install gnu-sed` and ensure it's in your `PATH`, or use the [Manual Install](#manual-install) steps.

### WSL (Windows Subsystem for Linux)

Works like native Linux. Key considerations:

- **Nerd Font goes on Windows**, not inside WSL. Install the font in Windows and set it in Windows Terminal.
- **`/proc` is available** in WSL2 — system metrics work.
- **Home directory**: `~/.claude/` is inside the WSL filesystem (`/home/username/`), not the Windows filesystem. The absolute path in `settings.json` must use the Linux path.

### SSH / Remote servers

qLine runs on the **remote server** but the font renders on your **local terminal**. Install the Nerd Font locally. The script and Python live on the remote machine.

### Docker / Containers

Works if the container has Python 3.10+ and Claude Code's `~/.claude/` directory is mounted or persisted. System metrics depend on whether `/proc` reflects the host or the container.

### pyenv / conda / virtualenv

The installer detects whichever Python is first in `PATH`. If you use pyenv, ensure the desired version is active (`pyenv shell 3.12`) before running `install.sh`. The shebang will be set to `#!/usr/bin/env python3` which respects your active environment.

For conda: activate the environment first. For virtualenv: qLine has no pip dependencies (unless you need `tomli` for 3.10), so it works outside any virtualenv.

---

## Verify Your Install

After installing and restarting Claude Code, verify manually:

```bash
# Check installed version matches the repo
cd /path/to/qLine
git log --oneline -1           # note the commit hash
grep -c '"enabled": False' ~/.claude/statusline.py
# Should show 12 (agents, tmux, + 10 obs modules)
# If it shows fewer, re-run: git pull && ./install.sh

# Should print a styled line with your model name
# Use the script directly (its shebang points to the correct Python)
echo '{"model":{"display_name":"Test Model"}}' | ~/.claude/statusline.py

# With NO_COLOR for plain text (easier to read in verification)
echo '{"model":{"display_name":"Test Model"}}' | NO_COLOR=1 ~/.claude/statusline.py

# Full payload test
echo '{"model":{"display_name":"Opus 4.6"},"cost":{"total_cost_usd":1.50,"total_duration_ms":120000},"context_window":{"total_input_tokens":50000,"total_output_tokens":20000,"context_window_size":200000}}' | NO_COLOR=1 ~/.claude/statusline.py
```

Expected output for the full test:
```
󰚩 Op4.6│↑50.0k↓20.0k 󰋑 ███░░░░░░░ 35%│$1.50│󰥔 2m
```

> **Note:** If obs modules appear as enabled when you expect them disabled, your installed copy may be from an older commit. Run `git pull && ./install.sh` to update.

If you see boxes instead of glyphs, your terminal font isn't a Nerd Font (see [Step 3](#3-install-a-nerd-font)).

If you see nothing, check `python3 --version` and that `~/.claude/statusline.py` exists and is executable.

---

## Modules

### Line 1 — Core

| Module | Glyph | Shows | Example |
|---|---|---|---|
| `model` | 󰚩 | Model name | `󰚩 Opus4.6[1M]` |
| `context_bar` | 󰋑 | Dual-color context health bar | `▓▓▓░░░░ 󰋑 35%` |
| `token_counts` | ▲ | Input tokens | `▲ 9.0k` |
| `token_out_counts` | ▼ | Output tokens | `▼ 300k` |
| `cache_rate` | 󰓅 | Cache hit rate (measured only) | `󰓅 99%` |
| `cost` | `$` | Session cost + $/hr rate | `$83.88\|26.44/hr` |
| `duration` | 󰥔 | Session duration | `󰥔 3h10m` |
| `degraded` | ⚠ | Error diagnostic pill (only on error) | `⚠ 2 err: cpu,obs` |

### Line 2 — Overhead + Observability

| Module | Glyph | Shows | Threshold colors |
|---|---|---|---|
| `sys_overhead_pill` | 󰑖 | System token overhead | — |
| `cache_read` | © | Cache read tokens this turn | — |
| `cache_delta` | 󰍻 | Cache write tokens this turn | spike > 5k (red) |
| `obs_prompts` | 󰅺 | User prompt count | — |
| `obs_reads` | 󰑇 | File read count | — |
| `obs_rereads` | ® | Reread percentage | warn 30%, critical 50% |
| `obs_writes` | 󰙏 | File write/edit count | — |
| `obs_bash` | 󰆍 | Bash command count | — |
| `obs_failures` | 󰀩 | Tool failure count | warn 1, critical 5 |
| `obs_tasks` | 󰌘 | Completed task count | — |
| `obs_subagents` | 󰀦 | Subagent spawn count | — |
| `obs_health` | 󰕥 | Session health badge | green/yellow/red |
| `obs_compactions` | 󰉇 | Context compaction count | — |
| `turns` | 󰔠 | Turns until autocompact | green > 50, red ≤ 10 |

### Line 3 — System + Analytics

| Module | Glyph | Shows | Notes |
|---|---|---|---|
| `dir` | 󰝰 | Working directory | — |
| `git` | — | Branch@SHA + freshness age | `main@bca0083 10s` |
| `cpu` | 󰓌 | CPU usage bar + freshness | `󰓌 ░░░░░ 10% 10s` |
| `memory` | 󰍛 | Memory usage bar + freshness | `󰍛 ██░░░ 57% 10s` |
| `disk` | 󰋊 | Disk usage bar + freshness | `󰋊 █░░░░ 25% 10s` |
| `daily_cost` | 󰃭 | Today's cumulative cost | — |
| `weekly_cost` | 󰃗 | Weekly cost estimate | — |
| `think_pct` | 󰔛 | Human wait time % | — |
| `cost_per_ktok` | 󰈣 | Cost per 1k output tokens | — |
| `io_ratio` | 󰻁 | Output:input token ratio | — |
| `tokens_per_turn` | 󰭵 | Avg output tokens per turn | — |
| `free_context` | 󰚎 | Remaining context tokens | — |

### Utility (disabled by default)

| Module | Glyph | Shows | Enable with |
|---|---|---|---|
| `agents` | 󰓌 | Active Codex instance count | `[agents]` `enabled = true` |
| `tmux` | `tmux` | tmux session/pane count | `[tmux]` `enabled = true` |

### Context Overhead Monitor

The `context_bar`, `sys_overhead`, and `cache_writes` modules work together to show what is consuming your context window in real time.

**How it works:**
1. On the first API response, the system captures `cache_creation_input_tokens` as the baseline system overhead (the "anchor"). This includes tool definitions, CLAUDE.md, skill stubs, MCP schemas, and the system prompt.
2. On each subsequent turn, `cache_creation_input_tokens` shows how much new content was written to cache. Spikes indicate skill loads, tool schema expansions, or compaction rebuilds.
3. The dual-color bar shows the proportion of system overhead vs conversation within the used context. Colors follow the health severity state (teal → yellow → red).

**Cache health states:**
| State | Hit Rate | Indicator | Meaning |
|-------|----------|-----------|---------|
| Healthy | ≥ 80% | — | Cache is working normally |
| Degraded | 30–80% | `~` suffix | Intermittent cache invalidation |
| Busting | < 30% | `󰒿` suffix | Active cache busting (10-20x token burn) |

**Spike detection** in `cache_writes`:
| Level | Threshold | Display | Meaning |
|-------|-----------|---------|---------|
| Normal | < 1k | `200` | Normal conversation churn |
| Notable | 1k–5k | `3.0k` | Skill or tool load |
| Spike | > 5k | `8.0k󰒿` | Large injection or compaction rebuild |

**Data sources** (in priority order):
1. Manifest anchor (`cache_anchor`) — written by `obs-stop-cache.py` hook on first turn
2. Transcript file start — reads first 4KB for the first completed turn's `cache_creation`
3. Transcript tail window — last 5 turns for cache hit rate
4. Static estimate — file sizes + MCP server count (fallback only)

---

## Configuration

qLine works with **zero configuration**. All customization is optional.

### Config file location

```
~/.config/qline.toml
```

Create it by copying the example:

```bash
cp qline.example.toml ~/.config/qline.toml
```

The example file contains every option with inline documentation and commented-out defaults.

### Python version and TOML

| Python | TOML support |
|---|---|
| 3.11+ | Built-in `tomllib` — works automatically |
| 3.10 with `tomli` installed | `pip install tomli` — works automatically |
| 3.10 without `tomli` | Config file ignored — defaults used |
| 3.9 and below | Not supported |

### Layout

```toml
[layout]
force_single_line = true    # merge all lines into one (default: true)
max_width = 200             # auto-wrap at this visible character count
line1 = ["model", "dir", "context_bar", "cost", "duration"]
line2 = ["cpu", "memory", "disk"]
line3 = ["obs_reads", "obs_rereads", "obs_writes", "obs_bash",
         "obs_prompts", "obs_tasks", "obs_subagents",
         "obs_failures", "obs_compactions", "obs_health"]
```

**Why is `force_single_line` default true?** Claude Code reads only the first line of stdout from status commands. Multi-line output is invisible. When `force_single_line` is true, all modules are merged into a single stream and auto-wrapped at `max_width`.

If a future Claude Code version supports multi-line, set `force_single_line = false` and each `lineN` array renders as its own row.

### Enabling and disabling modules

```toml
# Disable a module
[cpu]
enabled = false

# Enable an obs module
[obs_reads]
enabled = true
```

You can also control visibility by editing the `lineN` arrays — a module not listed in any line won't render even if enabled.

### Threshold colors

Modules with thresholds escalate: **default color → warn (yellow) → critical (red)**.

```toml
[cost]
warn_threshold = 2.0          # USD
critical_threshold = 5.0

[context_bar]
warn_threshold = 40.0         # % context used
critical_threshold = 70.0

[obs_failures]
warn_threshold = 1             # number of failures
critical_threshold = 5

[obs_rereads]
warn_threshold = 30            # reread %
critical_threshold = 50
```

### Colors and glyphs

Every module supports `color` (foreground), `bg` (pill background), and `glyph`:

```toml
[model]
glyph = "🤖 "                # any string — emoji, NF glyph, or plain text
color = "#ff6600"             # hex foreground
bg = "#1a1a2e"                # hex background
```

### Duration formats

```toml
[duration]
format = "auto"               # auto | hm | m | hms
```

| Format | Example | When to use |
|---|---|---|
| `auto` | `30s`, `2m30s`, `1h15m` | Default — adapts to session length |
| `hm` | `0h2m`, `1h15m` | When you always want hours shown |
| `m` | `2m`, `75m` | Compact; just total minutes |
| `hms` | `0h2m30s` | When you want full precision |

### Preset examples

**Minimal (just model + context):**
```toml
[layout]
line1 = ["model", "context_bar", "cost"]
line2 = []
line3 = []
```

**No system metrics (SSH to remote):**
```toml
[cpu]
enabled = false
[memory]
enabled = false
[disk]
enabled = false
```

**Full observability:**
```toml
[obs_reads]
enabled = true
[obs_rereads]
enabled = true
[obs_writes]
enabled = true
[obs_bash]
enabled = true
[obs_prompts]
enabled = true
[obs_tasks]
enabled = true
[obs_subagents]
enabled = true
[obs_failures]
enabled = true
[obs_health]
enabled = true
```

---

## Observability Setup

The `obs_*` modules display session telemetry — file operations, bash commands, tool failures, and more. They read data from observability session packages written by Claude Code lifecycle hooks.

### How it works

```
Claude Code hooks → write events to session package → qLine reads cached counts
```

The data lives at:
```
~/.claude/observability/sessions/YYYY-MM-DD/<session_id>/
  metadata/hook_events.jsonl    ← event counts by type
  custom/reads.jsonl            ← file read/reread tracking
  manifest.json                 ← health state
```

qLine scans these files every 30 seconds using fast string matching (no JSON parse) and caches results in `/tmp/qline-cache.json`.

### Prerequisites

The obs modules need:

1. **`obs_utils.py`** — shipped with qLine and installed to `~/.claude/` by `install.sh`
2. **Session hooks** — Claude Code lifecycle hooks that write events to the session package. These are the `obs-session-start.py`, `obs-posttool-*.py`, etc. scripts in `~/.claude/hooks/`
3. **Hook registrations** — entries in `~/.claude/settings.json` under the `hooks` key that tell Claude Code to invoke the hook scripts

If you don't have the hooks infrastructure, the obs modules simply show nothing — they fail silently. The rest of qLine works fine.

### Enabling obs modules

Once the hooks are in place and session data is being written:

```toml
# ~/.config/qline.toml
[obs_reads]
enabled = true
[obs_rereads]
enabled = true
[obs_writes]
enabled = true
[obs_bash]
enabled = true
[obs_health]
enabled = true
```

### Verifying obs data

```bash
# Check if session packages exist
ls ~/.claude/observability/sessions/

# Check recent session events
ls -t ~/.claude/observability/sessions/$(date +%Y-%m-%d)/ | head -1
# Then check its events:
wc -l ~/.claude/observability/sessions/$(date +%Y-%m-%d)/*/metadata/hook_events.jsonl
```

If there are no session directories, the hooks aren't installed or haven't fired yet.

---

## Architecture

Four Python modules: `src/statusline.py` (~3190 lines), `src/context_overhead.py` (~890 lines), `src/obs_utils.py` (~630 lines), and `src/qline-daemon.py` (~170 lines), plus 12 observability hooks in `hooks/` and shared libraries in `scripts/`. No runtime dependencies beyond Python stdlib.

```
stdin (JSON from Claude Code)
  → _init_session_paths()          # scope /tmp files by session_id
  → read_stdin_bounded()           # 200ms deadline, 256KB cap
  → normalize()                    # sparse-safe field extraction
  → _check_payload_fingerprint()   # detect CC format changes
  → collect_system_data()          # git, /proc, statvfs — tiered 60s TTL
  → _inject_obs_counters()         # cached event counts — tiered 5s TTL
  → inject_context_overhead()      # transcript analysis — 30s TTL
  → render()                       # 3-line module registry output
  → stdout                         # ANSI-styled, up to 3 lines
```

### Key design decisions

- **Session isolation**: all `/tmp` state files scoped by `sha256(session_id)[:12]`. Concurrent CC sessions (multiple tabs, subagents, different projects) cannot corrupt each other.
- **Tiered cache TTL**: obs counters refresh every 5s (change per turn), overhead every 30s, system metrics every 60s.
- **Freshness visibility**: stale cached metrics show a dim age suffix (e.g., `10s`) so you can tell at a glance whether data is current.
- **Diagnostic capture**: key `except` blocks call `_capture_diagnostic()` instead of bare `pass`. The `degraded` pill renders visibly when errors occur — the statusline never goes silently blank.
- **Schema fingerprint**: hashes the CC payload structure on first invocation, detects format changes across CC updates, surfaces a visible diagnostic.
- **Exit 0 always**: any failure is caught. A broken status line must never block Claude Code.
- **50ms subprocess timeouts**: system collectors (git, cpu) can't stall the pipeline.
- **NO_COLOR support**: respects https://no-color.org/ — set `NO_COLOR=1` to get plain text.

### Deployment

```
src/statusline.py  →  install.sh  →  ~/.claude/statusline.py
     (repo)              (copy)          (production)
```

The repo is the single source of truth. Run `bash install.sh` after any code change. The installed version imports `obs_utils` and `context_overhead` from `~/.claude/`.

---

## Tests

```bash
bash tests/test-statusline.sh                    # all sections
bash tests/test-statusline.sh --section renderer # one section
bash tests/test-statusline.sh --section obs      # obs modules only
```

235 tests across 10 sections:

| Section | Tests | What it covers |
|---|---|---|
| parser | Input reading, JSON parsing, byte limits |
| normalizer | Field extraction from Claude's JSON payload |
| renderer | Module rendering, pill styling, separators |
| ansi | ANSI color output, NO_COLOR support |
| command | End-to-end executable tests |
| layout | Multi-line, force_single_line, module ordering |
| collector | System metric collection (CPU, memory, disk, git) |
| cache | Cache read/write, staleness, version migration |
| obs | Observability snapshot, throttle, health, counters |

---

## Troubleshooting

### Glyphs show as boxes (□) or question marks

Your terminal font isn't a Nerd Font. Install one on your **local machine** (the one running the terminal emulator) and set it as the terminal font. See [Step 3](#3-install-a-nerd-font).

### No output at all

1. Check the file exists: `ls -la ~/.claude/statusline.py`
2. Check it's executable: `chmod +x ~/.claude/statusline.py`
3. Check the shebang: `head -1 ~/.claude/statusline.py` — does it point to a valid Python 3.10+?
4. Test the shebang interpreter: run the command from the shebang line with `--version` (e.g., `/usr/bin/env python3 --version`)
5. Test it directly: `echo '{"model":{"display_name":"Test"}}' | ~/.claude/statusline.py`

### Status line shows in terminal but not in Claude Code

Check `~/.claude/settings.json` has the `statusLine` entry:
```json
{
  "statusLine": {
    "type": "command",
    "command": "/home/YOU/.claude/statusline.py"
  }
}
```

The path must be **absolute** (not `~/...`). Restart Claude Code after editing.

### TOML config changes have no effect

- **Python 3.10 without tomli**: config is silently ignored. `pip install tomli` to fix.
- **Wrong path**: config must be at `~/.config/qline.toml` (not `~/.claude/`).
- **TOML syntax error**: any parse error silently falls back to defaults. Validate with: `python3 -c "import tomllib; tomllib.load(open('$HOME/.config/qline.toml','rb'))"`

### Obs modules show nothing

- Are they enabled? Check `~/.config/qline.toml` has `enabled = true` for each.
- Does session data exist? `ls ~/.claude/observability/sessions/`
- Obs modules only render when counts are > 0. At session start, they're empty.

### Status line is clipped / too wide

Set `max_width` in your TOML to match your display:
```toml
[layout]
max_width = 120
```

Or disable modules you don't need to reduce width.

### `install.sh` fails

| Error | Fix |
|---|---|
| `No python3 found` | Install Python 3.10+. On Ubuntu: `sudo apt install python3` |
| `~/.claude does not exist` | Run Claude Code once first to create the directory |
| `jq not found` | `sudo apt install jq` or `brew install jq`, or use [Manual Install](#manual-install) |
| `sed: invalid option -- 'i'` | macOS default sed. Use `brew install gnu-sed` or [Manual Install](#manual-install) |
| `permission denied` | `chmod +x install.sh` |

### CPU/memory bars show nothing

These modules read `/proc/stat` and `/proc/meminfo`. They only work on Linux. On macOS, WSL1, or containers without `/proc`, they silently produce no output. This is expected. The `disk` module uses `os.statvfs` and works on all platforms.

---

## Uninstall

```bash
./uninstall.sh
```

Or manually:
```bash
rm ~/.claude/statusline.py ~/.claude/obs_utils.py
rm -f ~/.claude/context_overhead.py
rm -f ~/.claude/hooks/obs-*.py
rm -f ~/.claude/scripts/obs_utils.py ~/.claude/scripts/hook_utils.py
# Edit ~/.claude/settings.json and remove the "statusLine" key
```

The uninstall script removes the `statusLine` binding from `settings.json` and all installed Python files: `statusline.py`, `obs_utils.py`, `context_overhead.py`, the 12 observability hooks in `hooks/`, and shared scripts in `scripts/`.

Your `~/.config/qline.toml` is not touched — delete it if you want a full cleanup.

---

## License

MIT
