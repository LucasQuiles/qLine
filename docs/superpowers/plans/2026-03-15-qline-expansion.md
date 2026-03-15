# qLine Expansion Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand qLine from 6 modules on 1 line to 12 modules across 2 configurable lines, adding git, CPU, memory, disk, agents, and tmux modules.

**Architecture:** Refactor the monolithic `render()` into a module registry + `render_line()` pattern. Add a `collect_system_data()` phase that runs file reads and subprocesses with 50ms timeouts. Add a JSON cache at `/tmp/qline-cache.json` for stale-data dimming on collector failures.

**Tech Stack:** Python 3.11+ (stdlib only: tomllib, subprocess, json, os, select, tempfile)

**Spec:** `docs/superpowers/specs/2026-03-15-qline-expansion-design.md`

---

## Chunk 1: Architecture Refactor — Module Registry + Multi-line

Refactor renderer from hardcoded modules to a registry-driven pattern with configurable multi-line layout. All 121 existing tests must continue passing. No new collectors yet.

### Task 1: Add layout config to DEFAULT_THEME

**Files:**
- Modify: `src/statusline.py:38-86` (DEFAULT_THEME)

- [ ] **Step 1: Add layout and new module defaults to DEFAULT_THEME**

Add after the `pill` entry in DEFAULT_THEME:

```python
    "layout": {
        "lines": 2,
        "line1": ["model", "dir", "context_bar", "tokens", "cost", "duration"],
        "line2": ["git", "cpu", "memory", "disk", "agents", "tmux"],
    },
    "git": {
        "enabled": True,
        "glyph": "\U000f04a9 ",
        "color": "#b48ead",
        "bg": "#2e3440",
        "dirty_marker": "*",
    },
    "cpu": {
        "enabled": True,
        "glyph": "CPU ",
        "color": "#a8d4d0",
        "bg": "#2e3440",
        "warn_threshold": 60.0,
        "critical_threshold": 85.0,
        "warn_color": "#f0d399",
        "critical_color": "#d06070",
        "show_threshold": 0,
    },
    "memory": {
        "enabled": True,
        "glyph": "MEM ",
        "color": "#a8d4d0",
        "bg": "#2e3440",
        "warn_threshold": 70.0,
        "critical_threshold": 90.0,
        "warn_color": "#f0d399",
        "critical_color": "#d06070",
        "show_threshold": 0,
    },
    "disk": {
        "enabled": True,
        "glyph": "DSK ",
        "color": "#a8d4d0",
        "bg": "#2e3440",
        "path": "/",
        "warn_threshold": 80.0,
        "critical_threshold": 95.0,
        "warn_color": "#f0d399",
        "critical_color": "#d06070",
        "show_threshold": 0,
    },
    "agents": {
        "enabled": True,
        "glyph": "\U000f04cc ",
        "color": "#b48ead",
        "bg": "#2e3440",
        "warn_threshold": 5,
        "critical_threshold": 8,
        "warn_color": "#f0d399",
        "critical_color": "#d06070",
        "show_threshold": 0,
    },
    "tmux": {
        "enabled": True,
        "glyph": "tmux ",
        "color": "#8eacb8",
        "bg": "#2e3440",
    },
```

Also add `"enabled": True` to the existing model, dir, context_bar, tokens, cost, and duration dicts so all modules have the key.

- [ ] **Step 2: Update load_config to handle layout section**

The existing shallow merge already handles new sections — verify `layout` dict merges correctly. The `layout` section contains `line1` and `line2` as lists, which TOML parses as arrays. No code change needed — the existing `defaults.update(user[section])` handles it.

- [ ] **Step 3: Run existing tests**

Run: `bash tests/test-statusline.sh`
Expected: 121/121 pass (DEFAULT_THEME changes are additive)

- [ ] **Step 4: Commit**

```bash
git add src/statusline.py
git commit -m "feat: add layout config and new module defaults to theme"
```

### Task 2: Extract individual module renderers

**Files:**
- Modify: `src/statusline.py:363-425` (render function → individual renderers)

- [ ] **Step 1: Create individual render functions**

Extract each module block from `render()` into its own function. Each takes `(state, theme)` and returns `str | None`:

```python
def render_model(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    model_name = state.get("model_name")
    if not model_name:
        return None
    m_cfg = theme.get("model", {})
    text = f"{m_cfg.get('glyph', '')}{_sanitize_fragment(model_name)}"
    return _pill(text, m_cfg, bold=m_cfg.get("bold", False), theme=theme)


def render_dir(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    dir_basename = state.get("dir_basename")
    if not dir_basename:
        return None
    d_cfg = theme.get("dir", {})
    text = f"{d_cfg.get('glyph', '')}{_sanitize_fragment(dir_basename)}"
    return _pill(text, d_cfg, theme=theme)


def render_context_bar(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    if "context_used" not in state or "context_total" not in state:
        return None
    pct = (state["context_used"] * 100) // state["context_total"]
    return render_bar(pct, theme)


def render_tokens(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    if "input_tokens" not in state or "output_tokens" not in state:
        return None
    return format_tokens(state["input_tokens"], state["output_tokens"], theme)


def render_cost(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    if "cost_usd" not in state:
        return None
    c_cfg = theme.get("cost", {})
    cost_val = state["cost_usd"]
    cost_text = f"{c_cfg.get('glyph', '')}{_format_cost(cost_val)}"
    warn_t = c_cfg.get("warn_threshold", 2.0)
    crit_t = c_cfg.get("critical_threshold", 5.0)
    if cost_val >= crit_t:
        return _pill(cost_text, c_cfg, c_cfg.get("critical_color", "#d06070"), True, theme)
    elif cost_val >= warn_t:
        return _pill(cost_text, c_cfg, c_cfg.get("warn_color", "#f0d399"), theme=theme)
    return _pill(cost_text, c_cfg, theme=theme)


def render_duration(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    if "duration_ms" not in state:
        return None
    dur_cfg = theme.get("duration", {})
    text = f"{dur_cfg.get('glyph', '')}{_format_duration(state['duration_ms'])}"
    return _pill(text, dur_cfg, theme=theme)
```

- [ ] **Step 2: Create placeholder renderers for new modules**

These return `None` for now — they'll be implemented in later tasks:

```python
def render_git(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    return None

def render_cpu(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    return None

def render_memory(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    return None

def render_disk(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    return None

def render_agents(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    return None

def render_tmux(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    return None
```

- [ ] **Step 3: Create MODULE_RENDERERS registry**

```python
MODULE_RENDERERS: dict[str, Any] = {
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

- [ ] **Step 4: Run existing tests**

Run: `bash tests/test-statusline.sh`
Expected: 121/121 pass (renderers are defined but not yet wired)

- [ ] **Step 5: Commit**

```bash
git add src/statusline.py
git commit -m "refactor: extract individual module render functions"
```

### Task 3: Implement render_line() and rewrite render()

**Files:**
- Modify: `src/statusline.py` (replace `render()` body)

- [ ] **Step 1: Write render_line()**

```python
DEFAULT_LINE1 = ["model", "dir", "context_bar", "tokens", "cost", "duration"]
DEFAULT_LINE2 = ["git", "cpu", "memory", "disk", "agents", "tmux"]


def render_line(state: dict[str, Any], theme: dict[str, Any],
                modules: list[str]) -> str:
    """Render a single line from a list of module names."""
    sep_cfg = theme.get("separator", {})
    sep_char = sep_cfg.get("char", "\u2502")
    sep_dim = sep_cfg.get("dim", True)
    sep = style_dim(sep_char) if sep_dim else sep_char

    parts: list[str] = []
    for name in modules:
        renderer = MODULE_RENDERERS.get(name)
        if renderer is None:
            continue
        cfg = theme.get(name, {})
        if not cfg.get("enabled", True):
            continue
        result = renderer(state, theme)
        if result is not None:
            parts.append(result)
    return sep.join(parts)
```

- [ ] **Step 2: Rewrite render() to use render_line()**

```python
def render(state: dict[str, Any], theme: dict[str, Any] | None = None) -> str:
    """Render one or two status lines from normalized state."""
    if theme is None:
        theme = DEFAULT_THEME

    layout = theme.get("layout", {})
    num_lines = max(1, min(2, layout.get("lines", 2)))
    line1_modules = layout.get("line1", DEFAULT_LINE1)
    line2_modules = layout.get("line2", DEFAULT_LINE2)

    if not isinstance(line1_modules, list):
        line1_modules = DEFAULT_LINE1
    if not isinstance(line2_modules, list):
        line2_modules = DEFAULT_LINE2

    sep_cfg = theme.get("separator", {})
    sep_char = sep_cfg.get("char", "\u2502")
    sep_dim = sep_cfg.get("dim", True)
    sep = style_dim(sep_char) if sep_dim else sep_char

    line1 = render_line(state, theme, line1_modules)

    if num_lines == 1:
        line2 = render_line(state, theme, line2_modules)
        if line1 and line2:
            return line1 + sep + line2
        return line1 or line2 or ""

    line2 = render_line(state, theme, line2_modules)
    if line1 and line2:
        return line1 + "\n" + line2
    return line1 or line2 or ""
```

- [ ] **Step 3: Run existing tests**

Run: `bash tests/test-statusline.sh`
Expected: 121/121 pass. The render output is identical because line2 modules all return None (placeholders), so only line1 is emitted — same as before.

- [ ] **Step 4: Commit**

```bash
git add src/statusline.py
git commit -m "refactor: replace monolithic render with registry-driven render_line"
```

### Task 4: Add layout and multi-line tests

**Files:**
- Modify: `tests/test-statusline.sh` (add layout section)

- [ ] **Step 1: Add layout test section**

Add after the `command` section, before the summary:

```bash
# ======================================================================
# SECTION: layout — multi-line and module ordering tests
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "layout" ]; then
echo "--- Layout Tests ---"

# L-01: Default two-line mode with no line2 data → single line output
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
state = {'model_name': 'Opus', 'cost_usd': 0.50}
line = render(state, DEFAULT_THEME)
print(repr(line))
")
assert_not_contains "L-01: no newline when line2 empty" "$OUT" "\\\\n"

# L-02: Single-line mode merges lines
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
import copy
theme = copy.deepcopy(DEFAULT_THEME)
theme['layout']['lines'] = 1
state = {'model_name': 'Opus'}
line = render(state, theme)
print(line)
")
assert_contains "L-02: single line mode" "$OUT" "Opus"
assert_not_contains "L-02b: no newline" "$OUT" $'\n'

# L-03: lines clamped to 1 when 0
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
import copy
theme = copy.deepcopy(DEFAULT_THEME)
theme['layout']['lines'] = 0
state = {'model_name': 'Opus'}
line = render(state, theme)
print(line)
")
assert_contains "L-03: lines=0 still renders" "$OUT" "Opus"

# L-04: lines clamped to 2 when 5
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
import copy
theme = copy.deepcopy(DEFAULT_THEME)
theme['layout']['lines'] = 5
state = {'model_name': 'Opus'}
line = render(state, theme)
print(line)
")
assert_contains "L-04: lines=5 still renders" "$OUT" "Opus"

# L-05: Unknown module name silently ignored
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
import copy
theme = copy.deepcopy(DEFAULT_THEME)
theme['layout']['line1'] = ['nonexistent', 'model']
state = {'model_name': 'Opus'}
line = render(state, theme)
print(line)
")
assert_contains "L-05: unknown module ignored" "$OUT" "Opus"

# L-06: Empty layout arrays → empty output
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
import copy
theme = copy.deepcopy(DEFAULT_THEME)
theme['layout']['line1'] = []
theme['layout']['line2'] = []
state = {'model_name': 'Opus'}
line = render(state, theme)
print(repr(line))
")
assert_equals "L-06: empty layout → empty" "$OUT" "''"

# L-07: Module moved between lines
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
import copy
theme = copy.deepcopy(DEFAULT_THEME)
theme['layout']['line1'] = ['cost']
theme['layout']['line2'] = ['model']
theme['layout']['lines'] = 2
state = {'model_name': 'Opus', 'cost_usd': 1.0}
line = render(state, theme)
parts = line.split(chr(10))
print(f'lines={len(parts)}')
print(f'line1_has_cost={\"1.00\" in parts[0]}')
print(f'line2_has_model={\"Opus\" in parts[1]}')
")
assert_contains "L-07a: two lines" "$OUT" "lines=2"
assert_contains "L-07b: cost on line1" "$OUT" "line1_has_cost=True"
assert_contains "L-07c: model on line2" "$OUT" "line2_has_model=True"

# L-08: enabled=false hides module
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
import copy
theme = copy.deepcopy(DEFAULT_THEME)
theme['model']['enabled'] = False
state = {'model_name': 'Opus', 'cost_usd': 1.0}
line = render(state, theme)
print(line)
")
assert_not_contains "L-08: disabled model hidden" "$OUT" "Opus"
assert_contains "L-08b: cost still shows" "$OUT" "1.00"

# L-09: line1/line2 not arrays → use defaults
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
import copy
theme = copy.deepcopy(DEFAULT_THEME)
theme['layout']['line1'] = 'not_a_list'
state = {'model_name': 'Opus'}
line = render(state, theme)
print(line)
")
assert_contains "L-09: non-array fallback" "$OUT" "Opus"

# L-10: Both lines empty → empty output
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
import copy
theme = copy.deepcopy(DEFAULT_THEME)
for mod in ['model','dir','context_bar','tokens','cost','duration','git','cpu','memory','disk','agents','tmux']:
    theme[mod]['enabled'] = False
state = {'model_name': 'Opus', 'cost_usd': 1.0}
line = render(state, theme)
print(repr(line))
")
assert_equals "L-10: all disabled → empty" "$OUT" "''"

echo ""
fi
```

- [ ] **Step 2: Run all tests**

Run: `bash tests/test-statusline.sh`
Expected: 131/131 pass (121 existing + 10 new layout)

- [ ] **Step 3: Commit**

```bash
git add tests/test-statusline.sh
git commit -m "test: add layout and multi-line rendering tests"
```

---

## Chunk 2: File-based Collectors — CPU, Memory, Disk

Add collectors that read `/proc` files and call `os.statvfs()`. No subprocesses. Testable via mock proc directory.

### Task 5: Add subprocess helper and proc dir override

**Files:**
- Modify: `src/statusline.py` (add imports, helpers)

- [ ] **Step 1: Add imports**

Add to the imports section:

```python
import subprocess
import tempfile
import time
```

- [ ] **Step 2: Add PROC_DIR override constant**

```python
PROC_DIR = os.environ.get("QLINE_PROC_DIR", "/proc")
```

- [ ] **Step 3: Add _run_cmd helper**

```python
def _run_cmd(cmd: list[str], timeout: float = 0.05,
             env: dict[str, str] | None = None) -> str | None:
    """Run a command with timeout, return stdout or None on any failure."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            return None
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
```

- [ ] **Step 4: Commit**

```bash
git add src/statusline.py
git commit -m "feat: add subprocess helper and proc dir override"
```

### Task 6: Implement CPU collector and renderer

**Files:**
- Modify: `src/statusline.py`
- Modify: `tests/test-statusline.sh`

- [ ] **Step 1: Write CPU collector tests**

Add a new `collector` test section:

```bash
# ======================================================================
# SECTION: collector — system data collector tests
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "collector" ]; then
echo "--- Collector Tests ---"

# COL-01: CPU from valid loadavg
MOCK_PROC=$(mktemp -d)
echo "2.50 1.20 0.80 1/234 5678" > "$MOCK_PROC/loadavg"
OUT=$(QLINE_PROC_DIR="$MOCK_PROC" run_py "
import os
os.environ['QLINE_PROC_DIR'] = '$MOCK_PROC'
import statusline
statusline.PROC_DIR = '$MOCK_PROC'
state = {}
statusline.collect_cpu(state)
print(state.get('cpu_percent', 'ABSENT'))
")
rm -rf "$MOCK_PROC"
# 2.50 / cpu_count * 100 — varies by machine, just check it's a number
TOTAL=$((TOTAL + 1))
if echo "$OUT" | grep -qE '^[0-9]+$'; then
    echo "  PASS: COL-01: CPU percent is a number ($OUT)"
    PASS=$((PASS + 1))
else
    echo "  FAIL: COL-01: CPU percent not a number ($OUT)"
    FAIL=$((FAIL + 1))
fi

# COL-02: CPU from missing file
MOCK_PROC=$(mktemp -d)
OUT=$(QLINE_PROC_DIR="$MOCK_PROC" run_py "
import statusline
statusline.PROC_DIR = '$MOCK_PROC'
state = {}
statusline.collect_cpu(state)
print(state.get('cpu_percent', 'ABSENT'))
")
rm -rf "$MOCK_PROC"
assert_equals "COL-02: CPU missing file" "$OUT" "ABSENT"

# COL-03: CPU from empty file
MOCK_PROC=$(mktemp -d)
echo "" > "$MOCK_PROC/loadavg"
OUT=$(QLINE_PROC_DIR="$MOCK_PROC" run_py "
import statusline
statusline.PROC_DIR = '$MOCK_PROC'
state = {}
statusline.collect_cpu(state)
print(state.get('cpu_percent', 'ABSENT'))
")
rm -rf "$MOCK_PROC"
assert_equals "COL-03: CPU empty file" "$OUT" "ABSENT"

echo ""
fi
```

- [ ] **Step 2: Implement collect_cpu**

```python
def collect_cpu(state: dict[str, Any]) -> None:
    """Collect CPU load percentage from /proc/loadavg."""
    try:
        with open(os.path.join(PROC_DIR, "loadavg")) as f:
            content = f.read().strip()
        if not content:
            return
        load_1m = float(content.split()[0])
        cpus = os.cpu_count()
        if not cpus or cpus <= 0:
            return
        pct = int((load_1m / cpus) * 100)
        state["cpu_percent"] = max(0, min(999, pct))
    except Exception:
        pass
```

- [ ] **Step 3: Implement render_cpu**

Replace the placeholder:

```python
def render_cpu(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    if "cpu_percent" not in state:
        return None
    cfg = theme.get("cpu", {})
    pct = state["cpu_percent"]
    show_t = cfg.get("show_threshold", 0)
    if pct <= show_t:
        return None
    text = f"{cfg.get('glyph', 'CPU ')}{pct}%"
    warn_t = cfg.get("warn_threshold", 60.0)
    crit_t = cfg.get("critical_threshold", 85.0)
    if pct >= crit_t:
        return _pill(text, cfg, cfg.get("critical_color", "#d06070"), True, theme)
    elif pct >= warn_t:
        return _pill(text, cfg, cfg.get("warn_color", "#f0d399"), theme=theme)
    return _pill(text, cfg, theme=theme)
```

- [ ] **Step 4: Run tests**

Run: `bash tests/test-statusline.sh`
Expected: All pass including new COL tests

- [ ] **Step 5: Commit**

```bash
git add src/statusline.py tests/test-statusline.sh
git commit -m "feat: add CPU collector and renderer"
```

### Task 7: Implement memory collector and renderer

**Files:**
- Modify: `src/statusline.py`
- Modify: `tests/test-statusline.sh`

- [ ] **Step 1: Write memory tests**

Add to collector section:

```bash
# COL-04: Memory from valid meminfo
MOCK_PROC=$(mktemp -d)
cat > "$MOCK_PROC/meminfo" << 'MEMEOF'
MemTotal:       16384000 kB
MemFree:         2000000 kB
MemAvailable:    6000000 kB
Buffers:          500000 kB
Cached:          3000000 kB
MEMEOF
OUT=$(run_py "
import statusline
statusline.PROC_DIR = '$MOCK_PROC'
state = {}
statusline.collect_memory(state)
print(state.get('memory_percent', 'ABSENT'))
")
rm -rf "$MOCK_PROC"
assert_equals "COL-04: Memory percent" "$OUT" "63"

# COL-05: Memory missing MemAvailable → fallback
MOCK_PROC=$(mktemp -d)
cat > "$MOCK_PROC/meminfo" << 'MEMEOF'
MemTotal:       16384000 kB
MemFree:         2000000 kB
Buffers:          500000 kB
Cached:          3000000 kB
MEMEOF
OUT=$(run_py "
import statusline
statusline.PROC_DIR = '$MOCK_PROC'
state = {}
statusline.collect_memory(state)
print(state.get('memory_percent', 'ABSENT'))
")
rm -rf "$MOCK_PROC"
assert_equals "COL-05: Memory fallback" "$OUT" "66"

# COL-06: Memory missing file
MOCK_PROC=$(mktemp -d)
OUT=$(run_py "
import statusline
statusline.PROC_DIR = '$MOCK_PROC'
state = {}
statusline.collect_memory(state)
print(state.get('memory_percent', 'ABSENT'))
")
rm -rf "$MOCK_PROC"
assert_equals "COL-06: Memory missing" "$OUT" "ABSENT"
```

- [ ] **Step 2: Implement collect_memory**

```python
def collect_memory(state: dict[str, Any]) -> None:
    """Collect memory usage percentage from /proc/meminfo."""
    try:
        with open(os.path.join(PROC_DIR, "meminfo")) as f:
            lines = f.readlines()
        info: dict[str, int] = {}
        for line in lines:
            parts = line.split()
            if len(parts) >= 2 and parts[0].endswith(":"):
                key = parts[0][:-1]
                try:
                    info[key] = int(parts[1])
                except ValueError:
                    pass
        total = info.get("MemTotal", 0)
        if total <= 0:
            return
        available = info.get("MemAvailable")
        if available is None:
            # Older kernels fallback
            available = info.get("MemFree", 0) + info.get("Buffers", 0) + info.get("Cached", 0)
        used = total - available
        state["memory_percent"] = max(0, min(100, (used * 100) // total))
    except Exception:
        pass
```

- [ ] **Step 3: Implement render_memory**

Replace the placeholder — same pattern as render_cpu:

```python
def render_memory(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    if "memory_percent" not in state:
        return None
    cfg = theme.get("memory", {})
    pct = state["memory_percent"]
    show_t = cfg.get("show_threshold", 0)
    if pct <= show_t:
        return None
    text = f"{cfg.get('glyph', 'MEM ')}{pct}%"
    warn_t = cfg.get("warn_threshold", 70.0)
    crit_t = cfg.get("critical_threshold", 90.0)
    if pct >= crit_t:
        return _pill(text, cfg, cfg.get("critical_color", "#d06070"), True, theme)
    elif pct >= warn_t:
        return _pill(text, cfg, cfg.get("warn_color", "#f0d399"), theme=theme)
    return _pill(text, cfg, theme=theme)
```

- [ ] **Step 4: Run tests**

Run: `bash tests/test-statusline.sh`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/statusline.py tests/test-statusline.sh
git commit -m "feat: add memory collector and renderer"
```

### Task 8: Implement disk collector and renderer

**Files:**
- Modify: `src/statusline.py`
- Modify: `tests/test-statusline.sh`

- [ ] **Step 1: Write disk tests**

```bash
# COL-07: Disk from real statvfs
OUT=$(run_py "
from statusline import collect_disk
state = {}
collect_disk(state)
pct = state.get('disk_percent', -1)
print('OK' if 0 <= pct <= 100 else f'BAD:{pct}')
")
assert_equals "COL-07: Disk real statvfs" "$OUT" "OK"
```

- [ ] **Step 2: Implement collect_disk**

```python
def collect_disk(state: dict[str, Any]) -> None:
    """Collect disk usage percentage via os.statvfs."""
    try:
        # Path can be overridden via theme, but we don't have theme here.
        # Use DISK_PATH module var set during collect_system_data.
        path = getattr(collect_disk, '_path', '/')
        st = os.statvfs(path)
        total = st.f_blocks * st.f_frsize
        if total <= 0:
            return
        available = st.f_bavail * st.f_frsize
        used = total - available
        state["disk_percent"] = max(0, min(100, (used * 100) // total))
    except Exception:
        pass
```

- [ ] **Step 3: Implement render_disk**

Same pattern as CPU/memory:

```python
def render_disk(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    if "disk_percent" not in state:
        return None
    cfg = theme.get("disk", {})
    pct = state["disk_percent"]
    show_t = cfg.get("show_threshold", 0)
    if pct <= show_t:
        return None
    text = f"{cfg.get('glyph', 'DSK ')}{pct}%"
    warn_t = cfg.get("warn_threshold", 80.0)
    crit_t = cfg.get("critical_threshold", 95.0)
    if pct >= crit_t:
        return _pill(text, cfg, cfg.get("critical_color", "#d06070"), True, theme)
    elif pct >= warn_t:
        return _pill(text, cfg, cfg.get("warn_color", "#f0d399"), theme=theme)
    return _pill(text, cfg, theme=theme)
```

- [ ] **Step 4: Add collect_system_data and wire into main()**

```python
def collect_system_data(state: dict[str, Any], theme: dict[str, Any]) -> None:
    """Run all enabled system collectors."""
    collectors = [
        ("git", collect_git),
        ("cpu", collect_cpu),
        ("memory", collect_memory),
        ("disk", collect_disk),
        ("agents", collect_agents),
        ("tmux", collect_tmux),
    ]
    for name, fn in collectors:
        cfg = theme.get(name, {})
        if not cfg.get("enabled", True):
            continue
        # Set disk path from config
        if name == "disk":
            collect_disk._path = cfg.get("path", "/")
        try:
            fn(state)
        except Exception:
            pass
```

Update `main()`:

```python
def main() -> None:
    """Status-line entrypoint. Read, normalize, collect, render, emit."""
    theme = load_config()
    payload = read_stdin_bounded()
    if payload is None:
        return
    state = normalize(payload)
    collect_system_data(state, theme)
    line = render(state, theme)
    if line:
        print(line)
```

- [ ] **Step 5: Run all tests**

Run: `bash tests/test-statusline.sh`
Expected: All pass. Line 2 now shows CPU/MEM/DSK data from the real system when run as a command test.

- [ ] **Step 6: Commit**

```bash
git add src/statusline.py tests/test-statusline.sh
git commit -m "feat: add disk collector, collect_system_data, wire into main"
```

---

## Chunk 3: Subprocess Collectors — Git, Tmux, Agents

### Task 9: Implement git collector and renderer

**Files:**
- Modify: `src/statusline.py`
- Modify: `tests/test-statusline.sh`

- [ ] **Step 1: Write git collector tests**

Add to collector section:

```bash
# COL-08: Git in a repo
GIT_TMP=$(mktemp -d)
(cd "$GIT_TMP" && git init -q && git commit --allow-empty -m "init" -q)
OUT=$(run_py "
import os
os.chdir('$GIT_TMP')
from statusline import collect_git
state = {}
collect_git(state)
print('branch:' + str(state.get('git_branch', 'ABSENT')))
print('sha:' + str(state.get('git_sha', 'ABSENT')))
print('dirty:' + str(state.get('git_dirty', 'ABSENT')))
")
rm -rf "$GIT_TMP"
assert_contains "COL-08a: git branch" "$OUT" "branch:main"
assert_not_contains "COL-08b: git sha present" "$OUT" "sha:ABSENT"
assert_contains "COL-08c: git clean" "$OUT" "dirty:False"

# COL-09: Git dirty detection
GIT_TMP=$(mktemp -d)
(cd "$GIT_TMP" && git init -q && git commit --allow-empty -m "init" -q && echo "x" > dirty.txt)
OUT=$(run_py "
import os
os.chdir('$GIT_TMP')
from statusline import collect_git
state = {}
collect_git(state)
print('dirty:' + str(state.get('git_dirty', 'ABSENT')))
")
rm -rf "$GIT_TMP"
assert_contains "COL-09: git dirty" "$OUT" "dirty:True"

# COL-10: Git not a repo
NOTGIT=$(mktemp -d)
OUT=$(run_py "
import os
os.chdir('$NOTGIT')
from statusline import collect_git
state = {}
collect_git(state)
print('branch:' + str(state.get('git_branch', 'ABSENT')))
")
rm -rf "$NOTGIT"
assert_contains "COL-10: not a repo" "$OUT" "branch:ABSENT"
```

- [ ] **Step 2: Implement collect_git**

```python
def collect_git(state: dict[str, Any]) -> None:
    """Collect git branch, SHA, and dirty status."""
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    # Get SHA
    sha_out = _run_cmd(["git", "rev-parse", "--short", "HEAD"],
                        timeout=0.025, env=env)
    if sha_out is None:
        # Not a repo or no commits
        # Check if it's an empty repo (init but no commits)
        check = _run_cmd(["git", "rev-parse", "--git-dir"],
                          timeout=0.025, env=env)
        if check is not None:
            state["git_branch"] = "init"
        return

    sha = sha_out.strip()
    state["git_sha"] = sha

    # Get branch + dirty via porcelain
    status_out = _run_cmd(
        ["git", "status", "--porcelain", "--branch"],
        timeout=0.025, env=env,
    )
    if status_out is None:
        state["git_branch"] = "HEAD"
        state["git_dirty"] = False
        return

    lines = status_out.splitlines()
    # First line: ## branch...tracking
    branch = "HEAD"
    if lines and lines[0].startswith("## "):
        branch_part = lines[0][3:].split("...")[0]
        if branch_part == "HEAD (no branch)":
            branch = "HEAD"
        elif branch_part == "No commits yet on main":
            branch = "init"
        else:
            branch = branch_part

    # Truncate long branch names
    if len(branch) > 20:
        branch = branch[:19] + "\u2026"

    state["git_branch"] = branch
    state["git_dirty"] = len(lines) > 1  # any lines after branch header = dirty
```

- [ ] **Step 3: Implement render_git**

```python
def render_git(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    if "git_branch" not in state:
        return None
    cfg = theme.get("git", {})
    branch = state["git_branch"]
    sha = state.get("git_sha", "")
    dirty = state.get("git_dirty", False)
    dirty_marker = cfg.get("dirty_marker", "*") if dirty else ""

    if sha:
        text = f"{cfg.get('glyph', '')}{branch}@{sha}{dirty_marker}"
    else:
        text = f"{cfg.get('glyph', '')}{branch}{dirty_marker}"

    return _pill(text, cfg, theme=theme)
```

- [ ] **Step 4: Run tests**

Run: `bash tests/test-statusline.sh`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/statusline.py tests/test-statusline.sh
git commit -m "feat: add git collector and renderer"
```

### Task 10: Implement tmux collector and renderer

**Files:**
- Modify: `src/statusline.py`
- Modify: `tests/test-statusline.sh`

- [ ] **Step 1: Write tmux tests**

```bash
# COL-11: Tmux when running (integration — skip if not in tmux)
if [ -n "$TMUX" ]; then
OUT=$(run_py "
from statusline import collect_tmux
state = {}
collect_tmux(state)
sessions = state.get('tmux_sessions', 0)
panes = state.get('tmux_panes', 0)
print(f'sessions={sessions}')
print(f'panes={panes}')
print('OK' if sessions > 0 else 'NO_SESSIONS')
")
assert_contains "COL-11: tmux sessions" "$OUT" "OK"
else
echo "  SKIP: COL-11: tmux not running"
fi

# COL-12: Tmux render format
OUT=$(run_py "
from statusline import render_tmux, DEFAULT_THEME
state = {'tmux_sessions': 3, 'tmux_panes': 12}
result = render_tmux(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_contains "COL-12: tmux format" "$OUT" "3s/12p"
```

- [ ] **Step 2: Implement collect_tmux**

```python
def collect_tmux(state: dict[str, Any]) -> None:
    """Collect tmux session and pane counts."""
    sessions_out = _run_cmd(["tmux", "list-sessions"], timeout=0.025)
    if sessions_out is None:
        return
    session_lines = [l for l in sessions_out.splitlines() if l.strip()]
    if not session_lines:
        return
    state["tmux_sessions"] = len(session_lines)

    panes_out = _run_cmd(["tmux", "list-panes", "-a"], timeout=0.025)
    if panes_out is not None:
        pane_lines = [l for l in panes_out.splitlines() if l.strip()]
        state["tmux_panes"] = len(pane_lines)
    else:
        state["tmux_panes"] = 0
```

- [ ] **Step 3: Implement render_tmux**

```python
def render_tmux(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    if "tmux_sessions" not in state or state["tmux_sessions"] <= 0:
        return None
    cfg = theme.get("tmux", {})
    sessions = state["tmux_sessions"]
    panes = state.get("tmux_panes", 0)
    if panes > 0:
        text = f"{cfg.get('glyph', 'tmux ')}{sessions}s/{panes}p"
    else:
        text = f"{cfg.get('glyph', 'tmux ')}{sessions}s"
    return _pill(text, cfg, theme=theme)
```

- [ ] **Step 4: Run tests**

Run: `bash tests/test-statusline.sh`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/statusline.py tests/test-statusline.sh
git commit -m "feat: add tmux collector and renderer"
```

### Task 11: Implement agents collector and renderer

**Files:**
- Modify: `src/statusline.py`
- Modify: `tests/test-statusline.sh`

- [ ] **Step 1: Write agents tests**

```bash
# COL-13: Agents from payload only (no codex)
OUT=$(run_py "
from statusline import collect_agents, normalize
payload = {
    'model': {'display_name': 'Opus'},
    'context_window': {
        'used_percentage': 10,
        'context_window_size': 200000,
        'total_input_tokens': 100,
        'total_output_tokens': 50,
    },
}
state = normalize(payload)
collect_agents(state)
print(state.get('agent_count', 'ABSENT'))
")
# No task data in payload → 0 → ABSENT because we don't set 0
assert_equals "COL-13: no agents" "$OUT" "ABSENT"

# COL-14: Agents render with count
OUT=$(run_py "
from statusline import render_agents, DEFAULT_THEME
state = {'agent_count': 3}
result = render_agents(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_contains "COL-14: agents render" "$OUT" "3"

# COL-15: Agents zero → hidden
OUT=$(run_py "
from statusline import render_agents, DEFAULT_THEME
state = {'agent_count': 0}
result = render_agents(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_equals "COL-15: agents zero hidden" "$OUT" "NONE"
```

- [ ] **Step 2: Implement collect_agents**

```python
def collect_agents(state: dict[str, Any]) -> None:
    """Count running Claude agents (from payload) and Codex instances."""
    count = 0

    # Claude agents: look for tasks in the payload's normalized state
    # The payload may contain task data under various keys
    current_usage = state.get("current_usage")
    if isinstance(current_usage, dict):
        # current_usage sometimes contains agent info
        pass

    # Codex instances via pgrep
    codex_out = _run_cmd(["pgrep", "-x", "codex"], timeout=0.05)
    if codex_out:
        codex_lines = [l for l in codex_out.splitlines() if l.strip()]
        count += len(codex_lines)

    if count > 0:
        state["agent_count"] = count
```

- [ ] **Step 3: Implement render_agents**

```python
def render_agents(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    if "agent_count" not in state or state["agent_count"] <= 0:
        return None
    cfg = theme.get("agents", {})
    count = state["agent_count"]
    show_t = cfg.get("show_threshold", 0)
    if count <= show_t:
        return None
    text = f"{cfg.get('glyph', '')}{count}"
    warn_t = cfg.get("warn_threshold", 5)
    crit_t = cfg.get("critical_threshold", 8)
    if count >= crit_t:
        return _pill(text, cfg, cfg.get("critical_color", "#d06070"), True, theme)
    elif count >= warn_t:
        return _pill(text, cfg, cfg.get("warn_color", "#f0d399"), theme=theme)
    return _pill(text, cfg, theme=theme)
```

- [ ] **Step 4: Run tests**

Run: `bash tests/test-statusline.sh`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/statusline.py tests/test-statusline.sh
git commit -m "feat: add agents collector and renderer"
```

---

## Chunk 4: Cache Layer + Stale Data

### Task 12: Implement cache read/write/staleness

**Files:**
- Modify: `src/statusline.py`
- Modify: `tests/test-statusline.sh`

- [ ] **Step 1: Add cache constants**

```python
CACHE_PATH = "/tmp/qline-cache.json"
CACHE_MAX_AGE_S = 60.0
CACHE_VERSION = 1
```

- [ ] **Step 2: Implement load_cache and save_cache**

```python
def load_cache() -> dict[str, Any]:
    """Load cache file, return empty dict on any failure."""
    try:
        with open(CACHE_PATH) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        if data.get("version") != CACHE_VERSION:
            return {}
        return data.get("modules", {})
    except Exception:
        return {}


def save_cache(cache: dict[str, Any]) -> None:
    """Atomically save cache to disk. Silent on failure."""
    try:
        data = {"version": CACHE_VERSION, "modules": cache}
        fd = tempfile.NamedTemporaryFile(
            mode="w", dir="/tmp", prefix="qline-", suffix=".tmp",
            delete=False,
        )
        try:
            json.dump(data, fd)
            fd.flush()
            os.fsync(fd.fileno())
            fd.close()
            os.rename(fd.name, CACHE_PATH)
        except Exception:
            fd.close()
            try:
                os.unlink(fd.name)
            except OSError:
                pass
    except Exception:
        pass
```

- [ ] **Step 3: Update collect_system_data to use cache**

```python
def collect_system_data(state: dict[str, Any], theme: dict[str, Any]) -> None:
    """Run all enabled system collectors with cache fallback."""
    cache = load_cache()
    now = time.time()

    collectors = [
        ("git", collect_git),
        ("cpu", collect_cpu),
        ("memory", collect_memory),
        ("disk", collect_disk),
        ("agents", collect_agents),
        ("tmux", collect_tmux),
    ]

    new_cache: dict[str, Any] = {}

    for name, fn in collectors:
        cfg = theme.get(name, {})
        if not cfg.get("enabled", True):
            continue
        if name == "disk":
            collect_disk._path = cfg.get("path", "/")

        try:
            fn(state)
            # Collector succeeded — cache the relevant state keys
            _cache_module(new_cache, state, name, now)
        except Exception:
            # Collector failed — try cache fallback
            _apply_cached(state, cache, name, now)

    save_cache(new_cache)


def _cache_module(cache: dict, state: dict, name: str, now: float) -> None:
    """Save module data to cache dict."""
    key_map = {
        "git": ["git_branch", "git_sha", "git_dirty"],
        "cpu": ["cpu_percent"],
        "memory": ["memory_percent"],
        "disk": ["disk_percent"],
        "agents": ["agent_count"],
        "tmux": ["tmux_sessions", "tmux_panes"],
    }
    keys = key_map.get(name, [])
    values = {}
    for k in keys:
        if k in state:
            values[k] = state[k]
    if values:
        cache[name] = {"value": values, "timestamp": now}


def _apply_cached(state: dict, cache: dict, name: str, now: float) -> None:
    """Apply cached data if fresh enough, marking as stale."""
    entry = cache.get(name)
    if not isinstance(entry, dict):
        return
    ts = entry.get("timestamp", 0)
    if now - ts > CACHE_MAX_AGE_S:
        return
    values = entry.get("value", {})
    if isinstance(values, dict):
        state.update(values)
        state[f"{name}_stale"] = True
```

- [ ] **Step 4: Update main() to use new collect_system_data**

```python
def main() -> None:
    """Status-line entrypoint. Read, normalize, collect, render, emit."""
    theme = load_config()
    payload = read_stdin_bounded()
    if payload is None:
        return
    state = normalize(payload)
    collect_system_data(state, theme)
    line = render(state, theme)
    if line:
        print(line)
```

- [ ] **Step 5: Write cache tests**

Add a `cache` test section:

```bash
# ======================================================================
# SECTION: cache — stale data cache tests
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "cache" ]; then
echo "--- Cache Tests ---"

# CACHE-01: save and load round-trip
OUT=$(run_py "
import statusline, time, json
statusline.CACHE_PATH = '/tmp/qline-test-cache.json'
cache = {'cpu': {'value': {'cpu_percent': 42}, 'timestamp': time.time()}}
statusline.save_cache(cache)
loaded = statusline.load_cache()
print(loaded.get('cpu', {}).get('value', {}).get('cpu_percent', 'ABSENT'))
import os; os.unlink('/tmp/qline-test-cache.json')
")
assert_equals "CACHE-01: round-trip" "$OUT" "42"

# CACHE-02: corrupted cache → empty
echo "not json" > /tmp/qline-test-cache2.json
OUT=$(run_py "
import statusline
statusline.CACHE_PATH = '/tmp/qline-test-cache2.json'
loaded = statusline.load_cache()
print(len(loaded))
")
rm -f /tmp/qline-test-cache2.json
assert_equals "CACHE-02: corrupted → empty" "$OUT" "0"

# CACHE-03: wrong version → empty
echo '{"version": 999, "modules": {"cpu": {}}}' > /tmp/qline-test-cache3.json
OUT=$(run_py "
import statusline
statusline.CACHE_PATH = '/tmp/qline-test-cache3.json'
loaded = statusline.load_cache()
print(len(loaded))
")
rm -f /tmp/qline-test-cache3.json
assert_equals "CACHE-03: wrong version → empty" "$OUT" "0"

# CACHE-04: stale entry (>60s) not applied
OUT=$(run_py "
import statusline, time
statusline.CACHE_PATH = '/tmp/qline-nonexistent'
cache = {'cpu': {'value': {'cpu_percent': 99}, 'timestamp': time.time() - 120}}
state = {}
statusline._apply_cached(state, cache, 'cpu', time.time())
print(state.get('cpu_percent', 'ABSENT'))
")
assert_equals "CACHE-04: stale not applied" "$OUT" "ABSENT"

# CACHE-05: fresh entry applied with stale flag
OUT=$(run_py "
import statusline, time
cache = {'cpu': {'value': {'cpu_percent': 42}, 'timestamp': time.time()}}
state = {}
statusline._apply_cached(state, cache, 'cpu', time.time())
print(state.get('cpu_percent', 'ABSENT'))
print(state.get('cpu_stale', False))
")
assert_contains "CACHE-05a: fresh applied" "$OUT" "42"
assert_contains "CACHE-05b: stale flag" "$OUT" "True"

echo ""
fi
```

- [ ] **Step 6: Run all tests**

Run: `bash tests/test-statusline.sh`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/statusline.py tests/test-statusline.sh
git commit -m "feat: add cache layer for stale data fallback"
```

---

## Chunk 5: UX Polish — Worktree, Density, Integration

### Task 13: Worktree decorator on dir module

**Files:**
- Modify: `src/statusline.py` (render_dir)
- Modify: `tests/test-statusline.sh`

- [ ] **Step 1: Write worktree test**

```bash
# L-11: Worktree marker appended
OUT=$(run_py "
from statusline import render_dir, DEFAULT_THEME
state = {'dir_basename': 'qLine', 'is_worktree': True}
result = render_dir(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_contains "L-11: worktree marker" "$OUT" "⊛"

# L-12: No worktree marker when false
OUT=$(run_py "
from statusline import render_dir, DEFAULT_THEME
state = {'dir_basename': 'qLine', 'is_worktree': False}
result = render_dir(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_not_contains "L-12: no marker" "$OUT" "⊛"
```

- [ ] **Step 2: Update render_dir**

```python
def render_dir(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    dir_basename = state.get("dir_basename")
    if not dir_basename:
        return None
    d_cfg = theme.get("dir", {})
    name = _sanitize_fragment(dir_basename)
    if state.get("is_worktree"):
        marker = d_cfg.get("worktree_marker", "\u229b")
        name = f"{name}{marker}"
    text = f"{d_cfg.get('glyph', '')}{name}"
    return _pill(text, d_cfg, theme=theme)
```

- [ ] **Step 3: Run tests, commit**

Run: `bash tests/test-statusline.sh`

```bash
git add src/statusline.py tests/test-statusline.sh
git commit -m "feat: add worktree marker to dir module"
```

### Task 14: Contextual density for single-line mode

**Files:**
- Modify: `src/statusline.py` (render_cpu, render_memory, render_disk, render_git)
- Modify: `tests/test-statusline.sh`

- [ ] **Step 1: Add density context to render_line**

Add a `compact` parameter that renderers can check:

Pass layout line count info through theme temporarily:

```python
def render(state: dict[str, Any], theme: dict[str, Any] | None = None) -> str:
    if theme is None:
        theme = DEFAULT_THEME
    layout = theme.get("layout", {})
    num_lines = max(1, min(2, layout.get("lines", 2)))
    # ... existing code ...
    # Set compact flag for renderers
    compact = num_lines == 1
    state["_compact"] = compact
    # ... rest of render ...
```

- [ ] **Step 2: Update system metric renderers for compact mode**

In render_cpu, render_memory, render_disk — when `state.get("_compact")` is True, use abbreviated labels:

```python
# In render_cpu:
    if state.get("_compact"):
        text = f"C:{pct}%"
    else:
        text = f"{cfg.get('glyph', 'CPU ')}{pct}%"
```

Same for memory (`M:`) and disk (`D:`).

In render_git — when compact, truncate branch to 12 chars instead of 20.

- [ ] **Step 3: Write density tests**

```bash
# DENSITY-01: CPU abbreviated in single-line mode
OUT=$(run_py "
from statusline import render_cpu, DEFAULT_THEME
state = {'cpu_percent': 23, '_compact': True}
result = render_cpu(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_contains "DENSITY-01: CPU compact" "$OUT" "C:23%"

# DENSITY-02: CPU full in two-line mode
OUT=$(run_py "
from statusline import render_cpu, DEFAULT_THEME
state = {'cpu_percent': 23, '_compact': False}
result = render_cpu(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_contains "DENSITY-02: CPU full" "$OUT" "CPU 23%"
```

- [ ] **Step 4: Run tests, commit**

Run: `bash tests/test-statusline.sh`

```bash
git add src/statusline.py tests/test-statusline.sh
git commit -m "feat: add contextual density for single-line mode"
```

### Task 15: Stale data dimming in renderers

**Files:**
- Modify: `src/statusline.py`
- Modify: `tests/test-statusline.sh`

- [ ] **Step 1: Update _pill to support dimming**

Add a `dim` parameter:

```python
def _pill(text: str, cfg: dict[str, Any], color: str | None = None,
          bold: bool = False, theme: dict[str, Any] | None = None,
          dim: bool = False) -> str:
    c = color or cfg.get("color")
    bg_hex = cfg.get("bg")
    if dim and not NO_COLOR:
        # Override: dim attribute wraps the pill
        if bg_hex:
            inner = style(f" {text} ", c, bold, bg_hex)
            return f"\033[2m{inner}\033[0m"
        return style_dim(style(text, c, bold))
    if bg_hex and not NO_COLOR:
        inner = style(f" {text} ", c, bold, bg_hex)
        pill_cfg = (theme or {}).get("pill", {})
        left = pill_cfg.get("left", "")
        right = pill_cfg.get("right", "")
        if left and right:
            return style(left, bg_hex) + inner + style(right, bg_hex)
        return inner
    return style(text, c, bold)
```

- [ ] **Step 2: Update system renderers to check stale flag**

In each of render_cpu, render_memory, render_disk, render_git, render_tmux, render_agents — check for `state.get(f"{module}_stale")` and pass `dim=True`:

```python
# Example for render_cpu:
    is_stale = state.get("cpu_stale", False)
    # ... threshold logic ...
    return _pill(text, cfg, theme=theme, dim=is_stale)
```

- [ ] **Step 3: Write stale rendering test**

```bash
# STALE-01: Stale CPU rendered dimmed
OUT=$(run_py "
from statusline import render_cpu, DEFAULT_THEME
state = {'cpu_percent': 42, 'cpu_stale': True}
result = render_cpu(state, DEFAULT_THEME)
# Should contain dim escape sequence
print('HAS_DIM' if '\033[2m' in (result or '') else 'NO_DIM')
" 2>&1)
# Note: This test must NOT use NO_COLOR
assert_equals "STALE-01: stale has dim" "$(echo "$OUT" | grep -o 'HAS_DIM\|NO_DIM')" "HAS_DIM"
```

- [ ] **Step 4: Run tests, commit**

Run: `bash tests/test-statusline.sh`

```bash
git add src/statusline.py tests/test-statusline.sh
git commit -m "feat: add stale data dimming to system renderers"
```

### Task 16: Install and final integration test

**Files:**
- Modify: `tests/test-statusline.sh`
- Copy: `src/statusline.py` → `~/.claude/statusline.py`

- [ ] **Step 1: Add end-to-end integration test with real payload**

```bash
# INT-01: Full real payload produces two-line output
run_statusline_color "$(cat "$FIXTURES/valid-real-payload.json")"
assert_exit_zero "INT-01a: exit 0" "$LAST_EXIT"
# Should have at least 1 line
TOTAL=$((TOTAL + 1))
LINE_COUNT=$(printf '%s\n' "$LAST_STDOUT" | wc -l)
if [ "$LINE_COUNT" -ge 1 ]; then
    echo "  PASS: INT-01b: at least 1 line ($LINE_COUNT)"
    PASS=$((PASS + 1))
else
    echo "  FAIL: INT-01b: expected at least 1 line, got $LINE_COUNT"
    FAIL=$((FAIL + 1))
fi
assert_empty "INT-01c: no stderr" "$LAST_STDERR"
```

- [ ] **Step 2: Run full test suite**

Run: `bash tests/test-statusline.sh`
Expected: All ~198 tests pass

- [ ] **Step 3: Install**

```bash
cp src/statusline.py ~/.claude/statusline.py
```

- [ ] **Step 4: Final commit**

```bash
git add src/statusline.py tests/test-statusline.sh
git commit -m "feat: qLine expansion complete — 12 modules, 2 lines, ~198 tests"
```
