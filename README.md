# qLine

A status line for [Claude Code](https://docs.anthropic.com/en/docs/build-with-claude/computer-use) that tries its best to be useful. It reads the JSON that Claude Code pipes to status commands and turns it into a little colored bar at the bottom of your terminal. Nothing revolutionary — just the stuff you'd otherwise have to squint at logs to find.

```
 󰚩 Claude 3 │ 󰜗 Sub 2 │ 󰝰 myproject main@a3f │ ↑281k↓141k 󰋑 █░░░░░░░░░ 15% │ $0.42 │ 󰥔 1m30s │ 󰓌 ██░░░ 22% │ 󰍛 ██░░░ 35%
```

It's a single Python file. No pip install, no virtualenv, no build step. Copy it, point Claude Code at it, done.

---

## What it shows you

| What | Example | Why you'd care |
|---|---|---|
| Model name | `󰚩 Op4.6` | Know which model is burning your tokens |
| Directory + git | `󰝰 myproject main@a3f*` | Where you are, which branch, whether it's dirty |
| Context usage | `󰋑 ███░░░░░░░ 35%` | How close you are to running out of context |
| Token I/O | `↑50k↓20k` | How chatty this session has been |
| Cost | `$1.50` | The number you'll think about later |
| Duration | `󰥔 2m30s` | How long you've been at this |
| CPU / Memory / Disk | `󰓌 ██░░░ 42%` | System metrics, because why not |
| Running agents | `󰚩 Claude 3 │ 󰜗 Sub 2` | How many Claude/Codex instances and sub-agents are running |
| tmux sessions | `tmux 3s/12p` | If you're a tmux person, you already know why |
| Observability | `󰑇 42 󰙏 8 󰆍 15` | File reads, writes, bash commands, failures, compactions... the works |

Everything goes yellow at a configurable threshold, then red at another one. Because knowing you've spent $5 is more useful when it's bright red.

---

## Quick start

```bash
git clone https://github.com/LucasQuiles/qLine.git
cd qLine
./install.sh
# Restart Claude Code
```

That's genuinely it for most setups. The installer finds your Python, copies two files, patches your Claude Code settings, and gets out of the way.

If something goes wrong, there's a [troubleshooting section](#troubleshooting) below that covers the usual suspects.

---

## Requirements

| Thing | Minimum | Ideal | What happens if you don't have it |
|---|---|---|---|
| Python | 3.10 | 3.11+ | 3.10 works but needs `pip install tomli` for config files. Below 3.10, no dice. |
| Nerd Font | Any | [Any Mono variant](https://github.com/ryanoasis/nerd-fonts) | Everything still works, but the icons show as boxes. The data's still there. |
| Claude Code | Any with `statusLine` support | Latest | That's... kind of the whole point |
| jq | — | Any | Only the installer needs it. You can skip it and do a [manual install](#manual-install). |
| OS | Linux / macOS / WSL2 | Linux | More on this [below](#platform-notes) |

---

## Install

### The easy way

```bash
git clone https://github.com/LucasQuiles/qLine.git
cd qLine
./install.sh
```

The installer will:
1. Find the newest Python 3.10+ on your system
2. Copy `statusline.py` and `obs_utils.py` to `~/.claude/`
3. Copy the observability hooks to `~/.claude/hooks/`
4. Fix the shebang if your default `python3` is too old
5. Add the `statusLine` command and hook registrations to `~/.claude/settings.json` (with a backup, because we're not monsters)

Restart Claude Code and you should see the status line appear.

### Upgrading

```bash
cd qLine
./update.sh
```

This does a `git pull` and re-runs the installer. Your `~/.config/qline.toml` is never touched.

### Manual install

If you don't trust shell scripts (fair), or the installer doesn't work on your setup:

```bash
# Core files
cp src/statusline.py ~/.claude/statusline.py
cp src/obs_utils.py ~/.claude/obs_utils.py
chmod +x ~/.claude/statusline.py

# Hooks (for observability modules)
mkdir -p ~/.claude/hooks
cp src/hooks/obs-*.py src/hooks/hook_utils.py ~/.claude/hooks/
cp src/obs_utils.py ~/.claude/hooks/
chmod +x ~/.claude/hooks/obs-*.py
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

The path **must be absolute**. `~/` won't work. If the file already has stuff in it, merge the `statusLine` key in — don't replace the whole thing.

For the obs hooks, you also need to register them. See `src/hooks/hooks.json` for the full registration template — replace `HOOKS_DIR` with your actual hooks path (e.g., `/home/YOU/.claude/hooks`) and merge the `hooks` key into your `settings.json`.

### Uninstall

```bash
./uninstall.sh
```

Or manually: delete `~/.claude/statusline.py` and `~/.claude/obs_utils.py`, remove the `statusLine` key from `~/.claude/settings.json`. Your config at `~/.config/qline.toml` is left alone — delete it yourself if you want.

---

## Platform notes

### Linux

Everything works. This is the happy path.

### macOS

Works well. CPU and memory collection use `sysctl` and `vm_stat` instead of `/proc`. Disk works everywhere. Git works everywhere. All the core modules (model, context, cost, duration) don't care about your OS at all.

If `install.sh` complains about `sed`, you're hitting the BSD vs GNU sed thing. Either `brew install gnu-sed` or just do the [manual install](#manual-install).

### WSL2

Works like Linux. The Nerd Font goes on **Windows** though — install it there and set it in Windows Terminal. The qLine files live inside WSL at `~/.claude/`.

### SSH / Remote

qLine runs on the remote machine. The font renders on your local terminal. Install the Nerd Font locally. Python goes on the server.

### Containers

Works if the container has Python 3.10+ and `~/.claude/` is persisted. System metrics reflect whatever `/proc` shows, which might be the container or the host depending on your setup.

---

## Configuration

qLine works with **zero configuration**. Everything below is optional.

### Config file

```
~/.config/qline.toml
```

Create it from the example:
```bash
cp qline.example.toml ~/.config/qline.toml
```

If you're on Python 3.10, you'll need `pip install tomli` for the config to be read. On 3.11+, TOML parsing is built in. If the config can't be read for any reason, qLine quietly uses its defaults. It won't crash or complain.

### Display modes

This is probably the first thing you'll want to set. It controls how modules render their labels:

```toml
[layout]
display_mode = "both"    # "icon" | "text" | "both"
```

| Mode | Example | When to use |
|---|---|---|
| `"both"` | `󰚩 Claude 3 │ 󰜗 Sub 2` | Default. Icons + text. Most readable. |
| `"icon"` | `󰚩 3 │ 󰜗 2` | Compact. Good if you know what the icons mean. |
| `"text"` | `Claude 3 │ Sub 2` | No Nerd Font? No problem. |

You can also override per-module:
```toml
[agents]
display_mode = "both"    # override global just for this module
```

### Layout

```toml
[layout]
force_single_line = true     # Claude Code only reads the first line, so... yeah
max_width = 200              # auto-wrap at this many visible characters
display_mode = "both"        # icon | text | both
line1 = ["model", "dir", "context_bar", "cost", "duration"]
line2 = ["cpu", "memory", "disk", "agents", "tmux"]
line3 = ["obs_reads", "obs_rereads", "obs_writes", "obs_bash",
         "obs_prompts", "obs_tasks", "obs_subagents",
         "obs_failures", "obs_compactions", "obs_health"]
```

Modules only render if they're both **enabled** and **listed in a layout line**. To hide a module, either set `enabled = false` or remove it from the line arrays. Your call.

### Enabling and disabling modules

```toml
# Turn something off
[cpu]
enabled = false

# Turn something on
[obs_reads]
enabled = true
```

### Colors and thresholds

Every module can escalate through three color states: **normal**, **warn** (yellow-ish), and **critical** (red-ish). You set the thresholds:

```toml
[cost]
warn_threshold = 2.0       # dollars — turns yellow
critical_threshold = 5.0   # dollars — turns red

[context_bar]
warn_threshold = 40.0      # percent — "maybe start wrapping up"
critical_threshold = 70.0  # percent — "seriously, wrap up"

[cpu]
warn_threshold = 60.0
critical_threshold = 85.0
show_threshold = 0         # hide below this % (0 = always show)
```

### Customizing glyphs and colors

Every module has a `glyph`, `color`, and `bg`:

```toml
[model]
glyph = "🤖 "           # literally any string — emoji, NF glyph, text, whatever
color = "#ff6600"        # foreground hex
bg = "#1a1a2e"           # pill background hex
```

### Nerd Font glyphs vs emoji

qLine ships with [Nerd Font](https://github.com/ryanoasis/nerd-fonts) glyphs by default. They look great in terminals that have a Nerd Font installed. If you don't have one (or don't want one), you have options:

**Use emoji instead:**
```toml
[model]
glyph = "🤖 "
[cost]
glyph = "💰"
[duration]
glyph = "⏱️ "
[agents]
glyph = "🧑‍💻 "
sub_glyph = "🔀 "
codex_glyph = "📋 "
```

**Use plain text:**
```toml
[model]
glyph = "M:"
[cost]
glyph = "$"
[duration]
glyph = "T:"
```

**Use nothing:**
```toml
[model]
glyph = ""
```

Emoji are wider than Nerd Font glyphs in most terminals (they take 2 columns instead of 1-2), so your status line will be a bit wider. Not a dealbreaker, just something to know.

To find Nerd Font glyph codes, check the [cheat sheet](https://www.nerdfonts.com/cheat-sheet). In TOML, you write them as `"\U000fXXXX"` — but honestly, it's easier to just copy-paste the glyph character directly into the TOML file. Your editor can handle it.

### Duration formats

```toml
[duration]
format = "auto"    # auto | hm | m | hms
```

| Format | Example | Vibe |
|---|---|---|
| `auto` | `30s`, `2m30s`, `1h15m` | Adapts to how long you've been going |
| `hm` | `0h2m`, `1h15m` | Always shows hours, even when it's been 2 minutes |
| `m` | `2m`, `75m` | Just total minutes. Compact. |
| `hms` | `0h2m30s` | Full precision for the detail-oriented |

---

## Agent detection

This is the fun one. qLine doesn't just count processes — it figures out what they are.

It runs a single `ps` command (~24ms) and builds a process tree to classify each `claude` or `codex` process:

| Type | How it's detected | Icon |
|---|---|---|
| **Claude main** | Parent is a shell (`zsh`, `bash`, etc.) | 󰚩 |
| **Claude sub-agent** | Parent chain is `claude → node → claude` | 󰜗 |
| **Codex main** | Parent is a shell or `node` | 󰄷 |
| **Codex sub-agent** | Everything else that's named `codex` | 󰄷 |

The breakdown shows up as segments separated by `│`:
```
󰚩 Claude 3 │ 󰜗 Sub 2 │ 󰄷 Codex 1
```

### Agent config

```toml
[agents]
enabled = true
show_breakdown = true          # false = just show total count
display_mode = ""              # "" = use global; or "icon" / "text" / "both"
glyph = "󰚩 "                  # claude main icon
sub_glyph = "󰜗 "              # sub-agent icon
codex_glyph = "󰄷 "            # codex icon
label = "Claude"               # text label for claude main
sub_label = "Sub"              # text label for sub-agents
codex_label = "Codex"          # text label for codex
inner_separator = " │ "        # between segments
warn_threshold = 5             # total count → yellow
critical_threshold = 8         # total count → red
```

Set `show_breakdown = false` if you just want a single number. Sometimes simple is better.

---

## Observability modules

These are the `obs_*` modules. They show session telemetry — file reads, writes, bash commands, tool failures, context compactions, that sort of thing. They're all disabled by default, but the hook scripts that produce the data ship with qLine in `src/hooks/` and are installed automatically by `install.sh`.

| Module | What it tracks | Default threshold |
|---|---|---|
| `obs_reads` | File reads | — |
| `obs_rereads` | Reread percentage | warn 30%, critical 50% |
| `obs_writes` | File writes/edits | — |
| `obs_bash` | Bash commands run | — |
| `obs_prompts` | User prompts | — |
| `obs_tasks` | Completed tasks | — |
| `obs_subagents` | Subagent spawns (historical) | — |
| `obs_failures` | Tool failures | warn 1, critical 5 |
| `obs_compactions` | Context compactions | — |
| `obs_health` | Session health badge | green/yellow/red |

### How it works

The hooks in `src/hooks/` are Claude Code lifecycle hooks that fire on events like tool use, prompt submit, session start/end, etc. They write structured events to session packages at `~/.claude/observability/sessions/`. qLine scans those files every 30 seconds using fast string matching (no JSON parsing) and caches the results. If the hooks aren't installed or haven't fired yet, these modules just show nothing. No errors, no fuss.

The hooks and their event registrations:

| Hook | Event | Matcher | What it records |
|---|---|---|---|
| `obs-session-start.py` | SessionStart | `.*` | Creates session package, records start |
| `obs-pretool-read.py` | PreToolUse | `Read` | File reads and re-reads |
| `obs-posttool-write.py` | PostToolUse | `Write` | File writes |
| `obs-posttool-edit.py` | PostToolUse | `Edit` | File edits |
| `obs-posttool-bash.py` | PostToolUse | `Bash` | Bash command executions |
| `obs-posttool-failure.py` | PostToolUseFailure | `.*` | Tool failures |
| `obs-prompt-submit.py` | UserPromptSubmit | `.*` | User prompts |
| `obs-precompact.py` | PreCompact | `.*` | Context compactions |
| `obs-subagent-stop.py` | SubagentStop | `.*` | Sub-agent lifecycle |
| `obs-task-completed.py` | TaskCompleted | `.*` | Task completions |
| `obs-session-end.py` | SessionEnd | `.*` | Session summary and health |

All hooks depend on `hook_utils.py` (input parsing) and `obs_utils.py` (session package management). Both are installed alongside the hooks.

To enable the obs modules in the status line:
```toml
[obs_reads]
enabled = true
[obs_writes]
enabled = true
# ... and so on for whichever you want
```

---

## Adding your own module

qLine doesn't have a plugin system (it's one file, let's not get carried away), but adding a module is pretty straightforward if you're comfortable editing Python:

1. **Add a config section** to `DEFAULT_THEME` in `statusline.py`:
   ```python
   "my_thing": {
       "enabled": False,
       "glyph": "🔧 ",
       "color": "#a8d4d0",
       "bg": "#2e3440",
   },
   ```

2. **Write a renderer function** that takes `(state, theme)` and returns `str | None`:
   ```python
   def render_my_thing(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
       value = state.get("my_thing_value")
       if value is None:
           return None
       cfg = theme.get("my_thing", {})
       glyph = cfg.get("glyph", "🔧 ")
       return _pill(f"{glyph}{value}", cfg, theme=theme)
   ```

3. **Register it** in `MODULE_RENDERERS`:
   ```python
   MODULE_RENDERERS: dict[str, Any] = {
       ...
       "my_thing": render_my_thing,
   }
   ```

4. **Add it to a layout line** (either in `DEFAULT_LINE1`/`2`/`3` or via your TOML config)

5. **Populate the data** — either in `collect_system_data()` with a new collector function, or inject it during `normalize()` if it comes from the Claude Code JSON payload

That's it. The `_pill()` helper handles all the ANSI coloring, background pills, threshold escalation, and stale-data dimming. You just give it text and config.

---

## Removing a module

Easier than adding one:

**Option A** — disable it in config:
```toml
[cpu]
enabled = false
```

**Option B** — remove it from the layout lines:
```toml
[layout]
line2 = ["memory", "disk"]   # cpu is gone
```

**Option C** — delete the code. Remove the renderer function, the `DEFAULT_THEME` entry, the `MODULE_RENDERERS` registration, and the layout line reference. qLine won't care — unknown module names are silently skipped.

---

## Preset configs

**Minimal** — just the essentials:
```toml
[layout]
line1 = ["model", "context_bar", "cost"]
line2 = []
line3 = []
```

**Text-only** — no Nerd Font needed:
```toml
[layout]
display_mode = "text"
```

**Icon-only** — compact:
```toml
[layout]
display_mode = "icon"
```

**No system metrics** — useful over SSH:
```toml
[cpu]
enabled = false
[memory]
enabled = false
[disk]
enabled = false
```

**Full observability** — everything on:
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
[obs_compactions]
enabled = true
[obs_health]
enabled = true
```

---

## How it works

Single Python file (~1800 lines) plus a small observability helper (~420 lines). No dependencies beyond Python's standard library.

```
stdin (JSON from Claude Code)
  → read_stdin_bounded()          200ms deadline, 512KB cap
  → normalize()                   pull out the fields we care about
  → load_config()                 merge TOML over defaults
  → collect_system_data()         git, cpu, memory, disk, agents — 50ms timeouts each
  → _inject_obs_counters()        cached event counts, 30s refresh
  → render()                      module registry → themed pills → auto-wrap
  → stdout                        one ANSI-styled line
```

### Design decisions (for the curious)

- **Single file, no dependencies.** Copy and run. No virtualenv, no pip, no build step. The fewer moving parts, the fewer things that break at 2am.
- **Exit 0 always.** Any failure is caught and swallowed. A broken status line should never, ever block Claude Code. That would be annoying and also kind of embarrassing.
- **50ms subprocess timeouts.** System collectors (git, cpu, ps) can't stall the pipeline. If `git status` hangs on a huge repo, qLine shrugs and moves on.
- **Cache with staleness.** System metrics are cached for 60 seconds at `/tmp/qline-cache.json`. Stale data is dimmed rather than hidden — you still see *something*, just a bit faded.
- **NO_COLOR support.** Set `NO_COLOR=1` to get plain text output. Respects [no-color.org](https://no-color.org/).

---

## Tests

```bash
bash tests/test-statusline.sh                    # all 261 tests
bash tests/test-statusline.sh --section renderer # just renderers
bash tests/test-statusline.sh --section collector # just collectors
bash tests/test-statusline.sh --section obs      # just observability
```

261 tests across 11 sections (parser, normalizer, renderer, config, ansi, command, layout, collector, cache, stale, obs). They run under `NO_COLOR=1` for deterministic plain-text assertions. The test file is a bash script because that's what you test CLI tools with.

---

## Troubleshooting

### Icons show as boxes or question marks

Your terminal font isn't a Nerd Font. Install one on your **local machine** (the one you're looking at, not the server). Set it as the terminal font. Use the Mono variant for correct character widths.

**macOS:** `brew install --cask font-ubuntu-sans-mono-nerd-font`

**Linux:** Download from [nerd-fonts releases](https://github.com/ryanoasis/nerd-fonts/releases), extract to `~/.local/share/fonts/`, run `fc-cache -fv`.

**Windows Terminal:** Download, install the `.ttf` files, set in Terminal settings.

**VS Code:** Add `"terminal.integrated.fontFamily": "'UbuntuSansMono Nerd Font Mono'"` to your VS Code settings.

Or just set `display_mode = "text"` in your config and skip the whole font thing.

### Nothing shows up at all

1. Does the file exist? `ls -la ~/.claude/statusline.py`
2. Is it executable? `chmod +x ~/.claude/statusline.py`
3. Does the shebang point to a valid Python? `head -1 ~/.claude/statusline.py`
4. Does it run? `echo '{"model":{"display_name":"Test"}}' | ~/.claude/statusline.py`
5. Is it hooked up? Check `~/.claude/settings.json` for the `statusLine` entry with an **absolute** path.

### Config changes aren't taking effect

- **Python 3.10 without tomli:** Config is silently ignored. `pip install tomli`.
- **Wrong path:** Config must be at `~/.config/qline.toml`.
- **Syntax error:** Any parse error silently falls back to defaults. Validate: `python3 -c "import tomllib; tomllib.load(open('$HOME/.config/qline.toml','rb'))"`

### CPU/memory show nothing

On macOS, these use `sysctl` and `vm_stat`. On Linux, they use `/proc`. If you're in a minimal container or WSL1 without `/proc`, they produce no output. This is expected — the other modules still work fine.

### Status line is too wide / gets clipped

```toml
[layout]
max_width = 120
```

Or disable modules you don't need. Or switch to `display_mode = "icon"` for a more compact look.

### `install.sh` fails

| Error | Fix |
|---|---|
| `No python3 found` | Install Python 3.10+ |
| `~/.claude does not exist` | Run Claude Code once first |
| `jq not found` | `sudo apt install jq` / `brew install jq`, or use [manual install](#manual-install) |
| `sed` errors on macOS | `brew install gnu-sed`, or use [manual install](#manual-install) |
| Permission denied | `chmod +x install.sh` |

---

## License

MIT. Do whatever you want with it. See [LICENSE](LICENSE) for the formal version.

---

## Contributing

This is a personal project that I use every day. If you find it useful, that's great. If you have ideas, open an issue. If you want to send a PR, go for it — just know that I'm one person and I might be slow to respond. No promises, but I appreciate the effort.

The test suite is your friend:
```bash
bash tests/test-statusline.sh
```

If the tests pass and you haven't added dependencies, you're probably in good shape.
