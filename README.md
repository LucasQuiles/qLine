---
title: "qLine"
doc_schema: "q-doc-v1"
status: "current"
authority: "reference"
owner_surface: "."
created: "2026-06-14"
updated: "2026-09-03"
requires_recapture: true
action_boundary: >
  Opening this file alone does not authorize install, update, uninstall, hook
  installation, Claude settings mutation, plugin symlink changes, command execution,
  repo mutation, cleanup, external action, or treating stale status claims as current.
---

# qLine

> Direct-open boundary: documentation reference only. Opening this file alone does
> not authorize install, update, uninstall, hook installation, Claude settings
> mutation, plugin symlink changes, command execution, repo mutation, cleanup,
> external action, or treating stale status claims as current.

Updated: 2026-09-03

A rich status-line renderer for [Claude Code](https://docs.anthropic.com/en/docs/build-with-claude/computer-use). Reads Claude's status JSON on stdin, renders 3-line ANSI output with context health, observability counters, session metrics, and system monitoring.

Commands, paths, hook references, plugin examples, test counts, metrics, and runtime
screenshots in this file are descriptive examples only; recapture current state and
obtain a separate named approval before using them against live Claude settings,
hooks, plugins, or repositories.

```text
󰚩 Opus4.6[1M]│▲780k│▼520k│██▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░󰋑85%~│󰓅99%│󰥔5h3m
󰑖44.0k™│©604k™|󰍻+293™│󰐕48│󰑇591│®94%│󰙏214│󰆍612│󰀩48│󰌘12│󰀦23│󰕥│󰀨5│+2.8k/-900│#1│󰃭$167│$929/wk│⏱53%│$/k0.33│io:0.7x
󰝰 qLine│main@abc1234│󰓌 ░░░░░7%│󰍛 ██░░░55%│󰋊 █░░░░24%│tok/t10.8k│▼150kfree│gro:393/t│󰉋53│fail:3.2%│󰔠34%
```

**Line 1** — Model, tokens, context health bar (dual-fill: █=overhead ▓=conversation ░=free), cache rate, active duration

**Line 2** — System overhead, cache metrics, turns, observability counters (reads, rereads, writes, bash, failures, tasks, subagents, health, compactions, hook faults), lines changed, sessions, daily/weekly cost, efficiency metrics

**Line 3** — Directory, git, normalized load, memory, disk + overflow from line 2

41 modules in the default layout. All metrics verified against raw data with runtime invariant checking. See [docs/modules.md](docs/modules.md) for the complete reference.

---

## Quick Start

```bash
git clone git@github.com:LucasQuiles/qLine.git
cd qLine
./install.sh        # installs statusline + observability hooks
# Restart Claude Code
```

Optional: customize with `cp qline.example.toml ~/.config/qline.toml`

An optional terminal pane shows recorded metrics on demand through `/qline`.
See [the qLine details mod](mods/qline-details/README.md) for a process-local
trial and its tested runtime. The ordinary status line remains available.

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

41 modules across 3 lines — see [docs/modules.md](docs/modules.md) for source, calculation, and config for each module.

**Line 1 (6):** model, input tokens, output tokens, context bar, cache rate, active duration

**Line 2 (31):** sys overhead, cache read, cache delta, turns, reads, rereads, writes, bash, failures, tasks, subagents, health, compactions, hook faults, diagnostics, lines changed, session count, daily cost, weekly cost, API efficiency, cost/ktok, I/O ratio, tokens/turn, free context, growth rate, unique files, fail rate, think %, cost/turn, burn trend, cost + $/hr

**Line 3 (5 + overflow):** directory, git, CPU, memory, disk

The CPU indicator shows the one-minute load average divided by the logical CPU
count, expressed as a percentage. It can exceed 100%; it is not CPU utilization.
The `cpu` configuration and cache keys remain compatible.

**Optional:** agents, tmux (disabled by default)

### Alert System

8-priority alert cascade for context health (bust → expired → micro → bloat → heavy → compact → turns → degraded). Banner shows for 5s then collapses to inline glyph. Alert onset is stored per session under a private temporary directory using a SHA-256 name, an atomic mode-0600 write, and bounded stale-file cleanup. Thresholds use CC-verified autocompact percentage when available, falling back to 75%/90% defaults.

Observability diagnostics share a versioned, one-MiB-bounded JSONL envelope.
The status line shows a compact diagnostic count; set
`QLINE_DIAGNOSTICS_VERBOSE=1` to include closed reason codes. New session
manifests use additive schema `1.1.0`; readers accept missing and `1.x`
versions as compatible and reject unknown major versions.

## Tests

```bash
python3 -m pip install -r requirements-dev.txt
python3 scripts/verify.py doctor                    # prerequisites, no checks run
python3 scripts/verify.py run                       # canonical local/CI gate
```

The gate parses tracked Python, runs Ruff without cache, runs full ShellCheck on
supported shell entrypoints and zsh syntax checks on zsh entrypoints, runs the Python,
shell, and installer suites, checks
both working-tree and committed-range whitespace, and rejects masked diagnostics,
exit-masking pipelines, wall-clock sleeps, and assertion-free Python tests.
Its shell regression receives the verifier's exact Python interpreter, so the
3.10/3.12 CI matrix does not silently fall back to another installed version.
It exits 0 on pass, 1 for completed check failures, and 2 when verification is
blocked or inconclusive. Focus one component when iterating:

```bash
python3 scripts/verify.py run --check pytest
bash tests/test-statusline.sh --section renderer
python3 scripts/verify.py run --format json --fields summary,effects
```

Contributor workflow, failure semantics, private full-log handling, and the
complete `QLV-*` error taxonomy are documented in
[docs/VERIFICATION.md](docs/VERIFICATION.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Architecture

```text
stdin (JSON) → throttle cache → renderer on transcript change or cache expiry
renderer: normalize() → collect_system_data() → _inject_obs_counters()
            → inject_context_overhead() → render() → 3-line ANSI output
```

- **Fail-open:** every path wrapped in try/except. Never crashes CC.
- **Runtime invariants:** `QLINE_DEBUG=1` enables consistency checks (pct drift, counter bounds, cost chains).
- **Stale import safeguard:** `obs_utils.__version__` check prevents shadowing by old copies.
- **Width-aware wrapping:** line 2 overflow distributes to line 3 within `max_width`.

### Key files

| File | Lines | Purpose |
|------|-------|---------|
| `src/statusline-throttle.zsh` | — | Throttle front end; reuses output for an unchanged transcript within the cache lifetime |
| `src/statusline.py` | ~2900 | Main renderer — all modules, themes, rendering |
| `src/context_overhead.py` | ~900 | Transcript analysis — overhead, cache, turns |
| `hooks/hook_utils.py` | ~420 | Hook utilities — stdin, fail-open, circuit breaker |
| `hooks/obs_utils.py` | ~660 | Session packages — events, manifest, health |
| `hooks/obs-*.py` | 12 files | Lifecycle hooks — reads, writes, bash, cache, etc. |
| `tests/test-statusline.sh` | ~4000 | Shell regression test harness |
| `docs/modules.md` | ~180 | Complete module reference |

## Install / Update / Uninstall

```bash
./install.sh       # fresh install (copies files, patches settings.json)
./update.sh        # git pull + reinstall
./uninstall.sh     # remove all installed files and settings
```

Plugin mode: symlink `~/.claude/plugins/qline → /path/to/qLine`. The installer detects this and skips file copying (imports directly from the plugin dir).

The core deployment uses `scripts/install-core-guarded.sh`. On the throttled
path, `src/statusline-throttle.zsh` becomes `statusline.py` and the Python
renderer becomes `statusline_full.py`; `context_overhead.py` stays beside them.
Where `/bin/zsh` is unavailable, installation keeps direct Python rendering at
`statusline.py`. The guarded installer also supports `--status-source full` for
an explicit direct-renderer installation. The optional throttle is therefore
not a new required dependency for Linux installations.
The installer checks expected deployed digests, stages the replacements, and
retains backups for recovery. It preserves an existing `statusLine` binding and
its `refreshInterval`. The throttle defaults to a ten-second cache lifetime and
invalidates on transcript modification time or size changes. This cache lifetime
is separate from Claude Code's refresh setting.

### Guarded core helper

Use the helper only for the three-file core transaction, and only after recording
the current destination preimages. Its complete interface is:

```bash
scripts/install-core-guarded.sh \
  --dest <existing-destination-directory> \
  --backup-dir <new-backup-directory> \
  --expect-status <lowercase-sha256-or-absent> \
  --expect-full <lowercase-sha256-or-absent> \
  --expect-context <lowercase-sha256-or-absent> \
  [--status-source auto|throttle|full]
```

`--dest`, `--backup-dir`, `--expect-status`, `--expect-full`, and
`--expect-context` are required. Each expected value is either `absent` or a
64-character lowercase SHA-256 digest of the current regular destination file.
`--backup-dir` must not already exist. `--status-source` defaults to `auto`;
it chooses `throttle` when `/bin/zsh` is executable and otherwise chooses
`full`. Explicit `throttle` refuses when zsh is unavailable. The helper rejects
unknown arguments, unsafe source or destination paths, an existing backup path,
and any preimage mismatch before it writes a destination file.

`--expect-full` is a required compatibility change. A former two-digest command
stops with usage error before any replacement. The transaction replaces only
`statusline.py`, `statusline_full.py`, and `context_overhead.py`. On an error
after replacement begins, it restores those three preimages when possible, or
removes a file whose expected preimage was `absent`. If restoration fails, it
reports `rollback incomplete` and retains the backup directory for manual
recovery.

The rollback boundary ends at those three files. It does not undo the enclosing
`install.sh` effects: fallback `obs_utils.py` and `hook_utils.py` copies or
stale-copy removal, the status-line settings write, copied lifecycle hooks, or
hook registration. `./install.sh` without `--no-obs` is a separate full install:
when the qLine plugin is not already active, it copies support files and registers
the 16 observability hooks in `settings.json`. Use
`./install.sh --no-obs` only when its remaining fallback-helper and status-line
settings effects are also intended. The optional details mod has its own
process-local or persistent activation decision.

Do not use old handoff commands that copy `src/statusline.py` directly over the
throttle. Source checkout, core deployment, hook deployment, and the optional
details mod are separate states; a source change does not deploy itself.

## Stop Lines

- Do not run `install.sh`, `update.sh`, `uninstall.sh`, tests, or hook commands based
  on this README alone.
- Do not mutate Claude settings, install hooks, create or remove plugin symlinks,
  copy files, pull remotes, or modify repositories without a separate named operator
  task.
- Treat module counts, test counts, example metrics, cost figures, status output, and
  Claude Code API references as stale until verified against the current checkout and
  live runtime.

## License

MIT
