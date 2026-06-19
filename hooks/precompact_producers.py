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
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hook_utils import iter_open_tasks, find_latest_plan  # noqa: E402
from precompact_ledger import read_session_actions, _read_tail_lines  # noqa: E402
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
# Source: `tool.failed` events in the obs package's metadata/hook_events.jsonl
# (the action-ledger carries NO exit status). Success events are not in this
# stream, so v1 reports DISTINCT failed commands this session, deduped by
# command_hash. Informational; degrades to None cleanly.

_MAX_EVENTS_BYTES = 1 * 1024 * 1024
_PREVIEW_MAX_CHARS = 100

# Credential-bearing patterns redacted before a failed command is surfaced into
# the compacted context (no-leak principle: never inject raw secrets).
_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization:\s*bearer\s+)\S+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)(--?(?:password|token|secret|api[-_]?key|apikey)[=\s]+)\S+"),
    re.compile(r"(?i)(-p\s+)\S+"),
    re.compile(r"\b(sk|ghp|gho|ghu|ghs|ghr|xox[baprs])[-_][A-Za-z0-9]{8,}"),
    re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),  # long base64-ish blobs
]


def _safe_preview(text) -> str:
    """Redact known credential patterns and truncate. Display-only signal."""
    s = str(text or "")
    for pat in _SECRET_PATTERNS:
        s = pat.sub(lambda m: (m.group(1) if m.lastindex else "") + "<redacted>", s)
    s = s.replace("\n", " ").strip()
    return s[:_PREVIEW_MAX_CHARS]


def read_session_failed_commands(session_id: str) -> list[dict]:
    """Return tool.failed event records for the session (bounded tail). Never raises."""
    try:
        from obs_utils import resolve_package_root_env
        root = resolve_package_root_env(session_id)
    except Exception:
        return []
    if not root:
        return []
    events_path = os.path.join(root, "metadata", "hook_events.jsonl")
    if not os.path.exists(events_path):
        return []
    out: list[dict] = []
    try:
        for line in _read_tail_lines(events_path, _MAX_EVENTS_BYTES):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(rec, dict) and (rec.get("event") or rec.get("event_type")) == "tool.failed":
                out.append(rec)
    except OSError:
        return []
    return out


def produce_failures(inp: dict) -> dict | None:
    session_id = str(inp.get("session_id") or "")
    fails = read_session_failed_commands(session_id)
    seen: set = set()
    cmds: list[str] = []
    for rec in fails:
        key = rec.get("command_hash") or rec.get("command_preview")
        if key in seen:
            continue
        seen.add(key)
        # A failed-tool record with neither a command preview nor an error
        # string carries no actionable information. Rendering a "(failed tool)"
        # placeholder is non-actionable noise — drop the record instead.
        raw = rec.get("command_preview") or rec.get("error")
        if not raw:
            continue
        cmds.append(_safe_preview(raw))
    if not cmds:
        return None
    return {"unresolved_failures": cmds[:_MAX_FAILURES]}


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
