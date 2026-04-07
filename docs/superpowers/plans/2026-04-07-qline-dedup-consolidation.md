# qLine Duplicate Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate ~218 lines of semantic duplication across 14 duplicate groups identified by the duplicate-intent analysis.

**Architecture:** Three-phase consolidation (quick wins → boilerplate → architectural) moving shared logic into `hook_utils.py` and `obs_utils.py`. Each task is independently testable and commitable.

**Tech Stack:** Python 3.12, no new dependencies. Shell test harness at `tests/test-statusline.sh`.

---

## File Structure

| File | Role | Changes |
|------|------|---------|
| `hooks/hook_utils.py` | Shared hook infrastructure | Add: `resolve_task_list_id`, `find_latest_plan`, `iter_open_tasks`, `hash16`, `now_iso` (re-export) |
| `hooks/obs_utils.py` | Session package management | Add: `resolve_package_root_env`, `load_manifest`, `extract_usage_full` |
| `hooks/precompact-preserve.py` | PreCompact hook | Remove: `_resolve_task_list_id`, `_get_active_plan`, `_get_open_tasks`. Import from hook_utils. |
| `hooks/session-end-summary.py` | SessionEnd hook | Remove: `_resolve_task_list_id`, `_get_active_plan`, `_count_open_tasks`. Import from hook_utils. |
| `hooks/obs-posttool-bash.py` | Bash hook | Remove: `_hash16`. Import from hook_utils. |
| `hooks/obs-prompt-submit.py` | Prompt hook | Replace inline hash. Import from hook_utils. |
| `hooks/obs-posttool-edit.py` | Edit hook | Replace inline hash. Import from hook_utils. |
| `hooks/obs-posttool-write.py` | Write hook | Replace inline hash. Import from hook_utils. |
| `hooks/obs-posttool-failure.py` | Failure hook | Replace inline hash. Import from hook_utils. |
| `hooks/obs-stop-cache.py` | Stop cache hook | Remove: `_extract_usage_from_entry`. Import from obs_utils. |
| `src/context_overhead.py` | Overhead estimation | Remove: `_extract_usage`. Import from obs_utils. |
| All 13 `hooks/obs-*.py` | Obs hooks | Replace OBS_ROOT boilerplate with `resolve_package_root_env`. |

---

## Phase A: Quick Wins (H2 + H3 + M4 + M3)

### Task 1: Move `_resolve_task_list_id` to hook_utils.py (H2)

**Files:**
- Modify: `hooks/hook_utils.py` — add function after `sanitize_task_list_id`
- Modify: `hooks/precompact-preserve.py:95-105` — delete local, add import
- Modify: `hooks/session-end-summary.py:89-99` — delete local, add import

- [ ] **Step 1: Add `resolve_task_list_id` to hook_utils.py**

Read `hooks/precompact-preserve.py` lines 95-105 for the source. Add to `hooks/hook_utils.py` after `sanitize_task_list_id` (~line 105):

```python
def resolve_task_list_id(session_id):
    """Resolve the local task-list directory ID."""
    override = os.environ.get("CLAUDE_CODE_TASK_LIST_ID")
    if override:
        return override
    return sanitize_task_list_id(session_id)
```

- [ ] **Step 2: Update precompact-preserve.py**

Replace the local `_resolve_task_list_id` function with an import. Add to the existing `from hook_utils import ...` line:

```python
from hook_utils import run_fail_open, log_hook_diagnostic, sanitize_task_list_id, resolve_task_list_id
```

Delete lines 95-105 (the local `_resolve_task_list_id` function).
Update the call site: change `_resolve_task_list_id(session_id)` to `resolve_task_list_id(session_id)`.

- [ ] **Step 3: Update session-end-summary.py**

Same pattern: add `resolve_task_list_id` to the import, delete lines 89-99, update call site.

- [ ] **Step 4: Run tests**

Run: `cd /Users/q/LAB/qLine/.worktrees/research && NO_COLOR=1 QLINE_NO_COLLECT=1 bash tests/test-statusline.sh 2>&1 | tail -3`
Expected: 192/235 passed (no regression)

- [ ] **Step 5: Commit**

```bash
git add hooks/hook_utils.py hooks/precompact-preserve.py hooks/session-end-summary.py
git commit -m "refactor: consolidate _resolve_task_list_id into hook_utils (H2)"
```

---

### Task 2: Extract `_find_latest_plan` to hook_utils.py (H3)

**Files:**
- Modify: `hooks/hook_utils.py` — add function
- Modify: `hooks/precompact-preserve.py:107-125` — delete local, add import
- Modify: `hooks/session-end-summary.py:101-115` — delete local, add import

- [ ] **Step 1: Read both implementations**

Read `hooks/precompact-preserve.py` lines 107-125 and `hooks/session-end-summary.py` lines 101-115. Note the format difference: one returns `"Active plan: {name}"`, the other returns bare `os.path.basename(latest)`.

- [ ] **Step 2: Add `find_latest_plan` to hook_utils.py**

Add after `resolve_task_list_id`:

```python
def find_latest_plan():
    """Find the most recently modified plan file. Returns basename or None."""
    import glob
    plans = glob.glob(os.path.expanduser("~/.claude/plans/*.md"))
    if not plans:
        return None
    try:
        latest = max(plans, key=os.path.getmtime)
        return os.path.basename(latest)
    except (OSError, ValueError):
        return None
```

- [ ] **Step 3: Update precompact-preserve.py**

Import `find_latest_plan` from hook_utils. Replace the local `_get_active_plan` call. The caller currently expects `f"Active plan: {name}"` — format at the call site:

```python
plan_name = find_latest_plan()
plan_line = f"Active plan: {plan_name}" if plan_name else None
```

Delete the local `_get_active_plan` function.

- [ ] **Step 4: Update session-end-summary.py**

Import `find_latest_plan`. Replace the local `_get_active_plan` call. This caller already uses bare filename, so `find_latest_plan()` returns exactly what it needs.

Delete the local `_get_active_plan` function.

- [ ] **Step 5: Run tests, commit**

Run: `NO_COLOR=1 QLINE_NO_COLLECT=1 bash tests/test-statusline.sh 2>&1 | tail -3`
Expected: 192/235

```bash
git add hooks/hook_utils.py hooks/precompact-preserve.py hooks/session-end-summary.py
git commit -m "refactor: consolidate _get_active_plan into hook_utils.find_latest_plan (H3)"
```

---

### Task 3: Move `_hash16` to hook_utils.py (M4)

**Files:**
- Modify: `hooks/hook_utils.py` — add function
- Modify: `hooks/obs-posttool-bash.py:44-47` — delete local, add import
- Modify: `hooks/obs-prompt-submit.py:66` — replace inline
- Modify: `hooks/obs-posttool-edit.py:122` — replace inline
- Modify: `hooks/obs-posttool-write.py:122` — replace inline
- Modify: `hooks/obs-posttool-failure.py:54` — replace inline

- [ ] **Step 1: Add `hash16` to hook_utils.py**

```python
def hash16(s):
    """SHA-256 truncated to 16 hex chars."""
    import hashlib
    return hashlib.sha256(s.encode()).hexdigest()[:16]
```

- [ ] **Step 2: Update obs-posttool-bash.py**

Delete the local `_hash16` function. Add `hash16` to the hook_utils import. Replace `_hash16(command)` with `hash16(command)`.

- [ ] **Step 3: Update 4 remaining hooks**

For each of `obs-prompt-submit.py`, `obs-posttool-edit.py`, `obs-posttool-write.py`, `obs-posttool-failure.py`:
- Add `hash16` to the `from hook_utils import ...` line
- Replace the inline `hashlib.sha256(...).hexdigest()[:16]` with `hash16(...)`
- Remove the `import hashlib` if it was only used for this

- [ ] **Step 4: Run tests, commit**

Run: `NO_COLOR=1 QLINE_NO_COLLECT=1 bash tests/test-statusline.sh 2>&1 | tail -3`
Expected: 192/235

```bash
git add hooks/hook_utils.py hooks/obs-posttool-bash.py hooks/obs-prompt-submit.py hooks/obs-posttool-edit.py hooks/obs-posttool-write.py hooks/obs-posttool-failure.py
git commit -m "refactor: consolidate hash16 into hook_utils (M4)"
```

---

### Task 4: Replace inline `_now_iso` calls (M3)

**Files:**
- Modify: `hooks/hook_utils.py:71` — replace inline datetime call
- Modify: `hooks/obs-posttool-bash.py` — replace inline
- Modify: `hooks/obs-session-start.py` — replace 3 inline calls

- [ ] **Step 1: Update hook_utils.py**

Add import at top of `hook_utils.py`:

```python
from obs_utils import _now_iso
```

Replace the inline `datetime.now(timezone.utc).isoformat()` at line 71 with `_now_iso()`.

**Note:** `hook_utils` currently does NOT import from `obs_utils`. This creates a new dependency direction. If this is unacceptable (hook_utils should be more primitive than obs_utils), alternatively define `_now_iso` in hook_utils and have obs_utils import from there. Read both files to determine which direction is safer.

- [ ] **Step 2: Update obs-posttool-bash.py and obs-session-start.py**

Both already import from `obs_utils`. Add `_now_iso` to their existing imports. Replace inline `datetime.now(timezone.utc).isoformat()` calls with `_now_iso()`.

- [ ] **Step 3: Run tests, commit**

Run: `NO_COLOR=1 QLINE_NO_COLLECT=1 bash tests/test-statusline.sh 2>&1 | tail -3`
Expected: 192/235

```bash
git add hooks/hook_utils.py hooks/obs-posttool-bash.py hooks/obs-session-start.py
git commit -m "refactor: replace inline timestamp generation with _now_iso (M3)"
```

---

## Phase B: Boilerplate Elimination (M5 + M2 + M1)

### Task 5: Add `resolve_package_root_env` to obs_utils.py (M5)

**Files:**
- Modify: `hooks/obs_utils.py` — add function after `resolve_package_root`
- Modify: All 13 `hooks/obs-*.py` files + `src/statusline.py` (x2) — replace 3-line boilerplate

- [ ] **Step 1: Add the helper to obs_utils.py**

After `resolve_package_root` (~line 245):

```python
def resolve_package_root_env(session_id):
    """Resolve package root, respecting OBS_ROOT env override."""
    obs_root = os.environ.get("OBS_ROOT")
    kwargs = {"obs_root": obs_root} if obs_root else {}
    return resolve_package_root(session_id, **kwargs)
```

- [ ] **Step 2: Update all hooks**

For each of the 13 `hooks/obs-*.py` files, replace the 3-line pattern:
```python
obs_root = os.environ.get("OBS_ROOT")
kwargs = {"obs_root": obs_root} if obs_root else {}
package_root = resolve_package_root(session_id, **kwargs)
```
With:
```python
package_root = resolve_package_root_env(session_id)
```

Add `resolve_package_root_env` to each file's import from obs_utils. Remove `resolve_package_root` from imports where it's no longer directly called.

- [ ] **Step 3: Update statusline.py**

Same replacement at the two sites in `statusline.py` (~lines 1887 and 1941).

- [ ] **Step 4: Run tests, commit**

Run: `NO_COLOR=1 QLINE_NO_COLLECT=1 bash tests/test-statusline.sh 2>&1 | tail -3`
Expected: 192/235

```bash
git add hooks/obs_utils.py hooks/obs-*.py src/statusline.py
git commit -m "refactor: replace OBS_ROOT boilerplate with resolve_package_root_env (M5)"
```

---

### Task 6: Extract `iter_open_tasks` to hook_utils.py (M2)

**Files:**
- Modify: `hooks/hook_utils.py` — add function
- Modify: `hooks/precompact-preserve.py:52-93` — replace with import
- Modify: `hooks/session-end-summary.py:53-87` — replace with import

- [ ] **Step 1: Read both implementations**

Read `precompact-preserve.py` lines 52-93 (`_get_open_tasks`) and `session-end-summary.py` lines 53-87 (`_count_open_tasks`). Extract the shared iteration pattern.

- [ ] **Step 2: Add `iter_open_tasks` to hook_utils.py**

```python
def iter_open_tasks(session_id):
    """Yield (task_dict, filename) for non-completed tasks in session task dir."""
    task_path = os.path.join(
        os.path.expanduser("~"), ".claude", "tasks",
        resolve_task_list_id(session_id)
    )
    if not os.path.isdir(task_path):
        return
    import json
    for fname in sorted(os.listdir(task_path)):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(task_path, fname)) as f:
                task = json.load(f)
            if task.get("status") in ("pending", "in_progress"):
                yield task, fname
        except (json.JSONDecodeError, OSError, KeyError):
            continue
```

- [ ] **Step 3: Update precompact-preserve.py**

Replace `_get_open_tasks` with logic that uses `iter_open_tasks`:

```python
from hook_utils import iter_open_tasks, resolve_task_list_id, find_latest_plan

def _format_open_tasks(session_id):
    """Format open tasks as a text block for compaction context."""
    lines = []
    for task, fname in iter_open_tasks(session_id):
        subject = task.get("subject", fname)
        tid = task.get("id", "?")
        status = task.get("status", "?")
        blocked = task.get("blockedBy", [])
        line = f"  - [{status}] #{tid}: {subject}"
        if blocked:
            line += f" (blocked by: {', '.join(str(b) for b in blocked)})"
        lines.append(line)
    return "\n".join(lines) if lines else None
```

- [ ] **Step 4: Update session-end-summary.py**

Replace `_count_open_tasks` with:

```python
from hook_utils import iter_open_tasks

def _count_open_tasks(session_id):
    total = 0
    in_progress = 0
    for task, _ in iter_open_tasks(session_id):
        total += 1
        if task.get("status") == "in_progress":
            in_progress += 1
    return total, in_progress
```

- [ ] **Step 5: Run tests, commit**

Run: `NO_COLOR=1 QLINE_NO_COLLECT=1 bash tests/test-statusline.sh 2>&1 | tail -3`
Expected: 192/235

```bash
git add hooks/hook_utils.py hooks/precompact-preserve.py hooks/session-end-summary.py
git commit -m "refactor: consolidate task iteration into hook_utils.iter_open_tasks (M2)"
```

---

### Task 7: Promote `load_manifest` to obs_utils.py (M1)

**Files:**
- Modify: `hooks/obs_utils.py` — add public `load_manifest` function
- Modify: `hooks/obs-session-end.py:33-41` — delete local, add import

- [ ] **Step 1: Add `load_manifest` to obs_utils.py**

After the existing `_read_manifest` (~line 375):

```python
def load_manifest(package_root):
    """Load and parse manifest.json from package root. Returns {} on error."""
    manifest_path = os.path.join(package_root, "manifest.json")
    try:
        with open(manifest_path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
```

- [ ] **Step 2: Update obs-session-end.py**

Remove the local `_load_manifest` function. Add `load_manifest` to the import from obs_utils. Update call sites.

- [ ] **Step 3: Run tests, commit**

Run: `NO_COLOR=1 QLINE_NO_COLLECT=1 bash tests/test-statusline.sh 2>&1 | tail -3`
Expected: 192/235

```bash
git add hooks/obs_utils.py hooks/obs-session-end.py
git commit -m "refactor: promote load_manifest to obs_utils public API (M1)"
```

---

## Phase C: Architectural (H4 + H5)

### Task 8: Unify `_extract_usage` functions (H4)

**Files:**
- Modify: `hooks/obs_utils.py` — add `extract_usage_full`
- Modify: `src/context_overhead.py:255-285` — delete local, import shared
- Modify: `hooks/obs-stop-cache.py:96-120` — delete local, import shared

- [ ] **Step 1: Read both implementations**

Read `context_overhead.py` lines 255-285 and `obs-stop-cache.py` lines 96-120. Map the superset of fields both extract.

- [ ] **Step 2: Add `extract_usage_full` to obs_utils.py**

```python
def extract_usage_full(entry):
    """Extract usage tuple from transcript entry.
    
    Returns (usage_dict, model, request_id, entry_id) or (None, None, None, None).
    Handles both message.usage and toolUseResult.usage paths.
    Skips streaming stubs (stop_reason is None).
    """
    msg = entry.get("message", {})
    if msg.get("type") == "assistant" and msg.get("stop_reason") is not None:
        usage = msg.get("usage")
        if usage:
            model = msg.get("model")
            request_id = entry.get("requestId")
            entry_id = msg.get("id") or entry.get("uuid")
            return usage, model, request_id, entry_id
    # toolUseResult path
    if "toolUseResult" in entry:
        msg2 = entry.get("message", {})
        usage = msg2.get("usage")
        if usage:
            return usage, None, entry.get("requestId"), entry.get("uuid")
    return None, None, None, None
```

- [ ] **Step 3: Update context_overhead.py**

Replace `_extract_usage` with imports. The caller uses `(usage, request_id)`:

```python
from obs_utils import extract_usage_full

# In _read_transcript_tail, replace:
#   usage, request_id = _extract_usage(entry)
# With:
usage, _model, request_id, _entry_id = extract_usage_full(entry)
```

Delete the local `_extract_usage` function (lines 255-285).

- [ ] **Step 4: Update obs-stop-cache.py**

Replace `_extract_usage_from_entry` with imports. The caller uses `(usage, model, entry_id)`:

```python
from obs_utils import extract_usage_full

# Replace:
#   usage, model, entry_id = _extract_usage_from_entry(entry)
# With:
usage, model, _request_id, entry_id = extract_usage_full(entry)
```

Delete the local `_extract_usage_from_entry` function (lines 96-120).

- [ ] **Step 5: Run tests, commit**

Run: `NO_COLOR=1 QLINE_NO_COLLECT=1 bash tests/test-statusline.sh 2>&1 | tail -3`
Expected: 192/235

```bash
git add hooks/obs_utils.py src/context_overhead.py hooks/obs-stop-cache.py
git commit -m "refactor: unify _extract_usage into obs_utils.extract_usage_full (H4)"
```

---

### Task 9: Wire `_write_ledger_record` through `_atomic_jsonl_append` (H5)

**Files:**
- Modify: `hooks/hook_utils.py:47-60` — replace body with obs_utils call

- [ ] **Step 1: Assess import direction**

`hook_utils.py` currently does NOT import from `obs_utils.py`. Adding this import creates a new dependency. Read both files to verify no circular dependency risk.

If safe: add `from obs_utils import _atomic_jsonl_append` to hook_utils.

If circular: skip this task (the duplication is only ~10 lines and the isolation may be intentional).

- [ ] **Step 2: If safe, update `_write_ledger_record`**

```python
def _write_ledger_record(record):
    """Append record to fault ledger via atomic JSONL append."""
    from obs_utils import _atomic_jsonl_append
    _atomic_jsonl_append(_LEDGER_PATH, record)
```

Note: using local import to keep the dependency lazy. If obs_utils is unavailable (e.g., during early bootstrap), the existing try/except in callers will catch ImportError.

- [ ] **Step 3: Run tests, commit**

Run: `NO_COLOR=1 QLINE_NO_COLLECT=1 bash tests/test-statusline.sh 2>&1 | tail -3`
Expected: 192/235

```bash
git add hooks/hook_utils.py
git commit -m "refactor: wire _write_ledger_record through _atomic_jsonl_append (H5)"
```

---

## Verification

After all tasks:

- [ ] **Final test run:** `NO_COLOR=1 QLINE_NO_COLLECT=1 bash tests/test-statusline.sh 2>&1 | tail -3` — must show 192/235
- [ ] **Line count delta:** `git diff --stat 01f3b14..HEAD` — expect net reduction of ~100-150 lines
- [ ] **No new files created** — all changes are consolidation into existing files
- [ ] **Each commit independently revertible** — `git log --oneline` shows 9 atomic commits
