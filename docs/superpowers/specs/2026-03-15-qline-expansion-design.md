# qLine Expansion Design Spec

## Summary

Expand qLine from 6 modules on 1 line to 12 modules across 2 configurable lines, adding git info, system metrics, and process monitoring. Expands the contract to allow subprocesses and file reads with strict per-collector timeouts.

## Decisions Made

- **Contract expansion:** Allow subprocesses/file reads with 50ms hard timeout per collector. This **deliberately relaxes** the prior visual design spec's "no shell/git" constraint. The prior constraint served a pure-renderer model; the expansion requires system data collection.
- **Multi-line:** 2-line default, configurable to 1-line mode
- **Layout:** Fully configurable via TOML `line1`/`line2` arrays
- **Per-module toggles:** Each module has `enabled` toggle + `show_threshold`
- **Floor thresholds:** Default 0 for all (show when value > 0%)
- **Stale data:** Cache file at `/tmp/qline-cache.json` for dimmed stale display on timeout
- **Platform:** Linux primary (`/proc` filesystem); macOS gracefully degrades (system modules auto-hidden)
- **CPU metric:** Load average divided by cpu_count is an approximation, not true CPU utilization (which requires `/proc/stat` deltas). Acceptable for a status bar.
- **Disk path:** Monitors root (`/`) only. Users with separate `/home` partitions can override via `disk.path` config key.

## Architecture

### Data Flow

```
stdin (JSON bytes)
    ↓ [read_stdin_bounded]
        - select() deadline (0.2s)
        - binary read up to 512KB
    ↓ [normalize]
        - Extract payload fields → state dict
    ↓ [load_config]                    ← BEFORE collectors (they need enabled flags)
        - TOML merge at ~/.config/qline.toml
    ↓ [collect_system_data]            ← NEW: needs theme for enabled checks
        - git: branch, SHA, dirty status
        - cpu: load from /proc/loadavg
        - memory: usage from /proc/meminfo
        - disk: usage from os.statvfs
        - agents: payload tasks + pgrep codex
        - tmux: session/pane counts
    ↓ [render]
        - Module registry maps names → render functions
        - render_line() composes each line
        - 1 or 2 lines joined by \n
    ↓
stdout (1-2 lines ANSI or empty)
    ↓
exit 0
```

### Updated main()

```python
def main() -> None:
    theme = load_config()
    payload = read_stdin_bounded()
    if payload is None:
        return
    state = normalize(payload)
    cache = load_cache()
    collect_system_data(state, theme, cache)
    save_cache(state, cache)
    line = render(state, theme)
    if line:
        print(line)
```

### Module Registry

Replaces hardcoded if/else render chain. Each renderer returns a styled string or `None` (display condition not met).

```python
MODULE_RENDERERS = {
    "model": render_model,
    "dir": render_dir,
    "context_bar": render_context_bar,
    "tokens": render_tokens,
    "cost": render_cost,
    "duration": render_duration,
    "git": render_git,
    "cpu": render_cpu,
    "memory": render_memory,
    "disk": render_disk,
    "agents": render_agents,
    "tmux": render_tmux,
}
```

### render_line()

```python
def render_line(state: dict, theme: dict, modules: list[str]) -> str:
    """Render a single line from a list of module names.

    Looks up each module in MODULE_RENDERERS, calls it with (state, theme),
    collects non-None results, joins with separator. Returns empty string
    if no modules produced output.
    """
    sep_cfg = theme.get("separator", {})
    sep_char = sep_cfg.get("char", "\u2502")
    sep_dim = sep_cfg.get("dim", True)
    sep = style_dim(sep_char) if sep_dim else sep_char

    parts: list[str] = []
    for name in modules:
        renderer = MODULE_RENDERERS.get(name)
        if renderer is None:
            continue  # unknown module name → silently skip
        cfg = theme.get(name, {})
        if not cfg.get("enabled", True):
            continue  # disabled → skip
        result = renderer(state, theme)
        if result is not None:
            parts.append(result)
    return sep.join(parts)
```

### Collector Framework

```python
def collect_system_data(state: dict, theme: dict, cache: dict) -> None:
    """Run all enabled collectors, mutating state in-place.

    Each collector writes its results to state keys. On failure,
    falls back to cached values if fresh enough (<60s).
    """
    collectors = [
        ("git", collect_git),
        ("cpu", collect_cpu),
        ("memory", collect_memory),
        ("disk", collect_disk),
        ("agents", collect_agents),
        ("tmux", collect_tmux),
    ]
    for name, fn in collectors:
        if not theme.get(name, {}).get("enabled", True):
            continue
        try:
            fn(state)
        except Exception:
            _apply_cached(state, cache, name)
```

### Subprocess Helper

```python
def _run_cmd(cmd: list[str], timeout: float = 0.05) -> str | None:
    """Run a command with timeout, return stdout or None on any failure.

    Uses stdout=PIPE, stderr=DEVNULL. On TimeoutExpired, the child is
    killed via Popen.kill() (SIGKILL on POSIX). Non-zero exit → None.
    """
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            text=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
```

Note: `subprocess.run` internally calls `Popen.kill()` + `Popen.communicate()` when `TimeoutExpired` is raised (CPython 3.3+). No orphan processes.

## Default Layout

```
Line 1: model │ dir │ context_bar │ tokens │ cost │ duration
Line 2: git │ cpu │ memory │ disk │ agents │ tmux
```

Line 1 preserves current behavior exactly. Line 2 adds new modules. If all line 2 modules are hidden/disabled, output stays single-line.

## Module Specifications

### Existing Modules (unchanged)

| Module | State key(s) | Display | Show when |
|--------|-------------|---------|-----------|
| model | `model_name` | `󰚩 Opus 4.6 (1M)` | present and non-empty |
| dir | `dir_basename` | `󰝰 qLine` (appends `⊛` inside pill when `is_worktree=True`) | present and non-empty |
| context_bar | `context_used`, `context_total` | `󰋑 █████░░░░░ 50%` | both present, total > 0 |
| tokens | `input_tokens`, `output_tokens` | `↑12.3k ↓4.1k` | both present, at least one > 0 |
| cost | `cost_usd` | `$ 1.23` | present |
| duration | `duration_ms` | `󰥔 1m30s` | present and > 0 |

### New Modules

#### Git (`git`)

- **Source:** Single subprocess: `git -c core.locksTimeout=0 status --porcelain --branch` (gives branch header + dirty files). SHA extracted from `git rev-parse --short HEAD` combined into one `_run_cmd` call via shell-free chaining: run `rev-parse` first (fast, ~2ms), then `status --porcelain --branch` only if rev-parse succeeds. Total budget: 50ms shared across both calls (25ms each).
- **Environment:** Set `GIT_OPTIONAL_LOCKS=0` to prevent blocking on `.git/index.lock`.
- **Display:** `󰊢 main@a3f7b2c*` (dirty asterisk if porcelain output has file changes after the branch header line)
- **Glyph:** `\U000f04a9` (nf-md-source_branch, Supplementary PUA)
- **Color:** `#b48ead` (muted purple, distinct from metrics group)
- **Show when:** inside a git repo (`git rev-parse` succeeds)
- **Hide when:** not a repo, command fails, command times out
- **Edge cases:**
  - Detached HEAD: branch header shows `## HEAD (no branch)` → display `HEAD@a3f7b2c`
  - Empty repo (no commits): `rev-parse HEAD` fails → display `init` with no SHA
  - Branch with slashes (`feature/foo/bar`): display full name, truncate to 20 chars with `…` if longer
  - `.git` is a file (submodule/worktree gitdir link): `git rev-parse` handles natively
  - Bare repo: `git status` fails → module omitted
  - `.git/index.lock` present: `GIT_OPTIONAL_LOCKS=0` prevents blocking
  - `git` binary not installed: `FileNotFoundError` → omitted
  - Shallow clone: `## HEAD (no branch)` → same as detached HEAD

#### Worktree (decorator on `dir`)

- **Source:** `is_worktree` from stdin payload (already normalized)
- **Display:** appends configurable marker **inside** the dir pill, e.g. `󰝰 qLine⊛`
- **Config key:** `dir.worktree_marker` (default `⊛`)
- **No subprocess needed**
- **Show when:** `is_worktree` is `True`

#### CPU (`cpu`)

- **Source:** `/proc/loadavg` field 1 (1-minute load average) divided by `os.cpu_count()` × 100 for percentage. This is an approximation — not true CPU utilization (which requires `/proc/stat` deltas). Acceptable for status bar context.
- **Display:** `CPU 23%`
- **Color:** `#a8d4d0` (shared metrics color)
- **Thresholds:** warn 60%, critical 85% (configurable). Threshold behavior: **color change only** (same as cost module — no suffix, no bold at warn, bold at critical).
- **Show when:** value > `show_threshold` (default 0)
- **Hide when:** `/proc/loadavg` missing (macOS), parse failure, `cpu_count()` returns None, permission denied
- **Edge cases:**
  - `/proc/loadavg` empty or malformed → omitted
  - `cpu_count()` returns `None` → omitted
  - Load astronomically high (>100% per core) → display capped at 999%, threshold colors still apply
  - Container with cgroup CPU limits → load avg reflects container, `cpu_count()` may return host cores (acceptable approximation)

#### Memory (`memory`)

- **Source:** `/proc/meminfo` — `MemTotal` minus `MemAvailable` = used bytes, percentage of total
- **Display:** `MEM 64%`
- **Color:** `#a8d4d0` (shared metrics color)
- **Thresholds:** warn 70%, critical 90% (configurable). Threshold behavior: **color change only** (no suffix, bold at critical).
- **Show when:** value > `show_threshold` (default 0)
- **Hide when:** `/proc/meminfo` missing (macOS), parse failure, `MemTotal` is 0, permission denied
- **Edge cases:**
  - `MemAvailable` missing (older kernels): fall back to `MemFree + Buffers + Cached`
  - Values non-numeric → omitted
  - Container → `MemAvailable` reflects cgroup limit (correct behavior)

#### Disk (`disk`)

- **Source:** `os.statvfs(path)` — `(total - available) / total × 100`. Default path: `"/"`, configurable via `disk.path`.
- **Display:** `DSK 78%`
- **Color:** `#a8d4d0` (shared metrics color)
- **Thresholds:** warn 80%, critical 95% (configurable). Threshold behavior: **color change only** (no suffix, bold at critical).
- **Show when:** value > `show_threshold` (default 0)
- **Hide when:** `statvfs` raises `OSError`, total blocks = 0
- **Edge cases:**
  - NFS-mounted path (slow stat): caught by overall timing
  - Disconnected mount → `OSError` → omitted
  - Path permission denied → `OSError` → omitted

#### Agents (`agents`)

- **Source:** stdin payload task data (Claude agents with non-terminal status) + `pgrep -x codex` (Codex instances, exact name match)
- **Display:** `󰚩 3` (total agent count) — omitted if 0. Note: uses `\U000f04cc` (nf-md-account_group) to differentiate from model's robot glyph.
- **Glyph:** `\U000f04cc` (nf-md-account_group, Supplementary PUA)
- **Color:** `#b48ead` (muted purple, environment group)
- **Thresholds:** warn 5, critical 8 (configurable). Threshold behavior: **color change only** (bold at critical).
- **Show when:** count > 0 (equivalent to `show_threshold = 0`)
- **Hide when:** count = 0, or both data sources fail
- **Edge cases:**
  - Payload has no task data → Claude count = 0
  - Task data is wrong type → ignored (sparse-safe)
  - `pgrep` not installed → `FileNotFoundError` → Codex count = 0, Claude count still works
  - `pgrep` times out → Codex count = 0
  - `pgrep` returns empty → Codex count = 0
  - Zombie processes matching pattern → not matched by `-x` (exact match)

#### Tmux (`tmux`)

- **Source:** `tmux list-sessions 2>/dev/null` (session count from line count) + `tmux list-panes -a 2>/dev/null` (pane count from line count). Both calls share a 50ms budget (25ms each).
- **Display:** `tmux 3s/12p` (3 sessions, 12 panes)
- **Color:** `#8eacb8` (muted teal, environment group)
- **Show when:** tmux is running and at least 1 session exists
- **Hide when:** `tmux` not installed, not running (`no server running` on stderr), command fails/times out
- **Edge cases:**
  - Not inside tmux (`$TMUX` unset) but tmux server running → still shows (monitoring, not "am I in tmux")
  - Session names with special characters → line count is stable regardless
  - Single session, 1 pane → `tmux 1s/1p`
  - `tmux` command times out → omitted
  - 100+ sessions: `list-panes -a` may be slow → 25ms timeout fires, falls back to cache or omits pane count (show sessions only: `tmux 3s`)

## Timing Budget

| Phase | Budget | Expected |
|-------|--------|----------|
| stdin read | 200ms (deadline) | ~1ms typical |
| normalize | — | <1ms |
| load_config | — | <1ms |
| collect_git | 50ms total (25ms × 2 calls) | 5-15ms |
| collect_cpu | — | <1ms (file read) |
| collect_memory | — | <1ms (file read) |
| collect_disk | — | <1ms (statvfs) |
| collect_agents | 50ms timeout (pgrep) | 5-10ms |
| collect_tmux | 50ms total (25ms × 2 calls) | 5-10ms |
| cache read/write | — | <1ms |
| render | — | <1ms |
| **Total worst case** | | **~250ms** (within 300ms) |

## Subprocess Rules

- All use `_run_cmd()` helper (defined above)
- `stdout=subprocess.PIPE, stderr=subprocess.DEVNULL` — no `capture_output` conflict
- Direct command lists, never `shell=True`
- `close_fds=True` (default on POSIX) — no fd leaks
- `timeout` per call — `Popen.kill()` (SIGKILL on POSIX) called on expiry by CPython
- `FileNotFoundError` (binary missing) → caught, module omitted
- Non-zero exit code → `None` returned
- Git calls set `GIT_OPTIONAL_LOCKS=0` in environment to prevent lock contention

## Cache Lifecycle

### Schema

```json
{
  "version": 1,
  "updated_at": 1710000000.0,
  "modules": {
    "git": {
      "value": {"branch": "main", "sha": "a3f7b2c", "dirty": true},
      "timestamp": 1710000000.0
    },
    "cpu": {
      "value": {"percent": 23},
      "timestamp": 1710000000.0
    }
  }
}
```

Each module entry has `value` (the data that was collected) and `timestamp` (monotonic-compatible float from `time.time()`).

### Read/Write Flow

1. **Load cache** at start of `main()` — `load_cache()` reads `/tmp/qline-cache.json`, returns `{}` on any failure
2. **Collectors run** — each writes results to `state` dict. On success, also updates cache dict entry with fresh value + timestamp
3. **On collector failure** — `_apply_cached(state, cache, name)` checks if cache entry exists and is <60s old. If so, copies cached value into `state` and sets `state[f"{name}_stale"] = True` flag for dimmed rendering
4. **Save cache** after all collectors — `save_cache(state, cache)` writes atomically via `tempfile.NamedTemporaryFile(dir="/tmp", delete=False)` + `os.rename()` (same-filesystem atomic rename guaranteed)
5. **Write failure** (read-only fs, `/tmp` full) → silently skip, no error

### Staleness Rules

- Cache entry < 60s old → use dimmed (stale indicator)
- Cache entry >= 60s old → discard, module omitted
- Cache file missing → all modules fresh-or-omitted, no stale display
- Cache file corrupted (bad JSON) → treated as empty
- Cache from older schema version (missing `version` key or wrong value) → treated as empty
- Concurrent writers: last writer wins, atomic rename prevents partial reads — acceptable since system metrics are machine-wide

## Multi-line Rendering

```python
def render(state: dict, theme: dict) -> str:
    layout = theme.get("layout", {})
    num_lines = max(1, min(2, layout.get("lines", 2)))  # clamp to 1-2
    line1_modules = layout.get("line1", DEFAULT_LINE1)
    line2_modules = layout.get("line2", DEFAULT_LINE2)

    if not isinstance(line1_modules, list):
        line1_modules = DEFAULT_LINE1
    if not isinstance(line2_modules, list):
        line2_modules = DEFAULT_LINE2

    line1 = render_line(state, theme, line1_modules)

    if num_lines == 1:
        line2_parts = render_line(state, theme, line2_modules)
        if line1 and line2_parts:
            return line1 + sep + line2_parts
        return line1 or line2_parts or ""

    line2 = render_line(state, theme, line2_modules)
    if line1 and line2:
        return line1 + "\n" + line2
    return line1 or line2 or ""
```

**Empty line suppression:** If all modules on a line are hidden/disabled/omitted, that line is not emitted. No blank lines, no trailing newlines.

**Single-line fallback:** `lines = 1` merges both layout arrays into one line with separator joining.

**Clamping:** `lines` is clamped to `[1, 2]` — values ≤0 become 1, values ≥3 become 2.

## Intelligent UI/UX

### Progressive Disclosure

System modules only appear when values exceed `show_threshold` (default 0 for all — effectively always visible when collectors succeed). Configurable per module for users who want a cleaner bar during idle.

### Contextual Density

When `lines = 1`, auto-abbreviate system module labels for space:
- `memory` → `M:64%`
- `cpu` → `C:23%`
- `disk` → `D:78%`
- Git branch truncated to 12 chars with `…`

In two-line mode, full labels used.

### Stale Data

If a collector failed on this invocation but cache has a recent value (<60s old):
- Show the cached value **dimmed** (ANSI dim attribute)
- Set `state["{module}_stale"] = True` — renderer checks this flag
- If cache is missing or stale (>60s), omit the module instead

See Cache Lifecycle section for implementation details.

### Color Coherence

- System metrics (CPU/MEM/DSK) share base color `#a8d4d0` — read as a group
- Environment modules (git, agents) share `#b48ead` — distinct from metrics
- Tmux gets `#8eacb8` — muted, infrastructure feel
- Warn/critical colors shared across all thresholded modules for consistency

### Threshold Behavior (all thresholded modules)

Consistent across context_bar, cost, CPU, MEM, DSK, agents:
- **Normal:** module color, no bold
- **Warn (≥ warn_threshold):** `warn_color`, no bold. Context bar adds `~` suffix.
- **Critical (≥ critical_threshold):** `critical_color`, bold. Context bar adds `!` suffix.

### Graceful Degradation

```
Two-line → one-line (if line2 empty) → empty (if everything hidden)
```

Never shows a broken or partial line. If a glyph renders as tofu, the text label (`CPU`, `MEM`, `DSK`, `tmux`) still conveys meaning.

## TOML Configuration

All keys optional. Missing file or any read error = use defaults silently. Path: `~/.config/qline.toml` (hardcoded, does not follow `$XDG_CONFIG_HOME` — intentional for simplicity).

```toml
[layout]
lines = 2
line1 = ["model", "dir", "context_bar", "tokens", "cost", "duration"]
line2 = ["git", "cpu", "memory", "disk", "agents", "tmux"]

[model]
enabled = true
glyph = "󰚩 "
color = "#d8dee9"
bg = "#3b4252"

[dir]
enabled = true
glyph = "󰝰 "
color = "#9bb8d3"
bg = "#2e3440"
worktree_marker = "⊛"

[context_bar]
enabled = true
glyph = "󰋑 "
color = "#b5d4a0"
bg = "#2e3440"
width = 10
warn_threshold = 40.0
warn_color = "#f0d399"
critical_threshold = 70.0
critical_color = "#d06070"
show_threshold = 0

[tokens]
enabled = true
color = "#a8d4d0"
bg = "#2e3440"

[cost]
enabled = true
glyph = "$ "
color = "#e0956a"
bg = "#2e3440"
warn_threshold = 2.0
warn_color = "#f0d399"
critical_threshold = 5.0
critical_color = "#d06070"

[duration]
enabled = true
glyph = "󰥔 "
color = "#8eacb8"
bg = "#2e3440"

[git]
enabled = true
glyph = "󰊢 "
color = "#b48ead"
bg = "#2e3440"
dirty_marker = "*"

[cpu]
enabled = true
glyph = "CPU "
color = "#a8d4d0"
bg = "#2e3440"
warn_threshold = 60.0
critical_threshold = 85.0
warn_color = "#f0d399"
critical_color = "#d06070"
show_threshold = 0

[memory]
enabled = true
glyph = "MEM "
color = "#a8d4d0"
bg = "#2e3440"
warn_threshold = 70.0
critical_threshold = 90.0
warn_color = "#f0d399"
critical_color = "#d06070"
show_threshold = 0

[disk]
enabled = true
glyph = "DSK "
color = "#a8d4d0"
bg = "#2e3440"
path = "/"
warn_threshold = 80.0
critical_threshold = 95.0
warn_color = "#f0d399"
critical_color = "#d06070"
show_threshold = 0

[agents]
enabled = true
glyph = "󰄴 "
color = "#b48ead"
bg = "#2e3440"
warn_threshold = 5
critical_threshold = 8
warn_color = "#f0d399"
critical_color = "#d06070"
show_threshold = 0

[tmux]
enabled = true
glyph = "tmux "
color = "#8eacb8"
bg = "#2e3440"

[separator]
char = "│"
dim = true

[pill]
left = ""
right = ""
```

### Config Edge Cases

| Scenario | Behavior |
|----------|----------|
| `enabled = false` on every module | Empty output |
| `lines` set to 0 or negative | Clamped to 1 |
| `lines` set to 3+ | Clamped to 2 |
| `line1`/`line2` not arrays | Use defaults |
| Unknown module name in layout array | Silently ignored |
| Duplicate module in layout array | Rendered twice (no crash) |
| Empty layout array `line1 = []` | That line produces nothing |
| Module on line2 that's normally on line1 | Renders on line2 correctly |
| Threshold set to negative | Treat as 0 |
| Threshold warn > critical | Both trigger at their values independently |
| Missing `layout` section entirely | Use defaults |

## Display Conditions

| Module | Show when | Hide when |
|--------|-----------|-----------|
| model | `model_name` present and non-empty | missing/empty |
| dir | `dir_basename` present and non-empty | missing/empty |
| context_bar | `context_used` and `context_total` both present, total > 0 | either missing or total = 0 |
| tokens | both `input_tokens` and `output_tokens` present, at least one > 0 | both 0 or either missing |
| cost | `cost_usd` present | missing |
| duration | `duration_ms` present and > 0 | missing or 0 |
| git | inside a git repo (rev-parse succeeds) | not a repo, command fails/times out |
| worktree | `is_worktree` is `True` in payload | `False`, missing, not in payload |
| cpu | value > `show_threshold` (default 0) | below threshold, `/proc` missing, parse failure |
| memory | value > `show_threshold` (default 0) | below threshold, `/proc` missing, parse failure |
| disk | value > `show_threshold` (default 0) | below threshold, `statvfs` fails |
| agents | count > `show_threshold` (default 0) | count = 0, both sources fail |
| tmux | at least 1 session running | not installed, no sessions, fails/times out |

## Resilience

| Scenario | Behavior |
|----------|----------|
| Single collector hangs past 50ms | Killed via `Popen.kill()` (SIGKILL), other collectors still run |
| All collectors fail simultaneously | Line 1 renders normally from payload data, line 2 shows cached (dimmed) or omitted |
| `/proc` mounted but stale (container/VM) | Values validated for sane ranges (0-100%), out-of-range → omitted |
| `git` repo locked (`.git/index.lock`) | `GIT_OPTIONAL_LOCKS=0` prevents blocking; if still fails → omitted |
| Collector output has newlines/control chars | Sanitized via `_sanitize_fragment()` |
| Payload shape changes between Claude versions | Sparse-safe: unknown fields ignored, missing → omitted |
| TOML config changes mid-session | Re-read every invocation — picks up changes live |

## Durability

| Concern | Approach |
|---------|----------|
| Claude updates payload schema | Normalizer is additive — new fields don't break old, old fields fallback |
| Nerd Font glyphs break in future | All glyphs configurable via TOML — swap to ASCII without code changes |
| Linux-only `/proc` paths | Guard with try/except — macOS users get system modules auto-hidden |
| Python 3.11+ required (`tomllib`) | Document in install script |
| tmux version differences | Parse output defensively — line count, not column parsing |
| Git version differences | Porcelain/plumbing commands stable across versions |

## Performance Guarantees

| Condition | Behavior |
|-----------|----------|
| Total render > 300ms | Claude Code kills process — exit 0 implicit |
| Invoked 3x/second | Stateless — no accumulation, no leaks |
| 100+ tmux sessions / 50+ agents | Count-based output — render time constant |
| Branch name 100+ chars | Truncate to 20 chars with `…` |
| Huge payload (512KB) | Already capped by `MAX_STDIN_BYTES` |
| Large git repo (100k+ files) | `git status` may be slow — 25ms timeout fires, falls back to cache |

## Filesystem Edge Cases

| Condition | Behavior |
|-----------|----------|
| Read-only filesystem | Cache write fails → skip caching, no error |
| `/tmp` full | Cache write fails → skip caching |
| `/proc` missing (macOS, container) | CPU/MEM omitted |
| NFS-mounted home (slow stat) | `statvfs` on configured path (default `/`), not home |
| Symlinked/file `.git` | `git rev-parse` handles natively |
| cwd deleted while running | `statvfs` uses configured path. Git may fail → omitted |

## Process & Environment Edge Cases

| Condition | Behavior |
|-----------|----------|
| No PATH set | `FileNotFoundError` → caught, module omitted |
| Binaries not installed | `FileNotFoundError` → caught, module omitted |
| Inside Docker container | `/proc` reflects cgroup limits (correct) |
| Inside WSL | All collectors work the same |
| Multiple Claude sessions | Stateless — no shared state conflicts |
| Cache race (concurrent write/read) | Atomic rename prevents partial reads; last writer wins (acceptable for machine-wide metrics) |
| SIGPIPE | `BrokenPipeError` caught by top-level try/except, exit 0 |

## Data Integrity

| Condition | Behavior |
|-----------|----------|
| Payload fields change type | Sparse-safe normalizer validates types every time |
| Git SHA changes between invocations | Fresh collection each time, no git state cached |
| Clock skew / NTP jump | Cache staleness worst case: treated as stale → fresh collection |
| Non-UTF-8 locale | Subprocess decode with `errors="replace"` |
| Cache file corrupted | `json.loads` fails → treated as empty |
| Cache from older version | Missing `version` key or wrong value → treated as empty |

## Concurrency Safety

| Condition | Behavior |
|-----------|----------|
| Two sessions invoke simultaneously | Independent processes, own stdin — no conflict |
| Session A writes cache, B reads | Atomic rename prevents partial reads |
| Collector subprocess fd leaks | `close_fds=True` (POSIX default) |

## Testing Strategy

### Existing Tests (preserved)

All 121 existing tests remain unchanged. Refactor from monolithic `render()` to `render_line()` + module registry validated by existing assertions.

### New Test Sections

#### Collector Tests (~30 tests)

**Git:**
- Happy: repo with branch + SHA + clean
- Happy: repo with dirty files → asterisk
- Edge: detached HEAD → `HEAD@abc1234`
- Edge: empty repo (no commits) → `init`
- Edge: branch with slashes → truncated with `…`
- Edge: not a git repo → omitted
- Edge: `git` not installed → omitted
- Edge: command times out → omitted
- Edge: bare repo → omitted
- Edge: shallow clone → same as detached HEAD
- Edge: `GIT_OPTIONAL_LOCKS=0` set in subprocess env

**CPU:**
- Happy: valid `/proc/loadavg` → percentage
- Edge: file missing → omitted
- Edge: file empty → omitted
- Edge: `cpu_count()` returns None → omitted
- Edge: extremely high load → capped display, threshold colors apply

**Memory:**
- Happy: valid `/proc/meminfo` → percentage
- Edge: file missing → omitted
- Edge: `MemAvailable` missing → fallback to `MemFree+Buffers+Cached`
- Edge: `MemTotal` is 0 → omitted
- Edge: malformed values → omitted

**Disk:**
- Happy: `statvfs("/")` → percentage
- Edge: `OSError` → omitted
- Edge: total blocks = 0 → omitted
- Edge: custom path via config

**Agents:**
- Happy: payload with 3 running tasks + 2 codex → `5`
- Edge: no task data in payload → Claude count = 0
- Edge: `pgrep` not installed → Codex count = 0, Claude count still works
- Edge: `pgrep` times out → Codex count = 0
- Edge: count = 0 → omitted

**Tmux:**
- Happy: 3 sessions, 12 panes → `3s/12p`
- Edge: not installed → omitted
- Edge: server not running → omitted
- Edge: command times out → omitted
- Edge: single session, 1 pane → `1s/1p`
- Edge: list-panes times out but list-sessions succeeds → `3s` (sessions only)

#### Layout Tests (~12 tests)

- Single-line mode: all modules on one line
- Two-line mode: correct line assignment
- Empty line2 suppression → single line output
- Empty line1 suppression → only line2
- Both lines empty → empty output
- Unknown module name → silently ignored
- Duplicate module → rendered twice
- Empty layout array → that line empty
- Module moved between lines → renders correctly
- `lines = 0` → clamped to 1
- `lines = 5` → clamped to 2
- `line1`/`line2` not arrays → use defaults

#### Toggle Tests (~8 tests)

- `enabled = false` hides module
- `enabled = false` on all modules → empty output
- `show_threshold` hides module below value
- `show_threshold = 0` shows when value > 0
- Disabled module not collected (no subprocess spawned)
- Module removed from layout arrays → hidden
- Module in layout but `enabled = false` → hidden
- Default config (no TOML file) → all enabled

#### Failure Mode Tests (~15 tests)

- All subprocesses time out simultaneously → line 1 renders, line 2 cached/omitted
- Non-zero exit code → module omitted
- Garbage stdout from subprocess → module omitted
- Binary exists but permission denied → module omitted
- PATH empty/broken → omitted
- `/proc` permission denied → omitted
- Cache write fails (read-only) → renders without cache
- Cache file corrupted → treated as empty
- Cache from different schema version → treated as empty
- Concurrent cache write/read → no partial reads (atomic rename)
- SIGPIPE → exit 0
- Malformed TOML with new sections → defaults for new sections
- Extremely long subprocess output → bounded by capture_output

#### Stale Data Tests (~7 tests)

- Collector succeeds → value cached with timestamp
- Collector fails, cache fresh (<60s) → dimmed value shown
- Collector fails, cache stale (>60s) → omitted
- Cache file missing → omitted on failure
- Cache write atomic (no partial JSON via tempfile + rename)
- Cache schema version mismatch → treated as empty
- Multiple modules cached independently

#### Contextual Density Tests (~5 tests)

- `lines = 1`: CPU shows as `C:23%`
- `lines = 1`: MEM shows as `M:64%`
- `lines = 1`: DSK shows as `D:78%`
- `lines = 1`: branch truncated to 12 chars
- `lines = 2`: full labels used

**Total new tests: ~77**
**Total tests: ~198**

## Constraints Preserved

- Single or dual stdout line (or empty output)
- No stderr on normal execution
- Exit 0 on all recoverable failures
- One bounded stdin read
- Byte-capped input (512KB)
- 200ms read deadline
- NO_COLOR convention respected

## Constraints Relaxed (from prior spec)

- **Subprocesses allowed:** git, pgrep, tmux (with 50ms timeouts)
- **File reads allowed:** `/proc/loadavg`, `/proc/meminfo` (no timeout needed, <1ms)
- **Cache file:** `/tmp/qline-cache.json` written atomically

## Deferred

- Usage limits (API + keyring + cache)
- Hook health badge
- `--explain` debug surface
- Severity-driven module reordering
- `glyph_set` config for BMP PUA vs MDI vs ASCII presets
- `$XDG_CONFIG_HOME` support for config path
- `$COLORTERM` / `$TERM` truecolor capability detection
