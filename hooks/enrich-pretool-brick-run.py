#!/usr/bin/env python3
"""PreToolUse(Bash) hook: route verbose commands through brick-run.

Detects test, build, and lint commands and prepends `brick-run --shell --`
so their output goes through Brick summarization BEFORE entering the context
window. brick-run handles its own threshold logic (passes through small output
raw, only summarizes large output).

This is P6a — the highest-value context load reduction item. Unlike PostToolUse
enrichment (additive), this is SUBSTITUTIVE: the agent sees the summary instead
of raw verbose output.

Safety:
- Skips commands with existing pipes/redirects (user already managing output)
- Skips commands wrapped in brick-run already
- Respects circuit breaker (OPEN = pass through)
- Fail-open: any error lets the command through unmodified
- Only matches known verbose command families
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hook_utils import read_hook_input, run_fail_open
from brick_circuit import CircuitBreaker
from brick_metrics import log_enrichment

_HOOK_NAME = "enrich-pretool-brick-run"
_EVENT_NAME = "PreToolUse"
_BRICK_RUN = os.path.expanduser("~/.local/bin/brick-run")

# ── Verbose command patterns ─────────────────────────────────────────────────
# Each tuple: (compiled_regex, command_family, format_hint)
# format_hint helps brick-run pick the right parser
_VERBOSE_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # Test runners
    (re.compile(r'(?:^|\b)(?:python3?\s+-m\s+)?pytest\b'), "pytest", "test_log"),
    (re.compile(r'(?:^|\b)(?:npx\s+)?vitest\b'), "vitest", "test_log"),
    (re.compile(r'(?:^|\b)(?:npx\s+)?jest\b'), "jest", "test_log"),
    (re.compile(r'\bcargo\s+test\b'), "cargo_test", "test_log"),
    (re.compile(r'\bgo\s+test\b'), "go_test", "test_log"),
    (re.compile(r'\bnpm\s+(?:run\s+)?test\b'), "npm_test", "test_log"),
    (re.compile(r'\byarn\s+test\b'), "yarn_test", "test_log"),
    (re.compile(r'\bmake\s+(?:test|check)\b'), "make_test", "test_log"),
    # Build commands
    (re.compile(r'\bnpm\s+run\s+build\b'), "npm_build", "build_log"),
    (re.compile(r'\byarn\s+build\b'), "yarn_build", "build_log"),
    (re.compile(r'(?:^|\b)tsc\b'), "tsc", "build_log"),
    (re.compile(r'\bcargo\s+build\b'), "cargo_build", "build_log"),
    (re.compile(r'\bgo\s+build\b'), "go_build", "build_log"),
    (re.compile(r'(?:^|\b)make\b(?!\s+(?:test|check))'), "make", "build_log"),
    # Lint commands
    (re.compile(r'(?:^|\b)(?:npx\s+)?eslint\b'), "eslint", "build_log"),
    (re.compile(r'(?:^|\b)(?:python3?\s+-m\s+)?(?:ruff|pylint|mypy|pyright)\b'), "python_lint", "build_log"),
    (re.compile(r'(?:^|\b)(?:npx\s+)?tsc\s+--noEmit\b'), "tsc_check", "build_log"),
    (re.compile(r'\bcargo\s+clippy\b'), "cargo_clippy", "build_log"),
]

# ── Patterns that indicate the user is already managing output ────────────────
# Pipes, redirects, process substitution, tee, etc.
_OUTPUT_MANAGED_RE = re.compile(
    r'[|]'           # pipe
    r'|>\s*\S'       # redirect to file (> file, >> file, 2> file)
    r'|2>&1\s*>'     # redirect stderr+stdout to file
    r'|\btee\b'      # tee
    r'|\bbrick-run\b'  # already wrapped
)

# Commands that are too short / simple to benefit from brick-run
# e.g. `pytest --co -q` (just listing tests), `make -n` (dry run)
_DRY_RUN_RE = re.compile(
    r'--collect-only\b'
    r'|--dry-run\b'
    r'|(?:^|\s)--co(?:\s|$)'  # pytest --co (short for --collect-only)
)


def _detect_verbose_command(command: str) -> tuple[str, str] | None:
    """Match command against verbose patterns.

    Returns (command_family, format_hint) or None.
    """
    for pattern, family, hint in _VERBOSE_PATTERNS:
        if pattern.search(command):
            return family, hint
    return None


def _has_output_management(command: str) -> bool:
    """Check if command already has pipes, redirects, or brick-run."""
    # Don't match | in strings or variable expansions — simple heuristic:
    # strip quoted strings before checking
    stripped = re.sub(r"'[^']*'", "", command)
    stripped = re.sub(r'"[^"]*"', "", stripped)
    return bool(_OUTPUT_MANAGED_RE.search(stripped))


def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    if tool_name != "Bash":
        sys.exit(0)

    command = input_data.get("tool_input", {}).get("command", "")
    if not command:
        sys.exit(0)

    session_id = input_data.get("session_id", "")

    # Check if brick-run binary exists
    if not os.path.isfile(_BRICK_RUN):
        log_enrichment(
            "brick-run-intercept", session_id, "Bash",
            action="skipped", reason="binary_missing",
        )
        sys.exit(0)

    # Check if command matches a verbose pattern
    match = _detect_verbose_command(command)
    if match is None:
        sys.exit(0)

    family, format_hint = match

    # Skip if output is already managed (pipes, redirects, brick-run)
    if _has_output_management(command):
        log_enrichment(
            "brick-run-intercept", session_id, "Bash",
            action="skipped", reason="output_managed",
            command_family=family,
        )
        sys.exit(0)

    # Skip dry-run style commands
    if _DRY_RUN_RE.search(command):
        log_enrichment(
            "brick-run-intercept", session_id, "Bash",
            action="skipped", reason="dry_run",
            command_family=family,
        )
        sys.exit(0)

    # Circuit breaker — if OPEN, let command through normally
    cb = CircuitBreaker()
    if not cb.allow_request():
        log_enrichment(
            "brick-run-intercept", session_id, "Bash",
            action="skipped", reason="circuit_open",
            command_family=family,
        )
        sys.exit(0)

    # Build the brick-run wrapped command
    # Use --shell so brick-run runs via sh -c (handles complex commands)
    # Use --format-hint to help brick-run pick the right parser
    wrapped = f"{_BRICK_RUN} --shell --format-hint {format_hint} -- {command}"

    log_enrichment(
        "brick-run-intercept", session_id, "Bash",
        action="intercepted",
        command_family=family,
        reason=format_hint,
        findings_preview=f"[🧱 Brick intercepted {family} — show this to user] Routing through brick-run",
    )

    # Emit updatedInput to rewrite the command
    print(json.dumps({
        "updatedInput": {
            "command": wrapped
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
