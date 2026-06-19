# PreCompact Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace three independent qLine/bricklab PreCompact hooks with one fail-open orchestrator that merges deterministic producers + an agent-authored handoff note into a single, bounded, observable capsule, rolled out behind an env flag with zero regression to the one working hook.

**Architecture:** One registered hook (`precompact-orchestrator.py`) invokes five producers **as subprocesses** (hard fail-isolation, no cross-repo import coupling), each under a ≤3s `Deadline`, and merges their JSON sections into one capsule with an observability envelope (`_producers_ok/_producers_failed/_empty/_ms`). The capsule is injected once via `systemMessage` and written to a `session_id`-keyed file. A SessionStart sentinel validates the envelope and emits a deterministic producer-rot diagnostic; a thin out-of-hook forwarder relays rot to BOT PATCHES. Gated by `PRECOMPACT_ORCHESTRATOR_ENABLED=1`, run in parallel with the legacy hook until ≥5 clean audits.

**Tech Stack:** Python 3.12, pytest 9.0.2, stdlib only (`subprocess`, `json`, `select`, `glob`). Reuses `hooks/hook_utils.py` (`is_strict`, `Deadline`, `subprocess_resource_limits`, `iter_open_tasks`, `find_latest_plan`, `read_hook_input`, `run_fail_open`, `log_hook_diagnostic`, `validate_session_id`).

**Spec:** `docs/superpowers/specs/2026-06-19-precompact-orchestrator-design.md` (commit `5df740b`). **Host:** Linux `/home/q` — NOT the rider's macOS `/Users/q` paths.

**Reuse-first rider principles enforced throughout (spec Appendix D):**
- Single versioned receipt/event schema → `CAPSULE_SCHEMA_VERSION` + one envelope shape.
- Shared classifiers/readers, not per-producer logic → one bounded ledger reader, one git-root resolver.
- Shadow → warn → enforce + rollback → env-flag gate, parallel legacy run, unset-to-rollback.
- No raw secrets / no raw transcript persistence → handoff note is agent-authored, local-only; producers emit counts/names, never message bodies or `tool_use.input`.
- Measurable → golden parity, producer-failure, bounded-read, empty-session tests; rot diagnostic is actionable.

**Conventions (verified in repo):**
- Tests live in `hooks/tests/`, each starts with `sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))` then imports modules by bare name.
- Run tests: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/<file> -v`.
- Hooks are executable (`chmod +x`), shebang `#!/usr/bin/env python3`, invoked via `hooks/run-hook` wrapper which resolves Python ≥3.10.
- Branch: `spec/precompact-orchestrator` (already checked out). Commit style: conventional commits; qLine uses the `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer.

---

## File Structure

**New (qLine `hooks/`):**
| File | Responsibility |
|---|---|
| `precompact_capsule.py` | Capsule schema constants, section keys, `merge_capsule()`, `build_envelope()`. The single source of the receipt schema. |
| `precompact_ledger.py` | One bounded tail-reader for the action-ledger JSONL: `read_session_actions(session_id, deadline)`. Reused by `stats`, `failures`, `git` producers. |
| `precompact_handoff.py` | Agent-authored note storage: `write_note()`, `read_note()`, plus a `__main__` CLI so the agent can record a note frictionlessly. |
| `precompact_producers.py` | Five producer functions + a `__main__` CLI dispatcher (`<name> --json-out`) so the orchestrator can invoke each as a subprocess. |
| `precompact-orchestrator.py` | Registered PreCompact hook: env-gate, subprocess fan-out with per-producer deadline, merge, inject once, persist capsule. |
| `precompact-sentinel.py` | Registered SessionStart hook: load session capsule, validate envelope, emit producer-rot diagnostic. |
| `precompact_botpatches_forward.py` | Out-of-hook adapter: tails the rot-diagnostic ledger, relays new rot events to BOT PATCHES via `create_agent_job`. Run by cron/operator, NOT in the hook. |

**New tests (`hooks/tests/`):** `test_precompact_capsule.py`, `test_precompact_ledger.py`, `test_precompact_handoff.py`, `test_precompact_producers.py`, `test_precompact_orchestrator.py`, `test_precompact_sentinel.py`.

**Modified:** global `~/.claude/settings.json` `PreCompact` + `SessionStart` arrays (Task 8). No edit to `precompact-preserve.py` (kept running in parallel; deregistered only after audits).

---

## Task 1: Capsule schema + envelope (`precompact_capsule.py`)

**Files:**
- Create: `hooks/precompact_capsule.py`
- Test: `hooks/tests/test_precompact_capsule.py`

- [ ] **Step 1: Write the failing test**

```python
# hooks/tests/test_precompact_capsule.py
"""Tests for the PreCompact capsule schema + merge/envelope."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestMergeCapsule:
    def test_merges_sections_and_records_ok(self):
        from precompact_capsule import merge_capsule, CAPSULE_SCHEMA_VERSION
        results = {
            "preserve": {"open_tasks": "Open tasks (1):\n  [pending] #1: x"},
            "git": {"git_state": [{"repo": "qLine", "dirty": 2, "unpushed": 0}]},
        }
        cap = merge_capsule(results, failed=["stats"], elapsed_ms=120)
        assert cap["schema_version"] == CAPSULE_SCHEMA_VERSION
        assert cap["open_tasks"].startswith("Open tasks")
        assert cap["git_state"][0]["repo"] == "qLine"
        assert sorted(cap["_producers_ok"]) == ["git", "preserve"]
        assert cap["_producers_failed"] == ["stats"]
        assert cap["_empty"] is False
        assert cap["_ms"] == 120

    def test_empty_when_all_sections_blank(self):
        from precompact_capsule import merge_capsule
        cap = merge_capsule({"preserve": None, "stats": {}}, failed=[], elapsed_ms=5)
        assert cap["_empty"] is True
        assert cap["_producers_ok"] == []  # producers that returned nothing are not "ok"

    def test_producer_returning_none_is_not_ok_not_failed(self):
        from precompact_capsule import merge_capsule
        cap = merge_capsule({"handoff": None}, failed=[], elapsed_ms=1)
        assert "handoff" not in cap["_producers_ok"]
        assert cap["_producers_failed"] == []

    def test_render_systemmessage_includes_present_sections_only(self):
        from precompact_capsule import render_systemmessage
        cap = {
            "schema_version": 1,
            "open_tasks": "Open tasks (1):\n  [pending] #1: x",
            "git_state": [{"repo": "qLine", "dirty": 1, "unpushed": 0}],
            "handoff_note": "Refactoring the parser; next: wire tests.",
            "_producers_ok": ["preserve", "git", "handoff"],
            "_producers_failed": [], "_empty": False, "_ms": 9,
        }
        msg = render_systemmessage(cap)
        assert "[PreCompact capsule]" in msg
        assert "Open tasks" in msg
        assert "qLine" in msg
        assert "Refactoring the parser" in msg

    def test_render_returns_none_when_empty(self):
        from precompact_capsule import render_systemmessage
        assert render_systemmessage({"_empty": True}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_precompact_capsule.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'precompact_capsule'`

- [ ] **Step 3: Write minimal implementation**

```python
# hooks/precompact_capsule.py
"""PreCompact capsule schema — the single versioned receipt for the orchestrator.

One schema, many producers. Each producer contributes named sections; the
orchestrator records which producers succeeded, failed, or returned nothing.
"""
from __future__ import annotations

CAPSULE_SCHEMA_VERSION = 1

# Section keys each producer may contribute. Order = render order.
SECTION_KEYS = (
    "open_tasks",       # preserve
    "active_plan",      # preserve
    "git_state",        # git
    "unresolved_failures",  # failures
    "session_stats",    # stats
    "handoff_note",     # handoff
)

_ENVELOPE_KEYS = {"_producers_ok", "_producers_failed", "_empty", "_ms", "schema_version"}


def _section_has_content(value) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, dict)) and len(value) == 0:
        return False
    return True


def merge_capsule(results: dict, failed: list, elapsed_ms: int) -> dict:
    """Merge per-producer section dicts into one capsule with an envelope.

    results: {producer_name: section_dict_or_None}
    failed:  producer names that errored/timed-out/returned-malformed.
    A producer is "ok" only if it returned at least one non-empty section.
    """
    capsule: dict = {"schema_version": CAPSULE_SCHEMA_VERSION}
    ok: list = []
    for name, section in results.items():
        if name in failed:
            continue
        if not section:
            continue
        contributed = False
        for key, value in section.items():
            if key not in SECTION_KEYS:
                continue
            if _section_has_content(value):
                capsule[key] = value
                contributed = True
        if contributed:
            ok.append(name)

    has_content = any(k in capsule for k in SECTION_KEYS)
    capsule["_producers_ok"] = ok
    capsule["_producers_failed"] = list(failed)
    capsule["_empty"] = not has_content
    capsule["_ms"] = int(elapsed_ms)
    return capsule


def build_envelope(capsule: dict) -> dict:
    """Extract just the envelope fields (for the sentinel)."""
    return {k: capsule.get(k) for k in _ENVELOPE_KEYS}


def render_systemmessage(capsule: dict) -> str | None:
    """Render the capsule to a single injected systemMessage. None if empty."""
    if capsule.get("_empty"):
        return None
    lines = ["[PreCompact capsule]"]
    if capsule.get("open_tasks"):
        lines.append(capsule["open_tasks"])
    if capsule.get("active_plan"):
        lines.append(f"Active plan: {capsule['active_plan']}")
    if capsule.get("git_state"):
        gl = ", ".join(
            f"{g['repo']}(+{g.get('dirty', 0)}d/{g.get('unpushed', 0)}u)"
            for g in capsule["git_state"]
        )
        lines.append(f"Git: {gl}")
    if capsule.get("unresolved_failures"):
        lines.append("Unresolved command failures:")
        for f in capsule["unresolved_failures"][:10]:
            lines.append(f"  - {f}")
    if capsule.get("session_stats"):
        lines.append(f"Session stats: {capsule['session_stats']}")
    if capsule.get("handoff_note"):
        lines.append("Handoff note (agent-authored):")
        lines.append(capsule["handoff_note"])
    if len(lines) == 1:
        return None
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_precompact_capsule.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
cd /home/q/LAB/qLine
git add hooks/precompact_capsule.py hooks/tests/test_precompact_capsule.py
git commit -m "feat(precompact): capsule schema + merge/envelope/render

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Bounded ledger reader (`precompact_ledger.py`)

The latency CRIT: never `read_text().splitlines()` on the ≈45 MB ledger. Read a bounded tail from EOF and filter by `session_id`.

**Files:**
- Create: `hooks/precompact_ledger.py`
- Test: `hooks/tests/test_precompact_ledger.py`

- [ ] **Step 1: Write the failing test**

```python
# hooks/tests/test_precompact_ledger.py
"""Tests for the bounded action-ledger tail reader."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _write_ledger(path, records):
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


class TestReadSessionActions:
    def test_returns_only_matching_session(self, tmp_path):
        from precompact_ledger import read_session_actions
        p = tmp_path / "ledger.jsonl"
        _write_ledger(p, [
            {"session_id": "A", "tool": "Bash", "command": "ls", "ts": "1"},
            {"session_id": "B", "tool": "Read", "file_path": "x", "ts": "2"},
            {"session_id": "A", "tool": "Edit", "file_path": "y", "ts": "3"},
        ])
        actions = read_session_actions("A", ledger_path=str(p))
        assert len(actions) == 2
        assert {a["tool"] for a in actions} == {"Bash", "Edit"}

    def test_bounded_scan_skips_old_records_beyond_byte_budget(self, tmp_path):
        from precompact_ledger import read_session_actions
        p = tmp_path / "ledger.jsonl"
        old = [{"session_id": "OLD", "tool": "Bash", "command": "x" * 200, "ts": str(i)}
               for i in range(20000)]
        recent = [{"session_id": "NEW", "tool": "Edit", "file_path": "z", "ts": "late"}]
        _write_ledger(p, old + recent)
        actions = read_session_actions("NEW", ledger_path=str(p), max_bytes=64 * 1024)
        assert len(actions) == 1  # found in the tail
        assert actions[0]["tool"] == "Edit"

    def test_large_file_completes_under_deadline(self, tmp_path):
        from precompact_ledger import read_session_actions
        from hook_utils import Deadline
        p = tmp_path / "ledger.jsonl"
        big = [{"session_id": "S", "tool": "Bash", "command": "y" * 300, "ts": str(i)}
               for i in range(100000)]
        _write_ledger(p, big)  # ~30 MB
        t0 = time.monotonic()
        actions = read_session_actions("S", ledger_path=str(p),
                                       max_bytes=2 * 1024 * 1024, deadline=Deadline(3.0))
        assert (time.monotonic() - t0) < 3.0
        assert len(actions) > 0  # got the tail of session S

    def test_missing_file_returns_empty(self, tmp_path):
        from precompact_ledger import read_session_actions
        assert read_session_actions("A", ledger_path=str(tmp_path / "nope.jsonl")) == []

    def test_skips_malformed_lines(self, tmp_path):
        from precompact_ledger import read_session_actions
        p = tmp_path / "ledger.jsonl"
        with open(p, "w") as f:
            f.write('{"session_id": "A", "tool": "Bash"}\n')
            f.write("not json at all\n")
            f.write('{"session_id": "A", "tool": "Edit"}\n')
        actions = read_session_actions("A", ledger_path=str(p))
        assert len(actions) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_precompact_ledger.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'precompact_ledger'`

- [ ] **Step 3: Write minimal implementation**

```python
# hooks/precompact_ledger.py
"""Bounded tail reader for the brick-lab action-ledger JSONL.

The ledger is append-only and can be tens of MB. A session's records cluster at
the end, so we read a bounded tail from EOF rather than the whole file. This is
the single shared reader for all producers (reuse-first; one place owns the
latency contract).
"""
from __future__ import annotations

import json
import os

DEFAULT_LEDGER_PATH = os.path.join(
    os.path.expanduser("~"), ".local", "share", "brick-lab", "action-ledger.jsonl"
)
DEFAULT_MAX_BYTES = 2 * 1024 * 1024  # 2 MB tail window


def _read_tail_lines(path: str, max_bytes: int) -> list[str]:
    """Return decoded lines from the last <=max_bytes of the file.

    Drops a possibly-partial first line (we seeked into the middle of a record).
    """
    size = os.path.getsize(path)
    start = max(0, size - max_bytes)
    with open(path, "rb") as f:
        f.seek(start)
        chunk = f.read()
    text = chunk.decode("utf-8", errors="replace")
    lines = text.split("\n")
    if start > 0 and lines:
        lines = lines[1:]  # discard partial leading record
    return lines


def read_session_actions(
    session_id: str,
    *,
    ledger_path: str = DEFAULT_LEDGER_PATH,
    max_bytes: int = DEFAULT_MAX_BYTES,
    deadline=None,
) -> list[dict]:
    """Return action records for session_id found within the bounded tail window.

    Never raises; returns [] on any error. Honors a hook_utils.Deadline if given.
    """
    try:
        if not os.path.exists(ledger_path):
            return []
        lines = _read_tail_lines(ledger_path, max_bytes)
    except OSError:
        return []

    out: list[dict] = []
    for line in lines:
        if deadline is not None and deadline.remaining() == 0:
            break
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(entry, dict) and entry.get("session_id") == session_id:
            out.append(entry)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_precompact_ledger.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
cd /home/q/LAB/qLine
git add hooks/precompact_ledger.py hooks/tests/test_precompact_ledger.py
git commit -m "feat(precompact): bounded tail reader for action-ledger (latency CRIT fix)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Agent-authored handoff note storage (`precompact_handoff.py`)

Resolves the spec's open question: storage = one overwrite file per session at `~/.claude/precompact-handoff/<session_id>.md`, written via a tiny CLI the agent calls. Absent file → no section (never fabricated).

**Files:**
- Create: `hooks/precompact_handoff.py`
- Test: `hooks/tests/test_precompact_handoff.py`

- [ ] **Step 1: Write the failing test**

```python
# hooks/tests/test_precompact_handoff.py
"""Tests for agent-authored handoff note storage."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestHandoffNote:
    def test_write_then_read_roundtrip(self, tmp_path):
        from precompact_handoff import write_note, read_note
        root = str(tmp_path)
        write_note("sess-1", "Refactoring parser; next: wire tests.", base_dir=root)
        assert read_note("sess-1", base_dir=root) == "Refactoring parser; next: wire tests."

    def test_read_absent_returns_none(self, tmp_path):
        from precompact_handoff import read_note
        assert read_note("missing", base_dir=str(tmp_path)) is None

    def test_write_overwrites(self, tmp_path):
        from precompact_handoff import write_note, read_note
        root = str(tmp_path)
        write_note("s", "first", base_dir=root)
        write_note("s", "second", base_dir=root)
        assert read_note("s", base_dir=root) == "second"

    def test_blank_note_is_rejected(self, tmp_path):
        from precompact_handoff import write_note, read_note
        root = str(tmp_path)
        write_note("s", "   ", base_dir=root)
        assert read_note("s", base_dir=root) is None

    def test_note_is_length_capped(self, tmp_path):
        from precompact_handoff import write_note, read_note, MAX_NOTE_CHARS
        root = str(tmp_path)
        write_note("s", "x" * (MAX_NOTE_CHARS + 500), base_dir=root)
        assert len(read_note("s", base_dir=root)) == MAX_NOTE_CHARS

    def test_session_id_is_sanitized_for_path(self, tmp_path):
        from precompact_handoff import write_note, read_note
        root = str(tmp_path)
        write_note("../evil", "data", base_dir=root)
        # Must stay inside base_dir — no traversal.
        for dirpath, _, files in os.walk(root):
            for fn in files:
                assert os.path.realpath(os.path.join(dirpath, fn)).startswith(
                    os.path.realpath(root))
        assert read_note("../evil", base_dir=root) == "data"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_precompact_handoff.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'precompact_handoff'`

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
# hooks/precompact_handoff.py
"""Agent-authored handoff note: trusted, local-only, zero-leak.

The live agent records intent/blockers/next-action in its own words during the
session. At PreCompact the handoff producer reads the latest note. No note ->
no section (never fabricated). Content never leaves the machine, so no
sanitization and no 'unverified' label.

CLI (for the agent to record a note):
    python3 precompact_handoff.py write <session_id> "next: wire the tests"
    echo "long note" | python3 precompact_handoff.py write <session_id> -
"""
from __future__ import annotations

import os
import sys

MAX_NOTE_CHARS = 4000
DEFAULT_BASE_DIR = os.path.join(
    os.path.expanduser("~"), ".claude", "precompact-handoff"
)


def _safe_name(session_id: str) -> str:
    """Sanitize session_id to a single path-safe filename (no traversal)."""
    cleaned = "".join(
        c if ((c.isascii() and c.isalnum()) or c in {"_", "-"}) else "-"
        for c in str(session_id)
    )
    return (cleaned or "unknown")[:128]


def _note_path(session_id: str, base_dir: str) -> str:
    return os.path.join(base_dir, _safe_name(session_id) + ".md")


def write_note(session_id: str, text: str, *, base_dir: str = DEFAULT_BASE_DIR) -> None:
    """Overwrite the session's handoff note. Blank text clears it. Never raises."""
    try:
        text = (text or "").strip()[:MAX_NOTE_CHARS]
        os.makedirs(base_dir, exist_ok=True)
        path = _note_path(session_id, base_dir)
        if not text:
            if os.path.exists(path):
                os.remove(path)
            return
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(text)
        os.replace(tmp, path)  # atomic
    except OSError:
        pass


def read_note(session_id: str, *, base_dir: str = DEFAULT_BASE_DIR) -> str | None:
    """Return the session's handoff note, or None if absent/blank. Never raises."""
    try:
        path = _note_path(session_id, base_dir)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            text = f.read().strip()[:MAX_NOTE_CHARS]
        return text or None
    except OSError:
        return None


def _main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[0] == "write":
        session_id = argv[1]
        if argv[2] == "-":
            text = sys.stdin.read()
        else:
            text = " ".join(argv[2:])
        write_note(session_id, text)
        return 0
    sys.stderr.write("usage: precompact_handoff.py write <session_id> <text|->\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
```

- [ ] **Step 4: Run test to verify it passes, then mark executable**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_precompact_handoff.py -v && chmod +x hooks/precompact_handoff.py`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
cd /home/q/LAB/qLine
git add hooks/precompact_handoff.py hooks/tests/test_precompact_handoff.py
git commit -m "feat(precompact): agent-authored handoff note storage + CLI

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Producers module + CLI (`precompact_producers.py`)

Five producers as functions, plus a `__main__` dispatcher so the orchestrator can run each as `python3 precompact_producers.py <name> --json-out` with the hook input JSON on stdin. Each function returns a section dict or `None`. Producers emit counts/names/state — never message bodies or `tool_use.input` (no-leak principle).

**Files:**
- Create: `hooks/precompact_producers.py`
- Test: `hooks/tests/test_precompact_producers.py`

- [ ] **Step 1: Write the failing test**

```python
# hooks/tests/test_precompact_producers.py
"""Tests for the five PreCompact producers."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

HOOKS_DIR = os.path.join(os.path.dirname(__file__), "..")


class TestPreserveProducer:
    def test_formats_open_tasks_matching_legacy_format(self, monkeypatch):
        import precompact_producers as P
        monkeypatch.setattr(P, "iter_open_tasks",
                            lambda sid: [({"id": "10", "subject": "do x", "status": "pending"}, "f")])
        monkeypatch.setattr(P, "find_latest_plan", lambda: "2026-06-19-thing.md")
        section = P.produce_preserve({"session_id": "s"})
        assert section["open_tasks"].startswith("Open tasks (1):")
        assert "[pending] #10: do x" in section["open_tasks"]
        assert section["active_plan"] == "2026-06-19-thing.md"

    def test_returns_none_when_nothing(self, monkeypatch):
        import precompact_producers as P
        monkeypatch.setattr(P, "iter_open_tasks", lambda sid: [])
        monkeypatch.setattr(P, "find_latest_plan", lambda: None)
        assert P.produce_preserve({"session_id": "s"}) is None


class TestFailuresProducer:
    def test_unresolved_failures_excludes_later_success(self, monkeypatch):
        import precompact_producers as P
        actions = [
            {"tool": "Bash", "command": "pytest", "exit_code": 1, "ts": "1"},
            {"tool": "Bash", "command": "pytest", "exit_code": 0, "ts": "2"},
            {"tool": "Bash", "command": "ruff check", "exit_code": 2, "ts": "3"},
        ]
        monkeypatch.setattr(P, "read_session_actions", lambda sid, **k: actions)
        section = P.produce_failures({"session_id": "s"})
        # 'pytest' later succeeded -> excluded; 'ruff check' has no later success -> kept
        assert any("ruff check" in f for f in section["unresolved_failures"])
        assert not any("pytest" in f for f in section["unresolved_failures"])

    def test_none_when_no_failures(self, monkeypatch):
        import precompact_producers as P
        monkeypatch.setattr(P, "read_session_actions",
                            lambda sid, **k: [{"tool": "Bash", "command": "ls", "exit_code": 0}])
        assert P.produce_failures({"session_id": "s"}) is None


class TestStatsProducer:
    def test_counts_tools(self, monkeypatch):
        import precompact_producers as P
        actions = [{"tool": "Bash"}, {"tool": "Bash"}, {"tool": "Read"}]
        monkeypatch.setattr(P, "read_session_actions", lambda sid, **k: actions)
        section = P.produce_stats({"session_id": "s"})
        assert section["session_stats"]["Bash"] == 2
        assert section["session_stats"]["Read"] == 1


class TestHandoffProducer:
    def test_reads_note(self, monkeypatch):
        import precompact_producers as P
        monkeypatch.setattr(P, "read_note", lambda sid: "next: wire tests")
        assert P.produce_handoff({"session_id": "s"})["handoff_note"] == "next: wire tests"

    def test_none_when_no_note(self, monkeypatch):
        import precompact_producers as P
        monkeypatch.setattr(P, "read_note", lambda sid: None)
        assert P.produce_handoff({"session_id": "s"}) is None


class TestCLIDispatcher:
    def test_cli_emits_json_section_on_stdout(self):
        # stats over an empty session -> None -> CLI prints "null"
        payload = json.dumps({"session_id": "no-such-session-xyz"})
        proc = subprocess.run(
            [sys.executable, os.path.join(HOOKS_DIR, "precompact_producers.py"),
             "stats", "--json-out"],
            input=payload, capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode == 0
        # Valid JSON (either null or an object)
        json.loads(proc.stdout.strip() or "null")

    def test_cli_unknown_producer_exits_nonzero(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(HOOKS_DIR, "precompact_producers.py"),
             "bogus", "--json-out"],
            input="{}", capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode != 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_precompact_producers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'precompact_producers'`

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
# hooks/precompact_producers.py
"""PreCompact producers. Each returns a section dict or None.

Invoked by the orchestrator as a subprocess:
    python3 precompact_producers.py <name> --json-out   (hook JSON on stdin)

Producers emit counts / names / state only — never message bodies or
tool_use.input (no-leak principle). They never raise to the CLI: a failing
producer returns None and exits 0; the orchestrator records failure via timeout
or malformed output, and the dispatcher exits non-zero only for an unknown name.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hook_utils import iter_open_tasks, find_latest_plan  # noqa: E402
from precompact_ledger import read_session_actions  # noqa: E402
from precompact_handoff import read_note  # noqa: E402

_MAX_REPOS = 5
_MAX_FAILURES = 10


# --- preserve ---------------------------------------------------------------

def _format_open_tasks(session_id: str) -> str | None:
    lines = []
    for task, fname in iter_open_tasks(session_id):
        tid = task.get("id", fname)
        subject = task.get("subject", "(no subject)")
        status = task.get("status", "?")
        blocked_by = task.get("blockedBy", [])
        entry = f"  [{status}] #{tid}: {subject}"
        if blocked_by:
            entry += f" (blocked by: {', '.join(str(b) for b in blocked_by)})"
        lines.append(entry)
    if not lines:
        return None
    return f"Open tasks ({len(lines)}):\n" + "\n".join(lines[:20])


def produce_preserve(inp: dict) -> dict | None:
    session_id = str(inp.get("session_id") or "")
    section: dict = {}
    tasks = _format_open_tasks(session_id)
    if tasks:
        section["open_tasks"] = tasks
    plan = find_latest_plan()
    if plan:
        section["active_plan"] = plan
    return section or None


# --- git --------------------------------------------------------------------

def _git_roots_from_actions(actions: list[dict]) -> list[str]:
    """Distinct git toplevels derived from this session's action cwds (no fixed list)."""
    roots: list[str] = []
    seen = set()
    for a in actions:
        cwd = a.get("cwd")
        if not cwd or cwd in seen:
            continue
        seen.add(cwd)
        try:
            top = subprocess.run(
                ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=1,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
        if top and top not in roots:
            roots.append(top)
        if len(roots) >= _MAX_REPOS:
            break
    return roots


def _git_state_for(root: str) -> dict | None:
    try:
        branch = subprocess.run(
            ["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=1).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", root, "status", "--porcelain"],
            capture_output=True, text=True, timeout=1).stdout.splitlines()
        unpushed = subprocess.run(
            ["git", "-C", root, "rev-list", "--count", "@{u}..HEAD"],
            capture_output=True, text=True, timeout=1).stdout.strip() or "0"
    except (OSError, subprocess.SubprocessError):
        return None
    return {
        "repo": os.path.basename(root),
        "branch": branch,
        "dirty": len(dirty),
        "unpushed": int(unpushed) if unpushed.isdigit() else 0,
    }


def produce_git(inp: dict) -> dict | None:
    session_id = str(inp.get("session_id") or "")
    actions = read_session_actions(session_id)
    states = []
    for root in _git_roots_from_actions(actions):
        st = _git_state_for(root)
        if st:
            states.append(st)
    return {"git_state": states} if states else None


# --- failures ---------------------------------------------------------------

def produce_failures(inp: dict) -> dict | None:
    session_id = str(inp.get("session_id") or "")
    actions = read_session_actions(session_id)
    last_success: dict[str, str] = {}
    failures: dict[str, str] = {}
    for a in actions:
        if a.get("tool") != "Bash":
            continue
        cmd = a.get("command")
        if not cmd:
            continue
        ts = str(a.get("ts") or "")
        code = a.get("exit_code")
        if code in (0, None):
            last_success[cmd] = ts
        else:
            failures[cmd] = ts
    unresolved = [
        cmd for cmd, fts in failures.items()
        if last_success.get(cmd, "") <= fts
    ]
    if not unresolved:
        return None
    return {"unresolved_failures": unresolved[:_MAX_FAILURES]}


# --- stats ------------------------------------------------------------------

def produce_stats(inp: dict) -> dict | None:
    session_id = str(inp.get("session_id") or "")
    actions = read_session_actions(session_id)
    counts: dict[str, int] = {}
    for a in actions:
        tool = a.get("tool")
        if tool:
            counts[tool] = counts.get(tool, 0) + 1
    return {"session_stats": counts} if counts else None


# --- handoff ----------------------------------------------------------------

def produce_handoff(inp: dict) -> dict | None:
    session_id = str(inp.get("session_id") or "")
    note = read_note(session_id)
    return {"handoff_note": note} if note else None


PRODUCERS = {
    "preserve": produce_preserve,
    "git": produce_git,
    "failures": produce_failures,
    "stats": produce_stats,
    "handoff": produce_handoff,
}


def _main(argv: list[str]) -> int:
    if len(argv) < 1 or argv[0] not in PRODUCERS:
        sys.stderr.write(f"unknown producer: {argv[:1]}\n")
        return 2
    name = argv[0]
    try:
        raw = sys.stdin.read()
        inp = json.loads(raw) if raw.strip() else {}
        if not isinstance(inp, dict):
            inp = {}
    except (json.JSONDecodeError, ValueError):
        inp = {}
    try:
        section = PRODUCERS[name](inp)
    except Exception:
        section = None  # producer failure -> null section, still exit 0
    sys.stdout.write(json.dumps(section))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
```

- [ ] **Step 4: Run test to verify it passes, then mark executable**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_precompact_producers.py -v && chmod +x hooks/precompact_producers.py`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
cd /home/q/LAB/qLine
git add hooks/precompact_producers.py hooks/tests/test_precompact_producers.py
git commit -m "feat(precompact): five producers (preserve/git/failures/stats/handoff) + CLI

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Orchestrator hook (`precompact-orchestrator.py`)

Env-gated. Fans the producers out as subprocesses, each with a hard per-producer deadline (≤3s) via `subprocess.run(timeout=...)` + `subprocess_resource_limits`. Merges via `merge_capsule`, persists the capsule to a session-keyed file, injects once. Wrapped in `run_fail_open`.

**Files:**
- Create: `hooks/precompact-orchestrator.py`
- Create (capsule store helper): add `capsule_path()` / `write_capsule()` / `read_capsule()` to `precompact_capsule.py`
- Test: `hooks/tests/test_precompact_orchestrator.py`

- [ ] **Step 1: Extend `precompact_capsule.py` with a session-keyed store (write test first)**

Add to `hooks/tests/test_precompact_capsule.py`:

```python
class TestCapsuleStore:
    def test_write_then_read_roundtrip(self, tmp_path):
        from precompact_capsule import write_capsule, read_capsule
        cap = {"schema_version": 1, "open_tasks": "x", "_empty": False,
               "_producers_ok": ["preserve"], "_producers_failed": [], "_ms": 3}
        write_capsule("sess-1", cap, base_dir=str(tmp_path))
        assert read_capsule("sess-1", base_dir=str(tmp_path))["open_tasks"] == "x"

    def test_read_absent_returns_none(self, tmp_path):
        from precompact_capsule import read_capsule
        assert read_capsule("nope", base_dir=str(tmp_path)) is None

    def test_session_id_path_is_sanitized(self, tmp_path):
        from precompact_capsule import write_capsule
        import os
        write_capsule("../evil", {"_empty": True}, base_dir=str(tmp_path))
        for dp, _, files in os.walk(str(tmp_path)):
            for fn in files:
                assert os.path.realpath(os.path.join(dp, fn)).startswith(
                    os.path.realpath(str(tmp_path)))
```

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_precompact_capsule.py::TestCapsuleStore -v`
Expected: FAIL — `ImportError: cannot import name 'write_capsule'`

- [ ] **Step 2: Add the store functions to `precompact_capsule.py`**

```python
# append to hooks/precompact_capsule.py
import json as _json
import os as _os

DEFAULT_CAPSULE_DIR = _os.path.join(
    _os.path.expanduser("~"), ".claude", "precompact-capsules"
)


def _safe_name(session_id: str) -> str:
    cleaned = "".join(
        c if ((c.isascii() and c.isalnum()) or c in {"_", "-"}) else "-"
        for c in str(session_id)
    )
    return (cleaned or "unknown")[:128]


def capsule_path(session_id: str, base_dir: str = DEFAULT_CAPSULE_DIR) -> str:
    return _os.path.join(base_dir, _safe_name(session_id) + ".json")


def write_capsule(session_id: str, capsule: dict, *, base_dir: str = DEFAULT_CAPSULE_DIR) -> None:
    try:
        _os.makedirs(base_dir, exist_ok=True)
        path = capsule_path(session_id, base_dir)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(_json.dumps(capsule))
        _os.replace(tmp, path)
    except OSError:
        pass


def read_capsule(session_id: str, *, base_dir: str = DEFAULT_CAPSULE_DIR) -> dict | None:
    try:
        path = capsule_path(session_id, base_dir)
        if not _os.path.exists(path):
            return None
        with open(path) as f:
            return _json.load(f)
    except (OSError, _json.JSONDecodeError):
        return None
```

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_precompact_capsule.py -v`
Expected: PASS (8 passed)

- [ ] **Step 3: Write the failing orchestrator test**

```python
# hooks/tests/test_precompact_orchestrator.py
"""Integration tests for the PreCompact orchestrator hook."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

HOOKS_DIR = os.path.join(os.path.dirname(__file__), "..")
ORCH = os.path.join(HOOKS_DIR, "precompact-orchestrator.py")


def _run(payload: dict, env_extra: dict, tmp_path):
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)            # isolate capsule/handoff/task dirs
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, ORCH],
        input=json.dumps(payload), capture_output=True, text=True,
        env=env, timeout=30,
    )


class TestEnvGate:
    def test_disabled_emits_nothing(self, tmp_path):
        proc = _run({"session_id": "s"}, {}, tmp_path)  # flag unset
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    def test_enabled_runs(self, tmp_path):
        proc = _run({"session_id": "s"}, {"PRECOMPACT_ORCHESTRATOR_ENABLED": "1"}, tmp_path)
        assert proc.returncode == 0


class TestGoldenParity:
    def test_reproduces_open_tasks_and_plan(self, tmp_path):
        # Seed a task + a plan under the isolated HOME so 'preserve' finds them.
        sid = "golden-sess"
        task_dir = tmp_path / ".claude" / "tasks" / sid
        task_dir.mkdir(parents=True)
        (task_dir / "t1.json").write_text(json.dumps(
            {"id": "10", "subject": "wire tests", "status": "pending"}))
        plan_dir = tmp_path / ".claude" / "plans"
        plan_dir.mkdir(parents=True)
        (plan_dir / "2026-06-19-precompact-orchestrator.md").write_text("# plan")

        proc = _run({"session_id": sid}, {"PRECOMPACT_ORCHESTRATOR_ENABLED": "1"}, tmp_path)
        out = json.loads(proc.stdout)
        msg = out["systemMessage"]
        assert "Open tasks (1):" in msg
        assert "[pending] #10: wire tests" in msg
        assert "Active plan: 2026-06-19-precompact-orchestrator.md" in msg
        # capsule persisted
        from precompact_capsule import read_capsule
        cap = read_capsule(sid, base_dir=str(tmp_path / ".claude" / "precompact-capsules"))
        assert cap["open_tasks"].startswith("Open tasks")
        assert "preserve" in cap["_producers_ok"]


class TestEmptySession:
    def test_empty_session_emits_no_systemmessage(self, tmp_path):
        proc = _run({"session_id": "empty-sess"},
                    {"PRECOMPACT_ORCHESTRATOR_ENABLED": "1"}, tmp_path)
        assert proc.returncode == 0
        # No content -> no systemMessage key (or empty stdout)
        if proc.stdout.strip():
            out = json.loads(proc.stdout)
            assert "systemMessage" not in out


class TestProducerFailure:
    def test_failing_producer_recorded_capsule_still_ships(self, tmp_path, monkeypatch):
        # Use the in-process orchestrator API to inject a failing producer.
        import importlib
        orch = importlib.import_module("precompact_orchestrator_lib")
        results, failed = orch.run_producers(
            {"session_id": "s"},
            producers=["preserve", "boom"],
            runner=lambda name, inp, deadline_s: (_ for _ in ()).throw(TimeoutError())
                if name == "boom" else None,
        )
        assert "boom" in failed
```

Note: the `TestProducerFailure` test imports `precompact_orchestrator_lib` — extract the testable core (producer fan-out + merge) into an importable module, leaving `precompact-orchestrator.py` (hyphenated, non-importable) as a thin entrypoint.

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_precompact_orchestrator.py -v`
Expected: FAIL — orchestrator + lib do not exist.

- [ ] **Step 4: Write the orchestrator core lib**

```python
# hooks/precompact_orchestrator_lib.py
"""Testable core for the PreCompact orchestrator: fan out producers as
subprocesses with a per-producer deadline, then merge into one capsule."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from precompact_capsule import merge_capsule

PRODUCER_ORDER = ["preserve", "git", "failures", "stats", "handoff"]
PER_PRODUCER_DEADLINE_S = 3.0
_PRODUCERS_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "precompact_producers.py")


def _subprocess_runner(name: str, inp: dict, deadline_s: float):
    """Run one producer as a subprocess; return its section dict or raise."""
    try:
        from hook_utils import subprocess_resource_limits
        preexec = subprocess_resource_limits
    except Exception:
        preexec = None
    proc = subprocess.run(
        [sys.executable, _PRODUCERS_SCRIPT, name, "--json-out"],
        input=json.dumps(inp), capture_output=True, text=True,
        timeout=deadline_s, preexec_fn=preexec,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"producer {name} rc={proc.returncode}")
    out = proc.stdout.strip()
    return json.loads(out) if out else None  # "null" -> None


def run_producers(inp: dict, *, producers=None, runner=None, deadline_s=PER_PRODUCER_DEADLINE_S):
    """Run each producer; return (results, failed)."""
    producers = producers or PRODUCER_ORDER
    runner = runner or _subprocess_runner
    results: dict = {}
    failed: list = []
    for name in producers:
        try:
            results[name] = runner(name, inp, deadline_s)
        except Exception:
            failed.append(name)
            results[name] = None
    return results, failed


def build_capsule(inp: dict, elapsed_ms: int, **kw) -> dict:
    results, failed = run_producers(inp, **kw)
    return merge_capsule(results, failed, elapsed_ms)
```

- [ ] **Step 5: Write the thin hook entrypoint**

```python
#!/usr/bin/env python3
# hooks/precompact-orchestrator.py
"""Registered PreCompact hook (Shape A orchestrator).

Gated behind PRECOMPACT_ORCHESTRATOR_ENABLED=1. Runs five producers as
subprocesses under per-producer deadlines, merges into one capsule, persists it
session-keyed, and injects once. Single fail-open boundary.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hook_utils import read_hook_input, run_fail_open, is_strict  # noqa: E402
from precompact_capsule import render_systemmessage, write_capsule  # noqa: E402
from precompact_orchestrator_lib import build_capsule  # noqa: E402


def main():
    if not is_strict("PRECOMPACT_ORCHESTRATOR_ENABLED"):
        sys.exit(0)  # disabled -> no-op (rollback path)

    inp = read_hook_input(timeout_seconds=2)
    if not inp:
        sys.exit(0)
    session_id = str(inp.get("session_id") or "")

    t0 = time.monotonic()
    capsule = build_capsule(inp, elapsed_ms=0)
    capsule["_ms"] = int((time.monotonic() - t0) * 1000)

    if session_id:
        write_capsule(session_id, capsule)

    msg = render_systemmessage(capsule)
    if msg:
        print(json.dumps({"systemMessage": msg}))
    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, "precompact-orchestrator", "PreCompact")
```

- [ ] **Step 6: Run tests + mark executable**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_precompact_orchestrator.py -v && chmod +x hooks/precompact-orchestrator.py`
Expected: PASS (all)

- [ ] **Step 7: Commit**

```bash
cd /home/q/LAB/qLine
git add hooks/precompact-orchestrator.py hooks/precompact_orchestrator_lib.py \
        hooks/precompact_capsule.py hooks/tests/test_precompact_orchestrator.py \
        hooks/tests/test_precompact_capsule.py
git commit -m "feat(precompact): orchestrator hook + subprocess fan-out + capsule store

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: SessionStart sentinel (`precompact-sentinel.py`)

On SessionStart, load the session capsule, validate the envelope, and emit a deterministic producer-rot diagnostic via the existing `log_hook_diagnostic` (reuse — no new ledger format). Expected producers that are persistently absent → `reason_class="precompact_producer_rot"`. Empty capsule → `precompact_capsule_empty`.

**Files:**
- Create: `hooks/precompact-sentinel.py`
- Create: `hooks/precompact_sentinel_lib.py` (testable core)
- Test: `hooks/tests/test_precompact_sentinel.py`

- [ ] **Step 1: Write the failing test**

```python
# hooks/tests/test_precompact_sentinel.py
"""Tests for the SessionStart capsule sentinel."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestEvaluateCapsule:
    def test_flags_rot_when_expected_producer_missing(self):
        from precompact_sentinel_lib import evaluate_capsule, EXPECTED_PRODUCERS
        cap = {"_producers_ok": ["preserve"], "_producers_failed": ["git"],
               "_empty": False, "_ms": 10}
        alerts = evaluate_capsule(cap)
        classes = {a["reason_class"] for a in alerts}
        assert "precompact_producer_rot" in classes
        # the rot alert names the failed producer
        rot = next(a for a in alerts if a["reason_class"] == "precompact_producer_rot")
        assert "git" in rot["context"]["failed"]

    def test_flags_empty_capsule(self):
        from precompact_sentinel_lib import evaluate_capsule
        alerts = evaluate_capsule({"_producers_ok": [], "_producers_failed": [],
                                   "_empty": True, "_ms": 4})
        assert any(a["reason_class"] == "precompact_capsule_empty" for a in alerts)

    def test_clean_capsule_no_alerts(self):
        from precompact_sentinel_lib import evaluate_capsule, EXPECTED_PRODUCERS
        cap = {"_producers_ok": list(EXPECTED_PRODUCERS), "_producers_failed": [],
               "_empty": False, "_ms": 10}
        assert evaluate_capsule(cap) == []

    def test_no_capsule_is_silent(self):
        from precompact_sentinel_lib import evaluate_capsule
        assert evaluate_capsule(None) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_precompact_sentinel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'precompact_sentinel_lib'`

- [ ] **Step 3: Write the sentinel core lib**

```python
# hooks/precompact_sentinel_lib.py
"""Testable core for the SessionStart capsule sentinel.

EXPECTED_PRODUCERS lists producers that should normally appear. 'failures' and
'unresolved' sections are legitimately often empty, so only structural failures
(_producers_failed) and a fully-empty capsule are alertable — not a producer
that simply had nothing to contribute this session.
"""
from __future__ import annotations

# Producers whose *structural failure* (not merely empty output) signals rot.
EXPECTED_PRODUCERS = ("preserve", "git", "stats")


def evaluate_capsule(capsule) -> list[dict]:
    """Return a list of alert dicts (possibly empty). Pure; never raises."""
    if not capsule:
        return []
    alerts: list[dict] = []
    failed = list(capsule.get("_producers_failed") or [])
    if failed:
        alerts.append({
            "reason_class": "precompact_producer_rot",
            "message": f"PreCompact producers failed: {', '.join(failed)}",
            "context": {"failed": failed, "ok": capsule.get("_producers_ok", [])},
        })
    if capsule.get("_empty"):
        alerts.append({
            "reason_class": "precompact_capsule_empty",
            "message": "PreCompact capsule was empty (capture pipeline not capturing).",
            "context": {"ms": capsule.get("_ms")},
        })
    return alerts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_precompact_sentinel.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Write the thin SessionStart hook entrypoint**

```python
#!/usr/bin/env python3
# hooks/precompact-sentinel.py
"""SessionStart hook: validate the prior session's PreCompact capsule envelope
and emit a producer-rot diagnostic. Purely observational — no injection.

Gated behind PRECOMPACT_ORCHESTRATOR_ENABLED=1 (only meaningful while the
orchestrator is producing capsules).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hook_utils import read_hook_input, run_fail_open, is_strict, log_hook_diagnostic  # noqa: E402
from precompact_capsule import read_capsule  # noqa: E402
from precompact_sentinel_lib import evaluate_capsule  # noqa: E402


def main():
    if not is_strict("PRECOMPACT_ORCHESTRATOR_ENABLED"):
        sys.exit(0)
    inp = read_hook_input(timeout_seconds=2)
    if not inp:
        sys.exit(0)
    session_id = str(inp.get("session_id") or "")
    if not session_id:
        sys.exit(0)

    capsule = read_capsule(session_id)
    for alert in evaluate_capsule(capsule):
        log_hook_diagnostic(
            "precompact-sentinel", "SessionStart",
            alert["reason_class"], alert["message"],
            level="warn", context=alert["context"],
        )
    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, "precompact-sentinel", "SessionStart")
```

- [ ] **Step 6: Mark executable + commit**

```bash
cd /home/q/LAB/qLine
chmod +x hooks/precompact-sentinel.py
git add hooks/precompact-sentinel.py hooks/precompact_sentinel_lib.py \
        hooks/tests/test_precompact_sentinel.py
git commit -m "feat(precompact): SessionStart sentinel — envelope validation + rot diagnostic

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: BOT PATCHES forwarder (out-of-hook adapter)

The hook cannot call MCP tools in-process. The sentinel writes rot diagnostics to the existing fault ledger (`~/.claude/logs/lifecycle-hook-faults.jsonl`); this small adapter tails new `precompact_producer_rot` / `precompact_capsule_empty` records and relays them to BOT PATCHES via `create_agent_job`. Run by cron/operator, not the hook (keeps the hook deterministic + testable).

**Files:**
- Create: `hooks/precompact_botpatches_forward.py`
- Test: `hooks/tests/test_precompact_botpatches_forward.py`

- [ ] **Step 1: Write the failing test (pure selection logic — no live MCP call)**

```python
# hooks/tests/test_precompact_botpatches_forward.py
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestSelectNewRotRecords:
    def test_selects_only_precompact_rot_after_offset(self, tmp_path):
        from precompact_botpatches_forward import select_new_rot_records
        ledger = tmp_path / "faults.jsonl"
        rows = [
            {"reason_class": "other_thing", "level": "warn"},
            {"reason_class": "precompact_producer_rot", "message": "git failed",
             "context": {"failed": ["git"]}},
            {"reason_class": "precompact_capsule_empty", "message": "empty"},
        ]
        with open(ledger, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        new, new_offset = select_new_rot_records(str(ledger), offset=0)
        classes = {r["reason_class"] for r in new}
        assert classes == {"precompact_producer_rot", "precompact_capsule_empty"}
        assert new_offset == os.path.getsize(ledger)

    def test_offset_prevents_redelivery(self, tmp_path):
        from precompact_botpatches_forward import select_new_rot_records
        ledger = tmp_path / "faults.jsonl"
        with open(ledger, "w") as f:
            f.write(json.dumps({"reason_class": "precompact_producer_rot"}) + "\n")
        _, off = select_new_rot_records(str(ledger), offset=0)
        new2, off2 = select_new_rot_records(str(ledger), offset=off)
        assert new2 == []
        assert off2 == off
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_precompact_botpatches_forward.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write the forwarder**

```python
#!/usr/bin/env python3
# hooks/precompact_botpatches_forward.py
"""Relay PreCompact producer-rot diagnostics to BOT PATCHES.

Reads new rot records from the fault ledger past a persisted byte offset and
posts a summary via the WhatSoup create_agent_job mechanism (report_chat =
BOT PATCHES). Idempotent via the offset file. Run by cron/operator.

NOTE: the actual create_agent_job call is performed by the operator/agent layer
that has MCP access; this module isolates the *selection* logic (unit-tested)
from delivery. `main()` prints the payload to stdout for the caller to relay.
"""
from __future__ import annotations

import json
import os
import sys

FAULT_LEDGER = os.path.join(os.path.expanduser("~"), ".claude", "logs",
                            "lifecycle-hook-faults.jsonl")
OFFSET_FILE = os.path.join(os.path.expanduser("~"), ".claude", "logs",
                           "precompact-rot-forward.offset")
BOT_PATCHES_CHAT = "120363428426970843@g.us"
_ROT_CLASSES = {"precompact_producer_rot", "precompact_capsule_empty"}


def select_new_rot_records(ledger_path: str, offset: int) -> tuple[list[dict], int]:
    """Return (new_rot_records, new_offset) for records past `offset`."""
    if not os.path.exists(ledger_path):
        return [], offset
    size = os.path.getsize(ledger_path)
    if offset > size:  # ledger rotated/truncated
        offset = 0
    out: list[dict] = []
    with open(ledger_path) as f:
        f.seek(offset)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(rec, dict) and rec.get("reason_class") in _ROT_CLASSES:
                out.append(rec)
    return out, size


def _read_offset() -> int:
    try:
        with open(OFFSET_FILE) as f:
            return int(f.read().strip() or "0")
    except (OSError, ValueError):
        return 0


def _write_offset(offset: int) -> None:
    try:
        os.makedirs(os.path.dirname(OFFSET_FILE), exist_ok=True)
        with open(OFFSET_FILE, "w") as f:
            f.write(str(offset))
    except OSError:
        pass


def main() -> int:
    new, offset = select_new_rot_records(FAULT_LEDGER, _read_offset())
    if not new:
        return 0
    summary = "🧱 PreCompact producer rot detected:\n" + "\n".join(
        f"  - {r.get('reason_class')}: {r.get('message', '')}" for r in new[:20]
    )
    payload = {"report_chat": BOT_PATCHES_CHAT, "summary": summary, "count": len(new)}
    sys.stdout.write(json.dumps(payload))
    _write_offset(offset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_precompact_botpatches_forward.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
cd /home/q/LAB/qLine
git add hooks/precompact_botpatches_forward.py hooks/tests/test_precompact_botpatches_forward.py
git commit -m "feat(precompact): BOT PATCHES rot forwarder (selection logic + offset)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Register behind env flag (parallel rollout) + audit

No flag day. Register the two new hooks in global `~/.claude/settings.json` gated by `PRECOMPACT_ORCHESTRATOR_ENABLED=1`; keep the three legacy hooks registered in parallel. Run full test suite. Do NOT deregister legacy hooks in this task — that happens only after ≥5 clean audits including one non-qLine compaction.

**Files:**
- Modify: `~/.claude/settings.json` (global; `PreCompact` array ~lines 323–343, `SessionStart` array ~lines 7–40)

- [ ] **Step 1: Back up the global settings**

```bash
cp ~/.claude/settings.json ~/.claude/settings.json.bak-precompact-$(date +%s)
python3 -c "import json; json.load(open('$HOME/.claude/settings.json')); print('valid JSON')"
```

- [ ] **Step 2: Run the FULL new test suite green before touching settings**

```bash
cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_precompact_*.py -v
```
Expected: PASS (all precompact tests).

- [ ] **Step 3: Add the orchestrator to the global `PreCompact` array**

Add this object to the `hooks.PreCompact[0].hooks` array (alongside the three existing entries — do NOT remove them):

```json
{
  "type": "command",
  "command": "/home/q/LAB/qLine/hooks/run-hook /home/q/LAB/qLine/hooks/precompact-orchestrator.py",
  "timeout": 10
}
```

- [ ] **Step 4: Add the sentinel to the global `SessionStart` array**

Add to `hooks.SessionStart[0].hooks`:

```json
{
  "type": "command",
  "command": "/home/q/LAB/qLine/hooks/run-hook /home/q/LAB/qLine/hooks/precompact-sentinel.py",
  "timeout": 8
}
```

- [ ] **Step 5: Validate settings JSON + confirm flag is unset (still shadow)**

```bash
python3 -c "import json; d=json.load(open('$HOME/.claude/settings.json')); print('valid JSON');
import sys
pc=[h['command'] for h in d['hooks']['PreCompact'][0]['hooks']]
ss=[h['command'] for h in d['hooks']['SessionStart'][0]['hooks']]
assert any('precompact-orchestrator' in c for c in pc), 'orchestrator not registered'
assert any('precompact-sentinel' in c for c in ss), 'sentinel not registered'
print('registered OK')"
echo "Flag currently: ${PRECOMPACT_ORCHESTRATOR_ENABLED:-<unset>}"
```
Expected: `valid JSON`, `registered OK`. Flag unset → orchestrator is a no-op; legacy hooks still do all the work. This is the shadow state.

- [ ] **Step 6: Commit the plan + rollout note (settings.json is outside the repo — document the change)**

```bash
cd /home/q/LAB/qLine
git add docs/superpowers/plans/2026-06-19-precompact-orchestrator.md
git commit -m "docs(precompact): implementation plan + rollout runbook

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: Enable + audit (manual, gated — runbook, not an automated step)**

This is the experiment phase. Perform deliberately, reviewing each capsule:

1. Export `PRECOMPACT_ORCHESTRATOR_ENABLED=1` in the environment Claude Code launches with.
2. Trigger ≥5 real compactions across ≥2 projects (at least one NON-qLine, since registration is global). For each: confirm the injected `[PreCompact capsule]` systemMessage contains the expected sections, and `read_capsule(<session_id>)` shows `_producers_failed == []` and `_empty == False` where content existed.
3. Run the forwarder once: `python3 /home/q/LAB/qLine/hooks/precompact_botpatches_forward.py` — confirm no rot payload on healthy runs.
4. Record audit results in the spec's Appendix C (append an audit log).

- [ ] **Step 8: Deregister legacy hooks (ONLY after 5 clean audits)**

After clean audits, remove the three legacy entries (`enrich-precompact.py`, `obs-precompact.py`, `precompact-preserve.py`) from the global `PreCompact` array. Keep `obs-precompact.py` if its telemetry is still wanted (it does not overlap the orchestrator's injection). **Rollback at any point:** `unset PRECOMPACT_ORCHESTRATOR_ENABLED` → orchestrator + sentinel no-op, legacy hooks resume. If legacy already deregistered, restore from `~/.claude/settings.json.bak-precompact-*`.

---

## Self-Review

**1. Spec coverage:**
- Consolidate 3 hooks → 1 orchestrator: Task 5 ✓
- Subprocess producer isolation (not import): Task 5 (`_subprocess_runner`) ✓
- Single fail-open boundary: Task 5 (`run_fail_open` wraps `main`) ✓
- Producers preserve/git/failures/stats/handoff: Task 4 ✓
- Dropped Brick findings-replay: not implemented (correctly absent) ✓
- Agent-authored handoff note + storage/ergonomics open question: Task 3 ✓
- Capsule + session-keyed file: Task 5 store ✓
- Hardening #1 bounded reads: Task 2 ✓
- Hardening #2 per-producer observability + SessionStart alert: Tasks 5 (envelope) + 6 (sentinel) + 7 (forward) ✓
- Hardening #3 ≤3s per-producer deadline: Task 5 (`PER_PRODUCER_DEADLINE_S`, subprocess `timeout`) ✓
- Hardening #4 empty-output signal: Task 1 (`_empty`) + Task 6 (`precompact_capsule_empty`) ✓
- Performance budget (no network on path): producers do only local git/file reads ✓
- Observability envelope: Task 1 ✓
- Rollout env flag + parallel + rollback + non-qLine audit: Task 8 ✓
- Testing: golden parity (Task 5), producer-failure (Task 5), bounded-read (Task 2), empty-session (Task 5) ✓
- Open question git active-repo derivation: Task 4 (`_git_roots_from_actions`, derived not fixed) ✓
- Open question ledger tail strategy: Task 2 (byte-bounded tail from EOF) ✓

**2. Placeholder scan:** No TBD/TODO/"handle edge cases" — every code step is complete and runnable.

**3. Type consistency:** Section keys (`open_tasks`, `active_plan`, `git_state`, `unresolved_failures`, `session_stats`, `handoff_note`) are defined once in `SECTION_KEYS` (Task 1) and used identically by producers (Task 4), render (Task 1), and tests. `merge_capsule(results, failed, elapsed_ms)`, `run_producers(inp)→(results, failed)`, `evaluate_capsule(capsule)→list[dict]`, `read_capsule`/`write_capsule(session_id, ..., base_dir=)` signatures are consistent across tasks. `is_strict("PRECOMPACT_ORCHESTRATOR_ENABLED")` is the single gate used by both hooks.

**Note on the `failures` producer ledger field:** the producer keys on `exit_code`. The current ledger sample did not include `exit_code` on every record; if the failed-command signal is stored under a different field, adjust `produce_failures` accordingly during Task 4 (the test seeds `exit_code` explicitly, so verify the live field name with `tail` on the ledger before relying on rollout data — `failures` is informational and its absence does not block the capsule).
