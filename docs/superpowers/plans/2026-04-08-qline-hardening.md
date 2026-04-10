# qLine Hardening: Session Isolation, Freshness, Diagnostics

> **STALE:** References to `src/qline-daemon.py` are obsolete — the daemon was deleted in commit `11b05f2` (2026-04-09), replaced by CC's native `refreshInterval`. Steps 7-8 in Task 1 no longer apply.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three real-world pain points — concurrent session collision, invisible data staleness, and silent total failure after CC updates.

**Architecture:** Session-scope all `/tmp` state files by session_id hash. Replace the single 30s cache TTL with per-category intervals (5s for obs, 30s for overhead, 60s for system metrics). Replace bare `except: pass` error swallowing with a diagnostic capture buffer that renders a visible degraded-mode pill. Add payload schema fingerprinting to detect CC format changes before they cause silent breakage.

**Tech Stack:** Python 3.10+, ANSI truecolor, TOML config, shell test harness (`test-statusline.sh`)

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/statusline.py` | Modify | Session path init, tiered cache, freshness rendering, diagnostic capture, degraded pill |
| `src/context_overhead.py` | Modify | Version fingerprint for payload schema detection |
| `src/qline-daemon.py` | Modify | Session-scoped paths, session_id from payload |
| `tests/test-statusline.sh` | Modify | New test sections for session isolation, freshness, diagnostics, fingerprint |

---

### Task 1: Session-Scoped File Paths

**Files:**
- Modify: `src/statusline.py:57-63` (constants), `src/statusline.py:837` (alert file)
- Modify: `src/qline-daemon.py:16-18` (daemon constants)
- Modify: `tests/test-statusline.sh` (new test section)

- [ ] **Step 1: Write failing test — session_paths returns scoped paths**

Add to `tests/test-statusline.sh` at the end of the cache section:

```bash
echo "  SESSION-01: session_paths produces scoped paths"
OUT=$(run_py "
from statusline import _init_session_paths, CACHE_PATH
import statusline

# Before init: default global path
assert '/tmp/qline-cache.json' in CACHE_PATH or 'QLINE_CACHE_PATH' in repr(CACHE_PATH)

# After init with session_id: scoped path
_init_session_paths('abc-123-def')
assert 'abc-123-def' in statusline.CACHE_PATH or len(statusline.CACHE_PATH) > len('/tmp/qline-cache.json')
# Must contain a hash of the session_id
import hashlib
expected_hash = hashlib.sha256('abc-123-def'.encode()).hexdigest()[:12]
assert expected_hash in statusline.CACHE_PATH, f'expected hash {expected_hash} in {statusline.CACHE_PATH}'
print('OK')

# Reset for other tests
_init_session_paths(None)
")
assert_equals "SESSION-01: scoped paths" "$OUT" "OK"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/test-statusline.sh --section cache 2>&1 | grep SESSION-01`
Expected: FAIL (function doesn't exist)

- [ ] **Step 3: Implement _init_session_paths and ALERT_FILE extraction**

In `src/statusline.py`, replace the constants block (around lines 57-64):

```python
# --- Session-scoped paths ---

_DEFAULT_CACHE_PATH = "/tmp/qline-cache.json"
_DEFAULT_ALERT_FILE = "/tmp/qline-alert.json"
CACHE_PATH = os.environ.get("QLINE_CACHE_PATH", _DEFAULT_CACHE_PATH)
ALERT_FILE = _DEFAULT_ALERT_FILE
CACHE_MAX_AGE_S = 60.0
CACHE_VERSION = 1


def _session_hash(session_id: str) -> str:
    """Stable 12-char hash of session_id for filesystem-safe scoping."""
    return hashlib.sha256(session_id.encode()).hexdigest()[:12]


def _init_session_paths(session_id: str | None) -> None:
    """Scope all temp file paths by session_id. Idempotent.

    Falls back to global defaults if session_id is None (backwards compatible).
    """
    global CACHE_PATH, ALERT_FILE
    if session_id:
        h = _session_hash(session_id)
        CACHE_PATH = os.environ.get("QLINE_CACHE_PATH", f"/tmp/qline-{h}-cache.json")
        ALERT_FILE = f"/tmp/qline-{h}-alert.json"
    else:
        CACHE_PATH = os.environ.get("QLINE_CACHE_PATH", _DEFAULT_CACHE_PATH)
        ALERT_FILE = _DEFAULT_ALERT_FILE
```

Then inside `render_context_bar`, replace the local `_ALERT_FILE = "/tmp/qline-alert.json"` (line ~837) with a reference to the module-level `ALERT_FILE`:

```python
    # Track onset via disk file (script runs once per CC call, no in-memory state)
    import time as _time
    alert_glyph_str = None
    alert_crit = False

    def _load_alert():
        try:
            with open(ALERT_FILE) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_alert(d):
        try:
            with open(ALERT_FILE, "w") as f:
                json.dump(d, f)
        except Exception:
            pass
```

In `main()` (around line 2003), add session path initialization after reading payload:

```python
def main() -> None:
    """Status-line entrypoint. Read, normalize, collect, render, emit."""
    theme = load_config()
    payload = read_stdin_bounded()
    if payload is None:
        return
    # Session-scope all temp file paths
    session_id = payload.get("session_id")
    if isinstance(session_id, str) and session_id:
        _init_session_paths(session_id)
    state = normalize(payload)
    # ... rest unchanged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test-statusline.sh --section cache 2>&1 | grep SESSION-01`
Expected: PASS

- [ ] **Step 5: Write failing test — session isolation between concurrent sessions**

```bash
echo "  SESSION-02: concurrent sessions use separate cache files"
OUT=$(run_py "
import statusline
from statusline import _init_session_paths, save_cache, load_cache
import json, os

# Session A writes data
_init_session_paths('session-aaa')
path_a = statusline.CACHE_PATH
save_cache({'_obs': {'session-aaa': {'test': 'data-a'}}})

# Session B writes different data
_init_session_paths('session-bbb')
path_b = statusline.CACHE_PATH
save_cache({'_obs': {'session-bbb': {'test': 'data-b'}}})

# Paths must be different
assert path_a != path_b, f'paths should differ: {path_a} vs {path_b}'

# Session A data still intact
_init_session_paths('session-aaa')
cache_a = load_cache()
assert cache_a.get('_obs', {}).get('session-aaa', {}).get('test') == 'data-a', f'session A data lost: {cache_a}'

# Session B data still intact
_init_session_paths('session-bbb')
cache_b = load_cache()
assert cache_b.get('_obs', {}).get('session-bbb', {}).get('test') == 'data-b', f'session B data lost: {cache_b}'

# Cleanup
os.unlink(path_a)
os.unlink(path_b)
_init_session_paths(None)
print('OK')
")
assert_equals "SESSION-02: concurrent isolation" "$OUT" "OK"
```

- [ ] **Step 6: Run test — should pass (implementation already supports this)**

Run: `bash tests/test-statusline.sh --section cache 2>&1 | grep SESSION-02`
Expected: PASS

- [ ] **Step 7: Update daemon to use session-scoped paths**

In `src/qline-daemon.py`, replace the hardcoded constants and add session_id extraction:

```python
# Default paths (overridden per-session in main loop)
LIVE_FILE = "/tmp/qline-live.txt"
PAYLOAD_FILE = "/tmp/qline-payload.json"
PID_FILE = "/tmp/qline-daemon.pid"
RENDER_INTERVAL = 0.2  # 200ms
IDLE_TIMEOUT = 300  # 5 minutes
```

In the daemon's main loop, after reading payload, scope the paths:

```python
            with open(PAYLOAD_FILE) as f:
                payload = json.load(f)

            # Session-scope paths on first payload read
            sid = payload.get("session_id")
            if isinstance(sid, str) and sid and not session_initialized:
                from statusline import _init_session_paths, _session_hash
                _init_session_paths(sid)
                h = _session_hash(sid)
                LIVE_FILE = f"/tmp/qline-{h}-live.txt"
                PID_FILE = f"/tmp/qline-{h}-daemon.pid"
                # Rewrite PID to new location
                with open(PID_FILE, "w") as pf:
                    pf.write(str(os.getpid()))
                session_initialized = True
```

Add `session_initialized = False` before the while loop.

- [ ] **Step 8: Commit**

```bash
git add src/statusline.py src/qline-daemon.py tests/test-statusline.sh
git commit -m "feat(session): scope all /tmp state files by session_id hash

Prevents concurrent CC sessions from corrupting each other's cache,
alert, and daemon state. Falls back to global paths when session_id
is missing (backwards compatible)."
```

---

### Task 2: Tiered Cache TTL

**Files:**
- Modify: `src/statusline.py` (cache layer ~line 1290-1410, obs injection ~line 1870-1930)
- Modify: `tests/test-statusline.sh`

- [ ] **Step 1: Write failing test — obs counters refresh at 5s, not 30s**

```bash
echo "  TIERED-01: obs counters refresh at 5s interval"
OUT=$(run_py "
import time, statusline

# Simulate obs cache that's 10s old (> 5s obs TTL, < 30s overhead TTL)
statusline._init_session_paths(None)
cache = {
    '_obs': {
        'test-session': {
            'last_count_ts': time.time() - 10,
            'event_counts': {'bash.executed': 5},
            'total_reads': 3,
            'reread_count': 0,
            'obs_health': 'healthy',
            'overhead_ts': time.time() - 10,
            'sys_overhead_tokens': 50000,
        }
    }
}
statusline.save_cache(cache)

# _inject_obs_counters should refresh because 10s > OBS_CACHE_TTL (5s)
# We can't fully test without a real package, but we can verify the TTL constant
assert hasattr(statusline, 'OBS_CACHE_TTL'), 'OBS_CACHE_TTL not defined'
assert statusline.OBS_CACHE_TTL <= 5, f'OBS_CACHE_TTL should be <= 5s, got {statusline.OBS_CACHE_TTL}'
assert statusline.SYSTEM_CACHE_TTL >= 60, f'SYSTEM_CACHE_TTL should be >= 60s, got {statusline.SYSTEM_CACHE_TTL}'
assert statusline.CACHE_MAX_AGE_S >= 30, f'CACHE_MAX_AGE_S (overhead) should be >= 30s'
print('OK')
")
assert_equals "TIERED-01: obs TTL" "$OUT" "OK"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/test-statusline.sh --section cache 2>&1 | grep TIERED-01`
Expected: FAIL (OBS_CACHE_TTL not defined)

- [ ] **Step 3: Implement tiered TTL constants and wire into cache checks**

In `src/statusline.py`, add tiered TTL constants near the existing CACHE_MAX_AGE_S:

```python
CACHE_MAX_AGE_S = 30.0    # Overhead data refresh interval
OBS_CACHE_TTL = 5.0        # Obs counters: refresh every 5s (change every turn)
SYSTEM_CACHE_TTL = 60.0    # System metrics: refresh every 60s (CPU/memory/disk)
```

In `collect_system_data` (around line 1370), change the cache staleness check:

```python
def collect_system_data(state: dict[str, Any], theme: dict[str, Any]) -> None:
    """Run all enabled system collectors with cache fallback.

    Uses SYSTEM_CACHE_TTL (60s) for system metrics refresh interval.
    """
    if os.environ.get("QLINE_NO_COLLECT") == "1":
        return
    cache = load_cache()
    now = time.time()
    new_cache: dict[str, Any] = {}

    # Preserve obs namespace across cache rebuilds
    if "_obs" in cache:
        new_cache["_obs"] = cache["_obs"]

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
        # Check if cached data is still fresh under SYSTEM_CACHE_TTL
        existing = cache.get(name)
        if isinstance(existing, dict) and now - existing.get("timestamp", 0) < SYSTEM_CACHE_TTL:
            new_cache[name] = existing
            values = existing.get("value", {})
            if isinstance(values, dict):
                state.update(values)
                state[f"{name}_stale"] = True
            continue
        if name == "disk":
            collect_disk._path = cfg.get("path", "/")
        try:
            fn(state)
            _cache_module(new_cache, state, name, now)
        except Exception:
            _apply_cached(state, cache, name, now)

    save_cache(new_cache)
```

In `_inject_obs_counters` (around line 1895), change the 30s check to use OBS_CACHE_TTL:

```python
        # Refresh counts if stale (OBS_CACHE_TTL for fast update)
        if now - session_cache.get("last_count_ts", 0) >= OBS_CACHE_TTL:
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test-statusline.sh --section cache 2>&1 | grep TIERED-01`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/statusline.py tests/test-statusline.sh
git commit -m "feat(cache): tiered TTL — 5s obs, 30s overhead, 60s system

Obs counters now refresh every 5s (they change per turn).
System metrics (CPU/memory/disk) refresh every 60s.
Overhead data stays at 30s. Reduces staleness for the
most volatile metrics without subprocess storms."
```

---

### Task 3: Freshness Age Indicator

**Files:**
- Modify: `src/statusline.py` (renderers, ~line 1412-1520)
- Modify: `tests/test-statusline.sh`

- [ ] **Step 1: Write failing test — stale system metrics show age suffix**

```bash
echo "  FRESH-01: stale system metric shows age"
OUT=$(run_py "
import os
os.environ['NO_COLOR'] = '1'
from statusline import render_cpu, DEFAULT_THEME
import time

# Stale CPU data with known timestamp
state = {
    'cpu_percent': 45,
    'cpu_stale': True,
    '_cache_timestamps': {'cpu': time.time() - 42},
}
result = render_cpu(state, DEFAULT_THEME)
assert result is not None, 'should render even when stale'
assert '42s' in result or '43s' in result, f'should show age ~42s: {result}'
print('OK')
")
assert_equals "FRESH-01: stale age shown" "$OUT" "OK"
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL (_cache_timestamps not used, no age in output)

- [ ] **Step 3: Implement freshness age rendering**

In `src/statusline.py`, add a freshness formatter:

```python
def _freshness_suffix(state: dict, cache_key: str) -> str:
    """Return dim age suffix like '12s' for stale cached data, or '' if fresh."""
    if not state.get(f"{cache_key}_stale"):
        return ""
    ts_map = state.get("_cache_timestamps", {})
    ts = ts_map.get(cache_key)
    if ts is None:
        return ""
    age = int(time.time() - ts)
    if age < 5:
        return ""  # Fresh enough — no suffix
    return style_dim(f" {age}s") if not NO_COLOR else f" {age}s"
```

In `_apply_cached` (around line 1350), store the timestamp:

```python
def _apply_cached(state: dict, cache: dict, name: str, now: float) -> None:
    """Apply cached data if fresh enough, marking as stale with timestamp."""
    entry = cache.get(name)
    if not isinstance(entry, dict):
        return
    ts = entry.get("timestamp", 0)
    if now - ts > SYSTEM_CACHE_TTL:
        return
    values = entry.get("value", {})
    if isinstance(values, dict):
        state.update(values)
        state[f"{name}_stale"] = True
        ts_map = state.setdefault("_cache_timestamps", {})
        ts_map[name] = ts
```

Also update the fresh-cache path in `collect_system_data` to store timestamps:

```python
        if isinstance(existing, dict) and now - existing.get("timestamp", 0) < SYSTEM_CACHE_TTL:
            new_cache[name] = existing
            values = existing.get("value", {})
            if isinstance(values, dict):
                state.update(values)
                state[f"{name}_stale"] = True
                ts_map = state.setdefault("_cache_timestamps", {})
                ts_map[name] = existing.get("timestamp", 0)
            continue
```

In `_render_system_metric`, append the freshness suffix:

```python
def _render_system_metric(state: dict[str, Any], theme: dict[str, Any],
                          state_key: str, theme_key: str,
                          compact_label: str = "") -> str | None:
    if state_key not in state:
        return None
    cfg = theme.get(theme_key, {})
    pct = state[state_key]
    show_t = cfg.get("show_threshold", 0)
    if pct < show_t:
        return None
    warn_t = cfg.get("warn_threshold", 60.0)
    crit_t = cfg.get("critical_threshold", 85.0)

    width = cfg.get("width", 5)
    filled = (pct * width) // 100
    bar = "\u2588" * filled + "\u2591" * (width - filled)

    if state.get("_compact") and compact_label:
        text = f"{compact_label}{bar} {pct}%"
    else:
        glyph = cfg.get("glyph", "")
        text = f"{glyph}{bar} {pct}%"

    age = _freshness_suffix(state, theme_key)
    is_stale = state.get(f"{theme_key}_stale", False)
    if pct >= crit_t:
        return _pill(text, cfg, cfg.get("critical_color", "#d06070"), True, theme, dim=is_stale) + age
    if pct >= warn_t:
        return _pill(text, cfg, cfg.get("warn_color", "#f0d399"), theme=theme, dim=is_stale) + age
    return _pill(text, cfg, theme=theme, dim=is_stale) + age
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test-statusline.sh 2>&1 | grep FRESH-01`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/statusline.py tests/test-statusline.sh
git commit -m "feat(freshness): show age suffix on stale cached metrics

Stale system metrics now show a dim age indicator (e.g., '42s')
so users can tell at a glance whether data is current. Fresh data
(< 5s old) shows no suffix. Uses _cache_timestamps state map."
```

---

### Task 4: Diagnostic Capture + Degraded Pill

**Files:**
- Modify: `src/statusline.py` (error handling, new renderer)
- Modify: `tests/test-statusline.sh`

- [ ] **Step 1: Write failing test — diagnostic buffer captures errors**

```bash
echo "  DIAG-01: _capture_diagnostic adds to buffer"
OUT=$(run_py "
from statusline import _capture_diagnostic

state = {}
_capture_diagnostic(state, 'test_module', 'something went wrong')
diags = state.get('_diagnostics', [])
assert len(diags) == 1, f'expected 1 diagnostic, got {len(diags)}'
assert diags[0]['module'] == 'test_module'
assert diags[0]['message'] == 'something went wrong'
print('OK')
")
assert_equals "DIAG-01: capture diagnostic" "$OUT" "OK"
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL (_capture_diagnostic not defined)

- [ ] **Step 3: Implement diagnostic capture and degraded pill**

In `src/statusline.py`, add the diagnostic capture function (near the styling helpers):

```python
def _capture_diagnostic(state: dict, module: str, message: str) -> None:
    """Record a diagnostic event for degraded-mode rendering."""
    diags = state.setdefault("_diagnostics", [])
    diags.append({"module": module, "message": message, "ts": time.time()})
```

Add the degraded pill renderer (near other module renderers):

```python
def render_degraded(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render degraded-mode pill when diagnostics are captured."""
    diags = state.get("_diagnostics", [])
    if not diags:
        return None
    count = len(diags)
    modules = sorted(set(d["module"] for d in diags))
    text = f"\u26a0 {count} err: {','.join(modules)}"
    if NO_COLOR:
        return f"[{text}]"
    return style(f" {text} ", "#bf616a", True, "#3b4252")
```

Register `render_degraded` in MODULE_RENDERERS:

```python
    "degraded": render_degraded,
```

Add `"degraded"` to the end of DEFAULT_LINE1 (it only shows when there are diagnostics):

```python
DEFAULT_LINE1 = ["model", "token_in", "token_out", "context_bar",
                 "cache_rate", "duration", "degraded"]
```

Add a DEFAULT_THEME entry for degraded:

```python
    "degraded": {
        "enabled": True,
        "color": "#bf616a",
        "bg": "#3b4252",
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test-statusline.sh 2>&1 | grep DIAG-01`
Expected: PASS

- [ ] **Step 5: Write failing test — degraded pill renders when diagnostics present**

```bash
echo "  DIAG-02: degraded pill renders with diagnostics"
OUT=$(run_py "
import os
os.environ['NO_COLOR'] = '1'
from statusline import render_degraded, DEFAULT_THEME

# No diagnostics → None
state_clean = {}
assert render_degraded(state_clean, DEFAULT_THEME) is None

# With diagnostics → visible pill
state_diag = {'_diagnostics': [
    {'module': 'cpu', 'message': 'sysctl failed', 'ts': 0},
    {'module': 'obs', 'message': 'package not found', 'ts': 0},
]}
result = render_degraded(state_diag, DEFAULT_THEME)
assert result is not None, 'should render pill'
assert '2 err' in result, f'should show count: {result}'
assert 'cpu' in result, f'should list module: {result}'
print('OK')
")
assert_equals "DIAG-02: degraded pill" "$OUT" "OK"
```

- [ ] **Step 6: Run test to verify it passes (implementation from Step 3)**

Expected: PASS

- [ ] **Step 7: Wire _capture_diagnostic into key error handlers**

Replace the bare `except: pass` in these critical paths:

In `collect_system_data`, change the collector exception handler:

```python
        try:
            fn(state)
            _cache_module(new_cache, state, name, now)
        except Exception as exc:
            _capture_diagnostic(state, name, str(exc))
            _apply_cached(state, cache, name, now)
```

In `_inject_obs_counters`, change the outer exception handler:

```python
    except Exception as exc:
        _capture_diagnostic(state, "obs", str(exc))
```

In `_try_obs_snapshot`, change the outer exception handler:

```python
    except Exception as exc:
        _capture_diagnostic(state, "snapshot", str(exc))
        try:
            if package_root:
                update_health(package_root, "statusline_capture", "degraded",
                             warning={"code": "STATUSLINE_APPEND_FAILED"})
        except Exception:
            pass
```

In `main()`, wrap the render call:

```python
    line = render(state, theme)
    if not line and state.get("_diagnostics"):
        # Total failure — at minimum show the degraded pill
        line = render_degraded(state, theme) or ""
```

- [ ] **Step 8: Commit**

```bash
git add src/statusline.py tests/test-statusline.sh
git commit -m "feat(diagnostics): capture errors and show degraded pill

Replaces silent 'except: pass' in collectors, obs injection, and
snapshot with structured diagnostic capture. Shows a visible degraded
pill (e.g., '⚠ 2 err: cpu,obs') on line 1 when errors occur, so
the statusline never goes silently blank."
```

---

### Task 5: Payload Schema Fingerprint

**Files:**
- Modify: `src/context_overhead.py` (~line 716, inject_context_overhead)
- Modify: `src/statusline.py` (normalize, to extract fingerprint)
- Modify: `tests/test-statusline.sh`

- [ ] **Step 1: Write failing test — fingerprint detects schema change**

```bash
echo "  FINGER-01: payload fingerprint detects schema change"
OUT=$(run_py "
from statusline import _payload_fingerprint

# Same schema → same fingerprint
fp1 = _payload_fingerprint({'model': {}, 'cost': {}, 'context_window': {}})
fp2 = _payload_fingerprint({'model': {}, 'cost': {}, 'context_window': {}})
assert fp1 == fp2, f'same schema should match: {fp1} vs {fp2}'

# Different schema → different fingerprint
fp3 = _payload_fingerprint({'model': {}, 'cost': {}, 'context_window': {}, 'new_field': {}})
assert fp1 != fp3, f'different schema should differ: {fp1} vs {fp3}'

# Value changes don't affect fingerprint (schema-only)
fp4 = _payload_fingerprint({'model': {'id': 'opus'}, 'cost': {'total': 5}, 'context_window': {'used': 50}})
assert fp1 == fp4, f'value changes should not affect fingerprint: {fp1} vs {fp4}'
print('OK')
")
assert_equals "FINGER-01: schema fingerprint" "$OUT" "OK"
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL (_payload_fingerprint not defined)

- [ ] **Step 3: Implement payload fingerprint**

In `src/statusline.py`, add the fingerprint function:

```python
def _payload_fingerprint(payload: dict) -> str:
    """Schema-only fingerprint of the payload structure.

    Hashes the sorted top-level keys and the type/keys of their values.
    Value changes don't affect the fingerprint — only structural changes do.
    Used to detect CC payload format changes across updates.
    """
    schema_parts = []
    for key in sorted(payload.keys()):
        val = payload[key]
        if isinstance(val, dict):
            sub_keys = ",".join(sorted(val.keys()))
            schema_parts.append(f"{key}:dict({sub_keys})")
        elif isinstance(val, list):
            schema_parts.append(f"{key}:list")
        else:
            schema_parts.append(f"{key}:{type(val).__name__}")
    schema_str = "|".join(schema_parts)
    return hashlib.sha256(schema_str.encode()).hexdigest()[:16]
```

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS

- [ ] **Step 5: Write failing test — fingerprint mismatch triggers diagnostic**

```bash
echo "  FINGER-02: schema mismatch triggers diagnostic"
OUT=$(run_py "
import time, os
os.environ['NO_COLOR'] = '1'
import statusline
from statusline import _init_session_paths, _payload_fingerprint, save_cache, load_cache

_init_session_paths('finger-test')

# Simulate a stored fingerprint from a previous CC version
old_fp = _payload_fingerprint({'model': {}, 'cost': {}})
cache = {'_obs': {'finger-test': {'payload_fingerprint': old_fp, 'overhead_ts': time.time()}}}
save_cache(cache)

# New payload has different schema (CC updated)
new_payload = {'model': {}, 'cost': {}, 'context_window': {}, 'new_v3_field': {}}
new_fp = _payload_fingerprint(new_payload)
assert old_fp != new_fp, 'schemas should differ'

# Check that fingerprint validation would detect this
state = {}
statusline._check_payload_fingerprint(state, new_payload)
diags = state.get('_diagnostics', [])
assert len(diags) == 1, f'expected 1 diagnostic, got {diags}'
assert 'schema' in diags[0]['message'].lower(), f'should mention schema: {diags[0]}'
print('OK')

# Cleanup
os.unlink(statusline.CACHE_PATH)
_init_session_paths(None)
")
assert_equals "FINGER-02: schema mismatch diagnostic" "$OUT" "OK"
```

- [ ] **Step 6: Run test to verify it fails**

Expected: FAIL (_check_payload_fingerprint not defined)

- [ ] **Step 7: Implement schema validation in main()**

In `src/statusline.py`, add the fingerprint checker:

```python
def _check_payload_fingerprint(state: dict, payload: dict) -> None:
    """Compare payload schema to cached fingerprint. Captures diagnostic on mismatch.

    On first invocation per session, stores the fingerprint.
    On subsequent invocations, compares. Mismatch means CC updated its
    payload format — overhead/obs parsing may be silently wrong.
    """
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return
    fp = _payload_fingerprint(payload)
    cache = load_cache()
    obs = cache.get("_obs", {})
    sc = obs.get(session_id, {})
    stored_fp = sc.get("payload_fingerprint")
    if stored_fp is None:
        # First invocation — store fingerprint
        sc["payload_fingerprint"] = fp
        obs[session_id] = sc
        cache["_obs"] = obs
        save_cache(cache)
    elif stored_fp != fp:
        _capture_diagnostic(
            state, "schema",
            f"Payload schema changed (was {stored_fp[:8]}, now {fp[:8]}). "
            "CC may have updated — overhead estimates could be stale."
        )
```

Wire it into `main()` after session path init:

```python
    _init_session_paths(session_id) if isinstance(session_id, str) and session_id else None
    _check_payload_fingerprint(state, payload)
```

Wait — `state` doesn't exist yet at that point. Move it after normalize:

```python
    state = normalize(payload)
    _check_payload_fingerprint(state, payload)
```

- [ ] **Step 8: Run test to verify it passes**

Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/statusline.py tests/test-statusline.sh
git commit -m "feat(fingerprint): detect CC payload schema changes

Hashes payload structure on first invocation, compares on subsequent
calls. Schema mismatch (from CC updates) triggers a visible diagnostic
instead of silent breakage. Only structural changes trigger — value
changes are ignored."
```

---

### Task 6: Integration Verification

**Files:**
- Modify: `tests/test-statusline.sh` (integration tests)

- [ ] **Step 1: Write end-to-end integration test**

```bash
echo "  INTEG-01: full pipeline with session isolation + diagnostics"
OUT=$(run_py "
import os, json
os.environ['NO_COLOR'] = '1'
os.environ['QLINE_NO_COLLECT'] = '1'
import statusline
from statusline import normalize, load_config, render, _init_session_paths, _inject_obs_counters, _check_payload_fingerprint
from context_overhead import inject_context_overhead

payload = {
    'session_id': 'integ-test-001',
    'model': {'id': 'claude-opus-4-6', 'display_name': 'Opus 4.6 (1M context)'},
    'cost': {'total_cost_usd': 1.50, 'total_duration_ms': 120000},
    'context_window': {
        'used_percentage': 35,
        'context_window_size': 1000000,
        'total_input_tokens': 350000,
        'total_output_tokens': 50000,
    },
}

# Init session
sid = payload['session_id']
_init_session_paths(sid)
theme = load_config()
state = normalize(payload)
_check_payload_fingerprint(state, payload)
_inject_obs_counters(state, payload)

cache_ctx = {
    'load_cache': statusline.load_cache,
    'save_cache': statusline.save_cache,
    'cache_max_age': statusline.CACHE_MAX_AGE_S,
    'obs_available': False,
    'resolve_package_root': None,
}
inject_context_overhead(state, payload, theme, cache_ctx)

output = render(state, theme)
assert output, 'should produce output'
assert 'Opus' in output, f'model missing: {output[:100]}'
assert '35%' in output, f'context pct missing: {output[:200]}'
# No diagnostics → no degraded pill
assert 'err' not in output.lower(), f'unexpected degraded pill: {output}'
print('OK')

# Cleanup
os.unlink(statusline.CACHE_PATH)
_init_session_paths(None)
")
assert_equals "INTEG-01: full pipeline" "$OUT" "OK"
```

- [ ] **Step 2: Run full test suite**

Run: `bash tests/test-statusline.sh 2>&1 | tail -5`
Expected: No new failures from our changes.

- [ ] **Step 3: Commit test**

```bash
git add tests/test-statusline.sh
git commit -m "test: integration test for session isolation + diagnostics pipeline"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** Session collision (Task 1), stale data (Tasks 2-3), silent breakage (Tasks 4-5), integration (Task 6)
- [x] **Placeholder scan:** All steps have code blocks. No TBD/TODO.
- [x] **Type consistency:** `_init_session_paths`, `_session_hash`, `_capture_diagnostic`, `_payload_fingerprint`, `_check_payload_fingerprint`, `_freshness_suffix`, `render_degraded` — names consistent across tasks.
- [x] **Scope check:** 6 focused tasks, each independently committable and testable.
