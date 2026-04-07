# Brick Verifiable Utility Experiment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Instrument the Brick enrichment pipeline to produce verifiable, measurable proof of utility across three dimensions: context protection, code quality gating, and session continuity.

**Architecture:** Three surgical changes to existing hooks and one new analysis script. Each dimension gets its own metric that can be independently validated. No new hooks, no new timers — we add fields to existing data flows and build a single analyzer that computes hard numbers from the enriched data.

**Tech Stack:** Python 3, existing hook framework (hook_utils), existing metrics JSONL, pytest

---

## File Structure

| File | Responsibility |
|------|---------------|
| `hooks/enrich-pretool-read.py` | **Modify:** Add `enrichment_id` to additionalContext, log it in metrics |
| `hooks/enrich-posttool-write.py` | **Modify:** Add `enrichment_id` to additionalContext, log it in metrics |
| `hooks/brick_action_ledger.py` | **Modify:** Add `read_count` per (session, file_path) tracking |
| `hooks/brick_metrics.py` | **Modify:** Add `enrichment_id` field to schema |
| `scripts/brick_utility_analyzer.py` | **Create:** Single script that computes all three verifiable metrics |
| `hooks/tests/test_enrichment_id.py` | **Create:** Tests for enrichment_id generation and injection |
| `hooks/tests/test_read_count.py` | **Create:** Tests for re-read tracking |
| `hooks/tests/test_utility_analyzer.py` | **Create:** Tests for the analyzer logic |

---

### Task 1: Add enrichment_id to Read hook

**Files:**
- Modify: `hooks/enrich-pretool-read.py:170-177`
- Modify: `hooks/brick_metrics.py:38-63` (add enrichment_id param)
- Create: `hooks/tests/test_enrichment_id.py`

The enrichment_id is a short UUID that gets embedded in additionalContext AND logged to metrics. This creates a machine-readable correlation key between "what was injected" and "what the agent did next."

- [ ] **Step 1: Write failing test for enrichment_id generation**

Create `hooks/tests/test_enrichment_id.py`:

```python
"""Tests for enrichment_id injection in Read and Write hooks."""
import importlib.util
import json
import os
import sys
import uuid
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_mod_path = os.path.join(os.path.dirname(__file__), "..", "enrich-pretool-read.py")
_spec = importlib.util.spec_from_file_location("enrich_pretool_read", _mod_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


class TestEnrichmentIdInReadContext:
    """enrichment_id must appear in additionalContext for downstream correlation."""

    @patch("urllib.request.urlopen")
    def test_enrichment_id_in_context_string(self, mock_urlopen):
        """The context string must contain a machine-readable enrichment_id."""
        response_data = {"tree": {"root": {"content": "File has 3 classes..."}}}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        summary = _mod.call_brick_summarize("content", "/path/file.py", "key")
        # Build context the same way main() does
        enrichment_id = "test-eid-123"
        context = _mod.build_enrichment_context(
            file_path="/path/file.py",
            line_count=500,
            summary=summary,
            enrichment_id=enrichment_id,
        )
        assert "enrichment_id=test-eid-123" in context
        assert "🧱 Brick enriched Read" in context

    def test_build_enrichment_context_contains_all_fields(self):
        """Context must contain file path, line count, enrichment_id, and summary."""
        context = _mod.build_enrichment_context(
            file_path="/src/app.py",
            line_count=350,
            summary="3 classes, 5 functions",
            enrichment_id="abc123",
        )
        assert "/src/app.py" in context
        assert "350" in context
        assert "enrichment_id=abc123" in context
        assert "3 classes, 5 functions" in context
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_enrichment_id.py -v 2>&1 | tail -10`
Expected: FAIL — `build_enrichment_context` does not exist yet.

- [ ] **Step 3: Add enrichment_id parameter to log_enrichment**

In `hooks/brick_metrics.py`, add `enrichment_id` to the function signature and entry dict:

```python
# Add to log_enrichment signature (after trace_id parameter):
    enrichment_id: str = "",  # machine-readable correlation key for utility measurement

# Add to entry dict (after trace_id block):
    if enrichment_id:
        entry["enrichment_id"] = enrichment_id
```

- [ ] **Step 4: Add build_enrichment_context to Read hook**

In `hooks/enrich-pretool-read.py`, add the helper function after `call_brick_summarize`:

```python
def build_enrichment_context(
    file_path: str, line_count: int, summary: str, enrichment_id: str,
) -> str:
    """Build additionalContext string with machine-readable enrichment_id."""
    return (
        f"[🧱 Brick enriched Read: {file_path} ({line_count} lines) "
        f"enrichment_id={enrichment_id} — show this to user] {summary}"
    )
```

- [ ] **Step 5: Wire enrichment_id into main()**

In `hooks/enrich-pretool-read.py`, replace the success block (lines 170-177) with:

```python
    if summary:
        cb.record_success()
        import uuid
        enrichment_id = str(uuid.uuid4())[:12]
        tokens_orig = int(line_count * 80 / 4)
        tokens_summ = int(len(summary) / 4)
        context = build_enrichment_context(file_path, line_count, summary, enrichment_id)
        log_enrichment(
            "read", session_id, "Read", file_path,
            action="enriched", latency_ms=latency_ms,
            findings_preview=summary, lines_changed=line_count,
            tokens_original=tokens_orig, tokens_summary=tokens_summ,
            enrichment_id=enrichment_id,
        )
        allow_with_context(context, event=_EVENT_NAME)
```

- [ ] **Step 6: Run tests**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_enrichment_id.py hooks/tests/test_pretool_read.py -v 2>&1 | tail -15`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
cd /home/q/LAB/qLine && git add hooks/enrich-pretool-read.py hooks/brick_metrics.py hooks/tests/test_enrichment_id.py
git commit -m "feat: add enrichment_id to Read hook for utility correlation"
```

---

### Task 2: Add enrichment_id to Write hook

**Files:**
- Modify: `hooks/enrich-posttool-write.py:224-233`
- Modify: `hooks/tests/test_enrichment_id.py` (add Write tests)

Same pattern as Read — embed enrichment_id in the context string and log it to metrics.

- [ ] **Step 1: Write failing test for Write hook enrichment_id**

Append to `hooks/tests/test_enrichment_id.py`:

```python
# Import write hook
_write_mod_path = os.path.join(os.path.dirname(__file__), "..", "enrich-posttool-write.py")
_write_spec = importlib.util.spec_from_file_location("enrich_posttool_write", _write_mod_path)
_write_mod = importlib.util.module_from_spec(_write_spec)
_write_spec.loader.exec_module(_write_mod)


class TestEnrichmentIdInWriteContext:
    """enrichment_id must appear in Write hook additionalContext."""

    def test_build_write_enrichment_context(self):
        context = _write_mod.build_write_enrichment_context(
            file_path="/src/app.py",
            summary="Missing error handling in try block",
            enrichment_id="def456",
        )
        assert "enrichment_id=def456" in context
        assert "🧱 Brick reviewed Write" in context
        assert "/src/app.py" in context
        assert "Missing error handling" in context
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_enrichment_id.py::TestEnrichmentIdInWriteContext -v 2>&1 | tail -10`
Expected: FAIL — `build_write_enrichment_context` does not exist.

- [ ] **Step 3: Add build_write_enrichment_context and wire it in**

In `hooks/enrich-posttool-write.py`, add after `extract_summary`:

```python
def build_write_enrichment_context(
    file_path: str, summary: str, enrichment_id: str,
) -> str:
    """Build additionalContext string with machine-readable enrichment_id."""
    return (
        f"[🧱 Brick reviewed Write: {file_path} "
        f"enrichment_id={enrichment_id} — show this to user] {summary}"
    )
```

Replace the success block (lines 224-233) with:

```python
    if summary is not None:
        cb.record_success()
        import uuid
        enrichment_id = str(uuid.uuid4())[:12]
        tokens_orig = int(len(content) / 4)
        tokens_summ = int(len(summary) / 4)
        log_enrichment(
            "write", session_id, tool_name, file_path,
            action="enriched", latency_ms=latency_ms,
            findings_preview=summary, lines_changed=lines_changed,
            action_id=action_id, tokens_original=tokens_orig,
            tokens_summary=tokens_summ, enrichment_id=enrichment_id,
        )
        if log_artifact_change is not None:
            log_artifact_change(session_id, tool_name, file_path, lines_changed, brick_findings=summary, cwd=input_data.get("cwd", ""))
        context = build_write_enrichment_context(file_path, summary, enrichment_id)
        allow_with_context(context, event=_EVENT_NAME)
```

- [ ] **Step 4: Run all enrichment_id tests**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_enrichment_id.py hooks/tests/test_enrich_write.py -v 2>&1 | tail -15`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /home/q/LAB/qLine && git add hooks/enrich-posttool-write.py hooks/tests/test_enrichment_id.py
git commit -m "feat: add enrichment_id to Write hook for utility correlation"
```

---

### Task 3: Add re-read tracking to action ledger

**Files:**
- Modify: `hooks/brick_action_ledger.py:81-122`
- Create: `hooks/tests/test_read_count.py`

Track how many times each file is read within a session. This enables measuring whether enriched reads reduce re-reads (context protection utility).

- [ ] **Step 1: Write failing test for read_count**

Create `hooks/tests/test_read_count.py`:

```python
"""Tests for re-read tracking in action ledger."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from brick_action_ledger import log_action, get_read_count, LEDGER_PATH


class TestReadCount:
    """Track file read frequency within a session."""

    @pytest.fixture(autouse=True)
    def _tmp_ledger(self, tmp_path):
        """Redirect ledger to temp file."""
        self.ledger = tmp_path / "test-ledger.jsonl"
        with patch("brick_action_ledger.LEDGER_PATH", self.ledger):
            yield

    def test_first_read_returns_one(self):
        with patch("brick_action_ledger.LEDGER_PATH", self.ledger):
            log_action("sess1", "Read", file_path="/src/app.py")
            assert get_read_count("sess1", "/src/app.py") == 1

    def test_second_read_returns_two(self):
        with patch("brick_action_ledger.LEDGER_PATH", self.ledger):
            log_action("sess1", "Read", file_path="/src/app.py")
            log_action("sess1", "Read", file_path="/src/app.py")
            assert get_read_count("sess1", "/src/app.py") == 2

    def test_different_files_tracked_separately(self):
        with patch("brick_action_ledger.LEDGER_PATH", self.ledger):
            log_action("sess1", "Read", file_path="/src/app.py")
            log_action("sess1", "Read", file_path="/src/utils.py")
            assert get_read_count("sess1", "/src/app.py") == 1
            assert get_read_count("sess1", "/src/utils.py") == 1

    def test_different_sessions_tracked_separately(self):
        with patch("brick_action_ledger.LEDGER_PATH", self.ledger):
            log_action("sess1", "Read", file_path="/src/app.py")
            log_action("sess2", "Read", file_path="/src/app.py")
            assert get_read_count("sess1", "/src/app.py") == 1
            assert get_read_count("sess2", "/src/app.py") == 1

    def test_non_read_tools_not_counted(self):
        with patch("brick_action_ledger.LEDGER_PATH", self.ledger):
            log_action("sess1", "Write", file_path="/src/app.py")
            assert get_read_count("sess1", "/src/app.py") == 0

    def test_read_count_in_logged_entry(self):
        """log_action should include read_count field for Read tool."""
        with patch("brick_action_ledger.LEDGER_PATH", self.ledger):
            log_action("sess1", "Read", file_path="/src/app.py")
            log_action("sess1", "Read", file_path="/src/app.py")
            # Read the last entry
            lines = self.ledger.read_text().strip().split("\n")
            last = json.loads(lines[-1])
            assert last["read_count"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_read_count.py -v 2>&1 | tail -10`
Expected: FAIL — `get_read_count` does not exist.

- [ ] **Step 3: Implement get_read_count and wire into log_action**

In `hooks/brick_action_ledger.py`, add after `derive_action_id`:

```python
def get_read_count(session_id: str, file_path: str) -> int:
    """Count how many times a file was read in a session. Never raises."""
    try:
        if not LEDGER_PATH.exists():
            return 0
        count = 0
        with open(LEDGER_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    entry.get("session_id") == session_id
                    and entry.get("tool") == "Read"
                    and entry.get("file_path") == file_path
                ):
                    count += 1
        return count
    except Exception:
        return 0
```

In `log_action`, after building the entry dict (after line 109), add:

```python
        # Track re-read count for Read tool
        if tool == "Read" and file_path:
            # Count existing reads BEFORE writing this one
            existing = get_read_count(session_id, file_path)
            entry["read_count"] = existing + 1
```

- [ ] **Step 4: Run tests**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_read_count.py hooks/tests/test_brick_action_ledger.py -v 2>&1 | tail -15`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /home/q/LAB/qLine && git add hooks/brick_action_ledger.py hooks/tests/test_read_count.py
git commit -m "feat: add re-read tracking to action ledger for context protection measurement"
```

---

### Task 4: Build the utility analyzer

**Files:**
- Create: `scripts/brick_utility_analyzer.py`
- Create: `hooks/tests/test_utility_analyzer.py`

Single script that computes three independently verifiable metrics from existing data:

**Metric A — Context Protection:** Average re-reads per file for enriched vs unenriched large-file reads. Lower re-reads on enriched files = context protection works.

**Metric B — Code Quality Gate:** For each Write enrichment with findings, check if the agent's next action on the same file within 120s addresses the finding (Edit/Write on same file). Compare against unenriched writes. Higher follow-up rate = quality gate works.

**Metric C — Session Continuity:** For sessions with SessionStart enrichment, compare error/retry rates (Bash exit_code != 0) against sessions without. Lower error rate = continuity works.

- [ ] **Step 1: Write failing tests for the analyzer**

Create `hooks/tests/test_utility_analyzer.py`:

```python
"""Tests for brick_utility_analyzer — verifiable utility metrics."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

# Will fail until module exists
from brick_utility_analyzer import (
    compute_context_protection,
    compute_quality_gate,
    compute_session_continuity,
)


def write_jsonl(path: Path, entries: list[dict]) -> None:
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


class TestContextProtection:
    """Metric A: enriched reads should produce fewer re-reads."""

    def test_enriched_file_fewer_rereads(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        metrics = tmp_path / "metrics.jsonl"

        # Enriched read of big_file: read once, then Edit (no re-read)
        write_jsonl(ledger, [
            {"session_id": "s1", "tool": "Read", "file_path": "/big.py", "read_count": 1, "enriched": True, "ts": "2026-04-06T01:00:00"},
            {"session_id": "s1", "tool": "Edit", "file_path": "/big.py", "ts": "2026-04-06T01:00:10"},
        ])
        # Enrichment metric confirming enrichment happened
        write_jsonl(metrics, [
            {"hook": "read", "session_id": "s1", "file_path": "/big.py", "action": "enriched", "lines_changed": 500, "ts": "2026-04-06T01:00:00"},
        ])

        result = compute_context_protection(ledger, metrics)
        assert result["enriched_avg_reads"] == 1.0
        assert result["enriched_file_count"] >= 1

    def test_unenriched_file_more_rereads(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        metrics = tmp_path / "metrics.jsonl"

        # Unenriched: read same file 3 times
        write_jsonl(ledger, [
            {"session_id": "s1", "tool": "Read", "file_path": "/big.py", "read_count": 1, "enriched": False, "ts": "2026-04-06T01:00:00"},
            {"session_id": "s1", "tool": "Read", "file_path": "/big.py", "read_count": 2, "enriched": False, "ts": "2026-04-06T01:01:00"},
            {"session_id": "s1", "tool": "Read", "file_path": "/big.py", "read_count": 3, "enriched": False, "ts": "2026-04-06T01:02:00"},
        ])
        write_jsonl(metrics, [
            {"hook": "read", "session_id": "s1", "file_path": "/big.py", "action": "skipped", "reason": "circuit_breaker", "lines_changed": 500, "ts": "2026-04-06T01:00:00"},
        ])

        result = compute_context_protection(ledger, metrics)
        assert result["unenriched_avg_reads"] == 3.0

    def test_empty_data_returns_zeroes(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        metrics = tmp_path / "metrics.jsonl"
        ledger.write_text("")
        metrics.write_text("")
        result = compute_context_protection(ledger, metrics)
        assert result["enriched_avg_reads"] == 0.0
        assert result["unenriched_avg_reads"] == 0.0


class TestQualityGate:
    """Metric B: enriched writes should produce more follow-up edits."""

    def test_enriched_write_with_followup(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        metrics = tmp_path / "metrics.jsonl"

        write_jsonl(metrics, [
            {"hook": "write", "session_id": "s1", "file_path": "/app.py", "action": "enriched",
             "enrichment_id": "eid1", "findings_preview": "Missing null check", "ts": "2026-04-06T01:00:00"},
        ])
        write_jsonl(ledger, [
            {"session_id": "s1", "tool": "Write", "file_path": "/app.py", "ts": "2026-04-06T01:00:00"},
            {"session_id": "s1", "tool": "Edit", "file_path": "/app.py", "ts": "2026-04-06T01:00:30"},
        ])

        result = compute_quality_gate(ledger, metrics)
        assert result["enriched_followup_rate"] > 0.0

    def test_unenriched_write_no_followup(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        metrics = tmp_path / "metrics.jsonl"

        write_jsonl(metrics, [
            {"hook": "write", "session_id": "s1", "file_path": "/app.py", "action": "skipped",
             "reason": "circuit_open", "ts": "2026-04-06T01:00:00"},
        ])
        write_jsonl(ledger, [
            {"session_id": "s1", "tool": "Write", "file_path": "/app.py", "ts": "2026-04-06T01:00:00"},
            {"session_id": "s1", "tool": "Read", "file_path": "/other.py", "ts": "2026-04-06T01:00:30"},
        ])

        result = compute_quality_gate(ledger, metrics)
        assert result["unenriched_followup_rate"] == 0.0

    def test_empty_data(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        metrics = tmp_path / "metrics.jsonl"
        ledger.write_text("")
        metrics.write_text("")
        result = compute_quality_gate(ledger, metrics)
        assert result["enriched_followup_rate"] == 0.0


class TestSessionContinuity:
    """Metric C: sessions with context injection should have lower error rates."""

    def test_enriched_session_fewer_errors(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        metrics = tmp_path / "metrics.jsonl"

        # Session with SessionStart enrichment: 1 error in 10 bash commands
        write_jsonl(metrics, [
            {"hook": "session_start", "session_id": "s1", "action": "enriched", "ts": "2026-04-06T01:00:00"},
        ])
        bash_entries = []
        for i in range(10):
            bash_entries.append({
                "session_id": "s1", "tool": "Bash", "exit_code": 1 if i == 0 else 0,
                "ts": f"2026-04-06T01:0{i}:00",
            })
        write_jsonl(ledger, bash_entries)

        result = compute_session_continuity(ledger, metrics)
        assert result["enriched_error_rate"] == 0.1
        assert result["enriched_session_count"] == 1

    def test_empty_data(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        metrics = tmp_path / "metrics.jsonl"
        ledger.write_text("")
        metrics.write_text("")
        result = compute_session_continuity(ledger, metrics)
        assert result["enriched_error_rate"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_utility_analyzer.py -v 2>&1 | tail -10`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement brick_utility_analyzer.py**

Create `scripts/brick_utility_analyzer.py`:

```python
#!/usr/bin/env python3
"""Brick Utility Analyzer — verifiable metrics for enrichment value.

Computes three independent metrics from existing JSONL data:
A) Context Protection: re-read reduction on enriched vs unenriched large files
B) Code Quality Gate: follow-up edit rate on enriched vs unenriched writes
C) Session Continuity: error rate in enriched vs unenriched sessions

Each metric is independently falsifiable — no bundled "overall score."
"""
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

LEDGER_FILE = Path.home() / ".local/share/brick-lab/action-ledger.jsonl"
ENRICH_FILE = Path("/tmp/brick-lab/enrich-metrics.jsonl")
LATEST_FILE = Path("/tmp/brick-lab/utility-latest.json")
JSONL_FILE = Path("/tmp/brick-lab/utility-metrics.jsonl")

QUALITY_GATE_WINDOW_S = 120.0  # 2 minutes for follow-up edits


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not path.exists():
        return entries
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def parse_ts(ts_str: str) -> float:
    try:
        return datetime.fromisoformat(ts_str).timestamp()
    except (ValueError, TypeError):
        return 0.0


def compute_context_protection(
    ledger_path: Path, metrics_path: Path,
) -> dict[str, Any]:
    """Metric A: average re-reads per file for enriched vs unenriched large-file reads.

    Uses read_count from action ledger to find max reads per (session, file).
    Compares files that were enriched by Read hook vs files that were skipped
    (due to circuit breaker or other reasons) on large files (>200 lines).
    """
    ledger = load_jsonl(ledger_path)
    metrics = load_jsonl(metrics_path)

    # Find large-file Read events from metrics (both enriched and skipped)
    enriched_files: set[tuple[str, str]] = set()  # (session_id, file_path)
    skipped_large_files: set[tuple[str, str]] = set()

    for m in metrics:
        if m.get("hook") != "read":
            continue
        sid = m.get("session_id", "")
        fp = m.get("file_path", "")
        if not sid or not fp:
            continue
        lines = m.get("lines_changed", 0)
        if lines < 200:
            continue
        if m.get("action") == "enriched":
            enriched_files.add((sid, fp))
        elif m.get("action") == "skipped" and m.get("reason") in ("circuit_breaker", "circuit_open"):
            skipped_large_files.add((sid, fp))

    # Get max read_count per (session, file) from ledger
    max_reads: dict[tuple[str, str], int] = defaultdict(int)
    for entry in ledger:
        if entry.get("tool") != "Read":
            continue
        key = (entry.get("session_id", ""), entry.get("file_path", ""))
        rc = entry.get("read_count", 1)
        if rc > max_reads[key]:
            max_reads[key] = rc

    # Compute averages
    enriched_counts = [max_reads.get(k, 1) for k in enriched_files if k in max_reads]
    unenriched_counts = [max_reads.get(k, 1) for k in skipped_large_files if k in max_reads]

    return {
        "enriched_avg_reads": round(sum(enriched_counts) / len(enriched_counts), 2) if enriched_counts else 0.0,
        "unenriched_avg_reads": round(sum(unenriched_counts) / len(unenriched_counts), 2) if unenriched_counts else 0.0,
        "enriched_file_count": len(enriched_counts),
        "unenriched_file_count": len(unenriched_counts),
        "delta": round(
            (sum(unenriched_counts) / len(unenriched_counts) if unenriched_counts else 0.0)
            - (sum(enriched_counts) / len(enriched_counts) if enriched_counts else 0.0),
            2,
        ),
    }


def compute_quality_gate(
    ledger_path: Path, metrics_path: Path,
) -> dict[str, Any]:
    """Metric B: follow-up edit rate on enriched vs unenriched writes.

    For each Write/Edit enrichment with findings, check if the agent
    followed up with another Edit/Write on the same file within 120s.
    Compare against writes where enrichment was skipped.
    """
    ledger = load_jsonl(ledger_path)
    metrics = load_jsonl(metrics_path)

    # Build session action timelines from ledger
    sessions: dict[str, list[dict]] = defaultdict(list)
    for entry in ledger:
        sid = entry.get("session_id", "")
        if sid:
            sessions[sid].append(entry)
    for actions in sessions.values():
        actions.sort(key=lambda a: parse_ts(a.get("ts", "")))

    # Classify write events
    enriched_writes: list[dict] = []
    skipped_writes: list[dict] = []
    for m in metrics:
        if m.get("hook") != "write":
            continue
        if m.get("action") == "enriched" and m.get("findings_preview"):
            enriched_writes.append(m)
        elif m.get("action") == "skipped" and m.get("reason") in ("circuit_open", "circuit_breaker"):
            skipped_writes.append(m)

    def has_followup(event: dict, session_actions: list[dict]) -> bool:
        ev_ts = parse_ts(event.get("ts", ""))
        ev_file = event.get("file_path", "")
        if not ev_ts or not ev_file:
            return False
        for act in session_actions:
            act_ts = parse_ts(act.get("ts", ""))
            if act_ts <= ev_ts:
                continue
            delta = act_ts - ev_ts
            if delta > QUALITY_GATE_WINDOW_S:
                break
            if act.get("file_path") == ev_file and act.get("tool") in ("Edit", "Write"):
                return True
        return False

    enriched_followups = sum(
        1 for w in enriched_writes
        if has_followup(w, sessions.get(w.get("session_id", ""), []))
    )
    unenriched_followups = sum(
        1 for w in skipped_writes
        if has_followup(w, sessions.get(w.get("session_id", ""), []))
    )

    return {
        "enriched_followup_rate": round(enriched_followups / len(enriched_writes), 4) if enriched_writes else 0.0,
        "unenriched_followup_rate": round(unenriched_followups / len(skipped_writes), 4) if skipped_writes else 0.0,
        "enriched_write_count": len(enriched_writes),
        "unenriched_write_count": len(skipped_writes),
        "enriched_followups": enriched_followups,
        "unenriched_followups": unenriched_followups,
    }


def compute_session_continuity(
    ledger_path: Path, metrics_path: Path,
) -> dict[str, Any]:
    """Metric C: Bash error rate in sessions with vs without SessionStart enrichment.

    Sessions with past-context injection should show fewer errors
    (agent doesn't repeat known-bad approaches).
    """
    ledger = load_jsonl(ledger_path)
    metrics = load_jsonl(metrics_path)

    # Find sessions with SessionStart enrichment
    enriched_sessions: set[str] = set()
    for m in metrics:
        if m.get("hook") == "session_start" and m.get("action") == "enriched":
            enriched_sessions.add(m.get("session_id", ""))

    # Count Bash errors per session
    session_bash: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "errors": 0})
    for entry in ledger:
        if entry.get("tool") != "Bash":
            continue
        sid = entry.get("session_id", "")
        if not sid:
            continue
        session_bash[sid]["total"] += 1
        if entry.get("exit_code") is not None and entry["exit_code"] != 0:
            session_bash[sid]["errors"] += 1

    # Compute error rates
    enriched_totals = 0
    enriched_errors = 0
    unenriched_totals = 0
    unenriched_errors = 0
    enriched_count = 0
    unenriched_count = 0

    for sid, counts in session_bash.items():
        if counts["total"] == 0:
            continue
        if sid in enriched_sessions:
            enriched_totals += counts["total"]
            enriched_errors += counts["errors"]
            enriched_count += 1
        else:
            unenriched_totals += counts["total"]
            unenriched_errors += counts["errors"]
            unenriched_count += 1

    return {
        "enriched_error_rate": round(enriched_errors / enriched_totals, 4) if enriched_totals else 0.0,
        "unenriched_error_rate": round(unenriched_errors / unenriched_totals, 4) if unenriched_totals else 0.0,
        "enriched_session_count": enriched_count,
        "unenriched_session_count": unenriched_count,
        "enriched_bash_total": enriched_totals,
        "unenriched_bash_total": unenriched_totals,
    }


def main() -> None:
    from datetime import timezone

    now = datetime.now(timezone.utc)

    a = compute_context_protection(LEDGER_FILE, ENRICH_FILE)
    b = compute_quality_gate(LEDGER_FILE, ENRICH_FILE)
    c = compute_session_continuity(LEDGER_FILE, ENRICH_FILE)

    report = {
        "ts": now.isoformat(),
        "context_protection": a,
        "quality_gate": b,
        "session_continuity": c,
    }

    # Write outputs
    LATEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        LATEST_FILE.write_text(json.dumps(report, indent=2) + "\n")
    except OSError:
        pass
    try:
        with open(JSONL_FILE, "a") as f:
            f.write(json.dumps(report) + "\n")
    except OSError:
        pass

    # Print summary
    print("=" * 60)
    print("BRICK UTILITY REPORT")
    print("=" * 60)
    print()
    print(f"A) Context Protection (re-reads per large file):")
    print(f"   Enriched: {a['enriched_avg_reads']:.1f} avg reads ({a['enriched_file_count']} files)")
    print(f"   Unenriched: {a['unenriched_avg_reads']:.1f} avg reads ({a['unenriched_file_count']} files)")
    print(f"   Delta: {a['delta']:+.1f} reads {'(BETTER)' if a['delta'] > 0 else '(WORSE)' if a['delta'] < 0 else '(NEUTRAL)'}")
    print()
    print(f"B) Code Quality Gate (follow-up edit rate):")
    print(f"   Enriched: {b['enriched_followup_rate']:.1%} ({b['enriched_followups']}/{b['enriched_write_count']})")
    print(f"   Unenriched: {b['unenriched_followup_rate']:.1%} ({b['unenriched_followups']}/{b['unenriched_write_count']})")
    print()
    print(f"C) Session Continuity (bash error rate):")
    print(f"   Enriched: {c['enriched_error_rate']:.1%} ({c['enriched_session_count']} sessions, {c['enriched_bash_total']} cmds)")
    print(f"   Unenriched: {c['unenriched_error_rate']:.1%} ({c['unenriched_session_count']} sessions, {c['unenriched_bash_total']} cmds)")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/test_utility_analyzer.py -v 2>&1 | tail -20`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /home/q/LAB/qLine && git add scripts/brick_utility_analyzer.py hooks/tests/test_utility_analyzer.py
git commit -m "feat: add brick utility analyzer with three verifiable metrics"
```

---

### Task 5: Run analyzer against live data and sync hooks

**Files:**
- No new files — runs existing scripts and syncs installed hooks

- [ ] **Step 1: Run the analyzer against live data**

```bash
cd /home/q/LAB/qLine && python3 scripts/brick_utility_analyzer.py
```

Expected: Report with current numbers for all three metrics. These are the baseline numbers before the enrichment_id instrumentation takes effect.

- [ ] **Step 2: Sync modified hooks to installed location**

```bash
cp hooks/enrich-pretool-read.py ~/.claude/hooks/enrich-pretool-read.py
cp hooks/enrich-posttool-write.py ~/.claude/hooks/enrich-posttool-write.py
cp hooks/brick_action_ledger.py ~/.claude/hooks/brick_action_ledger.py
cp hooks/brick_metrics.py ~/.claude/hooks/brick_metrics.py
```

- [ ] **Step 3: Run full test suite to verify no regressions**

```bash
cd /home/q/LAB/qLine && python3 -m pytest hooks/tests/ -q 2>&1 | tail -10
```

Expected: All tests pass, no regressions.

- [ ] **Step 4: Commit sync**

```bash
cd /home/q/LAB/qLine && git add -A
git commit -m "feat: sync instrumented hooks and run baseline utility analysis"
```

- [ ] **Step 5: Report baseline numbers**

Read `/tmp/brick-lab/utility-latest.json` and report the three metrics to the group. These are the numbers we'll measure improvement against.
