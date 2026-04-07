#!/usr/bin/env python3
"""TaskCompleted evidence hook (warn-first): checks for evidence when tasks complete.

Logs a warning to stderr when a task is completed without detectable evidence
of work (changed files, test references). Does NOT block completion.

Payload shape (verified from fixtures):
    session_id, transcript_path, cwd, hook_event_name, task_id, task_subject, task_description
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
from hook_utils import read_hook_input, is_strict, log_hook_diagnostic, run_fail_open

# Task subjects matching these patterns are exempt from evidence checks
EXEMPT_PATTERNS = [
    "research", "investigate", "explore", "read", "review",
    "document", "plan", "design", "discuss", "analyze",
]


def main():
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    task_subject = str(input_data.get("task_subject") or "")
    task_description = str(input_data.get("task_description") or "")
    task_id = str(input_data.get("task_id") or "?")
    cwd = str(input_data.get("cwd") or os.getcwd())

    # Exempt non-code tasks
    combined = (task_subject + " " + task_description).lower()
    if any(p in combined for p in EXEMPT_PATTERNS):
        sys.exit(0)

    # Check for uncommitted changes as evidence of work
    git_state = _check_git_changes(cwd)
    has_code_keywords = _has_code_evidence(combined)

    if git_state == "unknown":
        log_hook_diagnostic(
            "task-completed-gate", "TaskCompleted",
            "git_probe_failed",
            f"git status failed for task #{task_id} in {cwd}",
            context={"task_id": task_id, "cwd": cwd},
        )
        # Safety bias: assume changes exist, do not warn
        sys.exit(0)

    if has_code_keywords and git_state == "clean":
        msg = (
            f"[task-completed-gate] Task #{task_id} "
            f"(\"{task_subject}\") completed without detected file changes. "
            f"Consider verifying work was saved."
        )
        log_hook_diagnostic(
            "task-completed-gate", "TaskCompleted",
            "no_git_evidence", msg,
            level="warning",
            context={"task_id": task_id, "task_subject": task_subject},
        )
        if is_strict("CLAUDE_TASK_COMPLETED_STRICT"):
            # Strict mode: exit 2 blocks task completion
            print(msg, file=sys.stderr)
            sys.exit(2)
        else:
            print(f"Warning: {msg}", file=sys.stderr)

    sys.exit(0)


def _check_git_changes(cwd: str) -> str:
    """Tri-state git probe: returns 'dirty', 'clean', or 'unknown'."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=3, cwd=cwd,
        )
        if result.returncode != 0:
            return "unknown"
        return "dirty" if result.stdout.strip() else "clean"
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def _has_code_evidence(text: str) -> bool:
    """Check if the task text suggests code implementation work."""
    code_signals = [
        "implement", "add", "create", "fix", "build", "write",
        "refactor", "update", "modify", "change", "migrate",
    ]
    return any(s in text for s in code_signals)


if __name__ == "__main__":
    run_fail_open(main, "task-completed-gate", "TaskCompleted")
