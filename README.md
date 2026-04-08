# qLine

A rich status-line renderer for [Claude Code](https://docs.anthropic.com/en/docs/build-with-claude/computer-use). Reads Claude's status JSON on stdin, renders 3-line ANSI output with context health, observability counters, session metrics, and system monitoring.

```
󰚩 Opus4.6[1M]│▲780k│▼520k│██▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░󰋑85%~│󰓅99%│󰥔5h3m
󰑖44.0k™│©604k™|󰍻+293™│󰐕48│󰑇591│®94%│󰙏214│󰆍612│󰀩48│󰌘12│󰀦23│󰕥│󰀨5│+2.8k/-900│#1│󰃭$167│$929/wk│⏱53%│$/k0.33│io:0.7x
󰝰 qLine│main@abc1234│󰓌 ░░░░░7%│󰍛 ██░░░55%│󰋊 █░░░░24%│tok/t10.8k│▼150kfree│gro:393/t│󰉋53│fail:3.2%│󰔠34%
```

**Line 1** — Model, tokens, context health bar (dual-fill: █=overhead ▓=conversation ░=free), cache rate, active duration

**Line 2** — System overhead, cache metrics, turns, observability counters (reads, rereads, writes, bash, failures, tasks, subagents, health, compactions, hook faults), lines changed, sessions, daily/weekly cost, efficiency metrics

**Line 3** — Directory, git, CPU, memory, disk + overflow from line 2

41 modules in the default layout. All metrics verified against raw data with runtime invariant checking. See [docs/modules.md](docs/modules.md) for the complete reference.

---

## Quick Start

```bash
git clone https://github.com/LucasQuiles/qLine.git
cd qLine
./install.sh        # installs statusline + observability hooks
# Restart Claude Code
```

Optional: customize with `cp qline.example.toml ~/.config/qline.toml`

## Requirements

| Requirement | Minimum | Notes |
|---|---|---|
| Python | 3.10+ | 3.11+ recommended (built-in TOML support) |
| Nerd Font | Any mono variant | Install on **client terminal**, not server |
| Claude Code | Any with `statusLine` support | |

## Configuration

Zero config required — works with defaults. All customization via `~/.config/qline.toml`:

```toml
[layout]
max_width = 120          # line width for wrapping (default 120)
max_lines = 3            # CC status bar line limit (default 3)
show_labels = false      # prepend text labels to modules

# Toggle any module:
[obs_failures]
enabled = true

# Adjust thresholds:
[daily_cost]
warn_threshold = 200
critical_threshold = 400
```

See `qline.example.toml` for all options.

## Modules

37 modules across 3 lines — see [docs/modules.md](docs/modules.md) for source, calculation, and config for each module.

**Line 1 (6):** model, input tokens, output tokens, context bar, cache rate, active duration

**Line 2 (30):** sys overhead, cache read, cache delta, turns, reads, rereads, writes, bash, failures, tasks, subagents, health, compactions, hook faults, lines changed, session count, daily cost, weekly cost, API efficiency, cost/ktok, I/O ratio, tokens/turn, free context, growth rate, unique files, fail rate, think %, cost/turn, burn trend, cost + $/hr

**Line 3 (5 + overflow):** directory, git, CPU, memory, disk

**Optional:** agents, tmux (disabled by default)

### Alert System

8-priority alert cascade for context health (bust → expired → micro → bloat → heavy → compact → turns → degraded). Banner shows for 5s then collapses to inline glyph. Thresholds use CC-verified autocompact percentage when available, falling back to 75%/90% defaults.

## Tests

```bash
bash tests/test-statusline.sh                       # all 300 tests
bash tests/test-statusline.sh --section renderer     # one section
bash tests/test-statusline.sh --section invariants   # metric consistency proofs
```

300 tests across 12 sections: parser, normalizer, renderer, config, ansi, command, layout, collector, cache, stale, obs, new_metrics, derived_metrics, alerts, OPP features, invariants.

## Architecture

```
stdin (JSON) → normalize() → collect_system_data() → _inject_obs_counters()
            → inject_context_overhead() → render() → 3-line ANSI output
```

- **Fail-open:** every path wrapped in try/except. Never crashes CC.
- **Runtime invariants:** `QLINE_DEBUG=1` enables consistency checks (pct drift, counter bounds, cost chains).
- **Stale import safeguard:** `obs_utils.__version__` check prevents shadowing by old copies.
- **Width-aware wrapping:** line 2 overflow distributes to line 3 within `max_width`.

### Key files

| File | Lines | Purpose |
|------|-------|---------|
| `src/statusline.py` | ~2900 | Main renderer — all modules, themes, rendering |
| `src/context_overhead.py` | ~900 | Transcript analysis — overhead, cache, turns |
| `hooks/hook_utils.py` | ~420 | Hook utilities — stdin, fail-open, circuit breaker |
| `hooks/obs_utils.py` | ~660 | Session packages — events, manifest, health |
| `hooks/obs-*.py` | 12 files | Lifecycle hooks — reads, writes, bash, cache, etc. |
| `tests/test-statusline.sh` | ~4000 | Test harness — 300 assertions |
| `docs/modules.md` | ~180 | Complete module reference |

## Install / Update / Uninstall

```bash
./install.sh       # fresh install (copies files, patches settings.json)
./update.sh        # git pull + reinstall
./uninstall.sh     # remove all installed files and settings
```

Plugin mode: symlink `~/.claude/plugins/qline → /path/to/qLine`. The installer detects this and skips file copying (imports directly from the plugin dir).

## License

MIT
