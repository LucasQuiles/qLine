# qLine Duplicate Function Consolidation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate semantic duplicate functions identified by the 204-function dedup scan, reducing maintenance surface by ~200 lines without changing any observable behavior.

**Architecture:** Five targeted consolidations in dependency order. Each task preserves the 300-test safety net — tests run green before and after every commit. `scripts/hook_utils.py` (the largest duplicate source) is deleted entirely; `hooks/hook_utils.py` becomes the single canonical copy. Manifest readers are wired through `load_manifest`. Cost renderers are parameterized. Hook preamble boilerplate is extracted into `run_obs_hook`.

**Tech Stack:** Python 3.10+, bash tests (`tests/test-statusline.sh`), pytest (`hooks/tests/`)

**Pre-requisite:** The interpreter resolution fix (run-hook shim + hooks.json + test harness) must be committed first. It is ready but uncommitted on the current working tree.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `scripts/hook_utils.py` | Delete | Eliminated — all callers use `hooks/hook_utils.py` |
| `hooks/hook_utils.py` | Modify | Add `deny`, `get_tool_info`, `run_obs_hook`; fix `allow_with_context` |
| `hooks/obs_utils.py` | Read-only | `load_manifest` already exists at line 393 |
| `src/statusline.py` | Modify | Wire `_read_obs_health` through `load_manifest`; consolidate cost renderers |
| `hooks/obs-stop-cache.py` | Modify | Wire `_read_compaction_count` through `load_manifest` |
| `hooks/obs-*.py` (11 files) | Modify | Replace preamble with `run_obs_hook` call |
| `install.sh` | Modify | Remove `scripts/hook_utils.py` references |
| `uninstall.sh` | Modify | Remove `scripts/hook_utils.py` references |
| `tests/test-statusline.sh` | Verify | Must pass 300/300 after every task |
| `hooks/tests/test_hook_utils_v2.py` | Modify | Add tests for `run_obs_hook`, `deny`, `allow_with_context` |

---

### Task 1: Wire manifest readers through `load_manifest` (R3)

Smallest, safest consolidation. No cross-file import changes.

**Files:**
- Modify: `src/statusline.py:2538-2546` (`_read_obs_health`)
- Modify: `hooks/obs-stop-cache.py:119-127` (`_read_compaction_count`)
- Read: `hooks/obs_utils.py:393` (`load_manifest` — already exists)

- [ ] **Step 1: Verify `load_manifest` is importable from statusline.py**

```bash
"$PYTHON" -c "
import sys; sys.path.insert(0, 'hooks')
from obs_utils import load_manifest
print('OK:', type(load_manifest))
"
```

Expected: `OK: <class 'function'>`

- [ ] **Step 2: Replace `_read_obs_health` with one-liner**

In `src/statusline.py`, replace lines 2538-2546:

```python
def _read_obs_health(package_root: str) -> str:
    """Read overall health from manifest."""
    manifest = os.path.join(package_root, "manifest.json")
    try:
        with open(manifest) as f:
            m = json.load(f)
        return m.get("health", {}).get("overall", "unknown")
    except Exception:
        return "unknown"
```

With:

```python
def _read_obs_health(package_root: str) -> str:
    """Read overall health from manifest."""
    return load_manifest(package_root).get("health", {}).get("overall", "unknown")
```

Note: `load_manifest` already returns `{}` on any error, so the `try/except` is handled upstream.

- [ ] **Step 3: Add `load_manifest` import to statusline.py**

Find the existing `obs_utils` import block (near the top, where `resolve_package_root_env` is imported) and add `load_manifest`:

```python
from obs_utils import resolve_package_root_env, load_manifest
```

If `obs_utils` is imported conditionally (behind a try/except), add `load_manifest` to that same block.

- [ ] **Step 4: Replace `_read_compaction_count` in obs-stop-cache.py**

In `hooks/obs-stop-cache.py`, replace lines 119-127:

```python
def _read_compaction_count(package_root: str) -> int:
    """Read current compaction count from manifest compactions array."""
    manifest_path = os.path.join(package_root, "manifest.json")
    try:
        with open(manifest_path) as f:
            m = json.load(f)
        return len(m.get("compactions", []))
    except Exception:
        return 0
```

With:

```python
def _read_compaction_count(package_root: str) -> int:
    """Read current compaction count from manifest compactions array."""
    return len(load_manifest(package_root).get("compactions", []))
```

- [ ] **Step 5: Add `load_manifest` to obs-stop-cache.py imports**

Add `load_manifest` to the existing `from obs_utils import ...` line near the top of the file.

- [ ] **Step 6: Run tests**

```bash
bash tests/test-statusline.sh
```

Expected: `=== Results: 300/300 passed, 0 failed ===`

- [ ] **Step 7: Commit**

```bash
git add src/statusline.py hooks/obs-stop-cache.py
git commit -m "refactor: wire manifest readers through load_manifest

_read_obs_health and _read_compaction_count now delegate to
obs_utils.load_manifest instead of independently opening manifest.json.
Eliminates 2 duplicate file-open patterns (~12 lines removed)."
```

---

### Task 2: Eliminate `scripts/hook_utils.py` fork (R1)

The biggest consolidation — removes an entire 191-line file.

**Files:**
- Delete: `scripts/hook_utils.py`
- Modify: `hooks/hook_utils.py` — add `deny`, `get_tool_info`; fix `allow_with_context`
- Modify: `install.sh` — remove `scripts/hook_utils.py` references
- Modify: `hooks/tests/test_hook_utils_v2.py` — add tests for new functions

- [ ] **Step 1: Write tests for `deny` and `get_tool_info`**

Add to `hooks/tests/test_hook_utils_v2.py`:

```python
def test_deny_outputs_block_json(capsys):
    """deny() prints a block decision JSON to stdout."""
    import json
    from unittest.mock import patch
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from hook_utils import deny
    with pytest.raises(SystemExit) as exc_info:
        deny("test reason")
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["decision"] == "block"
    assert parsed["reason"] == "test reason"


def test_get_tool_info_extracts_fields():
    """get_tool_info() returns (tool_name, tool_input) from hook data."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from hook_utils import get_tool_info
    data = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    name, inp = get_tool_info(data)
    assert name == "Bash"
    assert inp == {"command": "ls"}


def test_get_tool_info_missing_fields():
    """get_tool_info() returns empty defaults for missing fields."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from hook_utils import get_tool_info
    name, inp = get_tool_info({})
    assert name == ""
    assert inp == {}
```

- [ ] **Step 2: Run tests — verify they fail (functions don't exist yet)**

```bash
cd /Users/q/qline && "$PYTHON" -m pytest hooks/tests/test_hook_utils_v2.py -v -k "deny or get_tool_info"
```

Expected: FAIL — `ImportError: cannot import name 'deny'`

- [ ] **Step 3: Copy `deny` and `get_tool_info` from scripts/ to hooks/hook_utils.py**

Read them from `scripts/hook_utils.py` and add to `hooks/hook_utils.py` after the `block_stop` function:

```python
def deny(reason: str) -> None:
    """Print a deny/block decision and exit 0. Used by PreToolUse hooks."""
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def get_tool_info(data: dict) -> tuple[str, dict]:
    """Extract (tool_name, tool_input) from hook input data."""
    return data.get("tool_name", ""), data.get("tool_input", {})
```

- [ ] **Step 4: Fix `allow_with_context` in hooks/hook_utils.py**

The current hooks/ version emits `{"decision": "allow", "message": ...}` which is incorrect. The scripts/ version correctly uses `{"additionalContext": ...}` + `sys.exit(0)`. Replace:

```python
def allow_with_context(message: str, event: str = "PreToolUse") -> None:
    """Print an allow decision with context message. Used by non-qLine hooks."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event,
            "decision": "allow",
            "message": message,
        }
    }))
```

With the correct Claude Code protocol shape:

```python
def allow_with_context(context: str, event: str = "PreToolUse") -> None:
    """Print an allow decision with additional context injected into the conversation."""
    print(json.dumps({
        "additionalContext": context,
    }))
    sys.exit(0)
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
"$PYTHON" -m pytest hooks/tests/test_hook_utils_v2.py -v -k "deny or get_tool_info"
```

Expected: PASS (3/3)

- [ ] **Step 6: Delete `scripts/hook_utils.py`**

```bash
rm scripts/hook_utils.py
rmdir scripts/ 2>/dev/null || true
```

- [ ] **Step 7: Remove `scripts/hook_utils.py` references from install.sh**

In `install.sh`, find the line referencing `$DEST_DIR/scripts/hook_utils.py` in the stale-copy cleanup loop (around line 89) and remove it. The `scripts/` directory reference should be removed from the glob.

- [ ] **Step 8: Run full test suite**

```bash
bash tests/test-statusline.sh
```

Expected: `=== Results: 300/300 passed, 0 failed ===`

- [ ] **Step 9: Commit**

```bash
git add -A scripts/ hooks/hook_utils.py hooks/tests/test_hook_utils_v2.py install.sh
git commit -m "refactor: eliminate scripts/hook_utils.py fork

Delete the 191-line scripts/hook_utils.py that was a systematic copy of
hooks/hook_utils.py. Move deny() and get_tool_info() to the canonical
hooks/ copy. Fix allow_with_context to use the correct additionalContext
protocol shape instead of the broken decision/message shape."
```

---

### Task 3: Consolidate cost renderers (R4)

**Files:**
- Modify: `src/statusline.py:1940-1969` — extract shared helper, simplify both functions

- [ ] **Step 1: Run existing cost renderer tests to establish baseline**

```bash
bash tests/test-statusline.sh --section obs 2>&1 | tail -5
bash tests/test-statusline.sh --section renderer 2>&1 | tail -5
```

Expected: All pass.

- [ ] **Step 2: Create `_render_cost_pill` helper**

Add just above `render_daily_cost` in `src/statusline.py`:

```python
def _render_cost_pill(
    state: dict[str, Any],
    theme: dict[str, Any],
    state_key: str,
    theme_key: str,
    fmt: str,
    warn_default: float,
    crit_default: float,
) -> str | None:
    """Shared renderer for threshold-colored cost pills."""
    cost = state.get(state_key)
    if cost is None:
        return None
    cfg = theme.get(theme_key, {})
    warn_t = cfg.get("warn_threshold", warn_default)
    crit_t = cfg.get("critical_threshold", crit_default)
    text = fmt.format(cost=cost)
    if cost >= crit_t:
        return _pill(text, cfg, cfg.get("critical_color", "#d06070"), True, theme)
    if cost >= warn_t:
        return _pill(text, cfg, cfg.get("warn_color", "#f0d399"), theme=theme)
    return _pill(text, cfg, theme=theme)
```

- [ ] **Step 3: Rewrite `render_daily_cost` and `render_weekly_cost` as one-liners**

```python
def render_daily_cost(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render today's cumulative cost from session snapshot history."""
    return _render_cost_pill(state, theme, "daily_cost", "daily_cost",
                             "\U000f00ed${cost:.0f}", 200, 400)


def render_weekly_cost(state: dict[str, Any], theme: dict[str, Any]) -> str | None:
    """Render this week's cumulative cost."""
    return _render_cost_pill(state, theme, "weekly_cost", "weekly_cost",
                             "${cost:.0f}/wk", 1000, 2000)
```

- [ ] **Step 4: Run tests**

```bash
bash tests/test-statusline.sh
```

Expected: `=== Results: 300/300 passed, 0 failed ===`

- [ ] **Step 5: Commit**

```bash
git add src/statusline.py
git commit -m "refactor: extract _render_cost_pill from daily/weekly cost renderers

Both functions were near-identical — same data source, same threshold
pattern, differing only in state key, format string, and defaults.
Now delegate to a shared helper (~15 lines removed)."
```

---

### Task 4: Extract `run_obs_hook` dispatcher (R6, obs hooks only)

Targets the 11 `obs-*.py` hooks that share a 6-line preamble. Does NOT attempt to cover gate hooks or non-obs hooks.

**Files:**
- Modify: `hooks/hook_utils.py` — add `run_obs_hook`
- Modify: 11 files: `hooks/obs-pretool-read.py`, `hooks/obs-posttool-bash.py`, `hooks/obs-posttool-edit.py`, `hooks/obs-posttool-write.py`, `hooks/obs-posttool-failure.py`, `hooks/obs-prompt-submit.py`, `hooks/obs-precompact.py`, `hooks/obs-stop-cache.py`, `hooks/obs-session-start.py`, `hooks/obs-session-end.py`, `hooks/obs-subagent-stop.py`
- Modify: `hooks/tests/test_hook_utils_v2.py` — add test for `run_obs_hook`

- [ ] **Step 1: Write failing test for `run_obs_hook`**

Add to `hooks/tests/test_hook_utils_v2.py`:

```python
def test_run_obs_hook_calls_handler_with_parsed_input(monkeypatch):
    """run_obs_hook parses stdin, validates session_id, resolves package, calls handler."""
    import sys, json, io
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    payload = json.dumps({"session_id": "test-123", "tool_name": "Read"})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    calls = []

    def handler(input_data, session_id, package_root):
        calls.append((session_id, package_root))

    # Mock resolve_package_root_env to return a fake path
    import hook_utils
    monkeypatch.setattr(hook_utils, "_resolve_package_root_for_obs",
                        lambda sid: "/tmp/fake-pkg")

    with pytest.raises(SystemExit) as exc_info:
        hook_utils.run_obs_hook(handler, "test-hook", "TestEvent")
    assert exc_info.value.code == 0
    assert len(calls) == 1
    assert calls[0] == ("test-123", "/tmp/fake-pkg")


def test_run_obs_hook_exits_on_missing_session_id(monkeypatch):
    """run_obs_hook exits 0 when session_id is missing."""
    import sys, json, io
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    payload = json.dumps({"tool_name": "Read"})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    import hook_utils
    calls = []

    with pytest.raises(SystemExit) as exc_info:
        hook_utils.run_obs_hook(lambda *a: calls.append(1), "test", "Test")
    assert exc_info.value.code == 0
    assert len(calls) == 0
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
"$PYTHON" -m pytest hooks/tests/test_hook_utils_v2.py -v -k "run_obs_hook"
```

Expected: FAIL — `AttributeError: module 'hook_utils' has no attribute 'run_obs_hook'`

- [ ] **Step 3: Implement `run_obs_hook` in hooks/hook_utils.py**

Add after `run_fail_open`:

```python
def _resolve_package_root_for_obs(session_id: str) -> str | None:
    """Resolve package root for obs hooks. Thin wrapper for testability."""
    try:
        from obs_utils import resolve_package_root_env
        return resolve_package_root_env(session_id)
    except ImportError:
        return None


def run_obs_hook(
    handler: Callable[[dict, str, str], None],
    hook_name: str,
    event_name: str,
) -> None:
    """Standard obs hook dispatcher: read stdin, validate, resolve package, call handler.

    Handles the common 6-line preamble shared by all 11 obs hooks:
      1. read_hook_input() — exit 0 if empty
      2. get session_id — exit 0 if missing
      3. resolve_package_root_env(session_id) — exit 0 if None
      4. call handler(input_data, session_id, package_root)
      5. exit 0

    The handler receives validated input_data, session_id, and package_root.
    Wrap with run_fail_open() at the call site for crash resistance.
    """
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = input_data.get("session_id")
    if not session_id:
        sys.exit(0)

    package_root = _resolve_package_root_for_obs(session_id)
    if package_root is None:
        sys.exit(0)

    handler(input_data, session_id, package_root)
    sys.exit(0)
```

- [ ] **Step 4: Run test — verify it passes**

```bash
"$PYTHON" -m pytest hooks/tests/test_hook_utils_v2.py -v -k "run_obs_hook"
```

Expected: PASS (2/2)

- [ ] **Step 5: Migrate ONE hook as proof — `obs-subagent-stop.py`**

This is the simplest obs hook. Replace its `main()`:

```python
def _handle(input_data: dict, session_id: str, package_root: str) -> None:
    agent_id = input_data.get("agent_id", "")
    agent_type = input_data.get("agent_type", "")
    agent_transcript_path = input_data.get("agent_transcript_path", "")
    last_assistant_message = input_data.get("last_assistant_message", "")
    message_length = len(last_assistant_message)

    # ... rest of existing main() body starting from Step 1 ...
```

And change the entry point:

```python
if __name__ == "__main__":
    from hook_utils import run_obs_hook, run_fail_open
    run_fail_open(lambda: run_obs_hook(_handle, "obs-subagent-stop", "SubagentStop"),
                  "obs-subagent-stop", "SubagentStop")
```

- [ ] **Step 6: Run full test suite**

```bash
bash tests/test-statusline.sh
```

Expected: `=== Results: 300/300 passed, 0 failed ===`

- [ ] **Step 7: Commit proof-of-concept**

```bash
git add hooks/hook_utils.py hooks/obs-subagent-stop.py hooks/tests/test_hook_utils_v2.py
git commit -m "refactor: add run_obs_hook dispatcher, migrate obs-subagent-stop

Extract the 6-line preamble shared by all 11 obs hooks into
run_obs_hook(handler, name, event). Migrate obs-subagent-stop.py
as proof of concept. Remaining 10 obs hooks follow in next commit."
```

- [ ] **Step 8: Migrate remaining 10 obs hooks**

Apply the same pattern to each. For each hook:
1. Extract the body after the preamble into `_handle(input_data, session_id, package_root)`
2. Remove the preamble lines (read_hook_input, session_id check, resolve_package_root_env, exit)
3. Update the `__main__` block

Hooks to migrate: `obs-pretool-read.py`, `obs-posttool-bash.py`, `obs-posttool-edit.py`, `obs-posttool-write.py`, `obs-posttool-failure.py`, `obs-prompt-submit.py`, `obs-precompact.py`, `obs-stop-cache.py`, `obs-session-start.py`, `obs-session-end.py`

**Important:** Some hooks have extra preamble (e.g., `obs-pretool-read.py` checks `tool_name != "Read"` before resolving package_root). For these, move the tool-name check into `_handle` and return early:

```python
def _handle(input_data, session_id, package_root):
    if input_data.get("tool_name") != "Read":
        return  # Not our tool
    # ... rest of handler ...
```

- [ ] **Step 9: Run full test suite**

```bash
bash tests/test-statusline.sh
```

Expected: `=== Results: 300/300 passed, 0 failed ===`

- [ ] **Step 10: Commit batch migration**

```bash
git add hooks/obs-*.py
git commit -m "refactor: migrate remaining 10 obs hooks to run_obs_hook

All 11 obs hooks now use the shared dispatcher. Each hook's main()
is replaced by a _handle(input_data, session_id, package_root) function
that receives validated, pre-resolved arguments. ~60 lines of
duplicated preamble eliminated."
```

---

## Deferred (not in this plan)

| Item | Reason |
|------|--------|
| **R5: Derived-metric renderer consolidation** | The 8 functions have genuinely diverse computation. A generic helper risks becoming harder to read than the originals. The `_render_obs_counter` pattern works because obs counters are trivial lookups; derived metrics have real math. Defer until a clear data-driven pattern emerges from use. |
| **R2: `_extract_usage` fallback removal** | Already consolidated per prior plan. The 14-line fallback serves test isolation. Leave as-is. |
| **DRY for resolver candidate list** | Three copies of `python3.13 python3.12 ...` across `run-hook`, `test-statusline.sh`, and `install.sh`. Acceptable — different execution contexts, small blast radius. |
| **`_load_alert`/`_save_alert` consolidation** | Local closures inside `render_context_bar`. The load/save pattern is simple enough that extracting it adds more indirection than it saves. |

---

## Execution Checklist

- [ ] Commit interpreter fix first (ready on working tree)
- [ ] Task 1: Manifest readers (R3) — ~10 min
- [ ] Task 2: Scripts fork elimination (R1) — ~15 min
- [ ] Task 3: Cost renderers (R4) — ~10 min
- [ ] Task 4: Hook dispatcher (R6) — ~25 min
- [ ] Final: Run full test suite, verify 300/300
