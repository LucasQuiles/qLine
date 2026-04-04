#!/usr/bin/env python3
"""UserPromptSubmit observability hook: records prompt metadata without storing prompt text.

Privacy contract: full prompt text is NEVER written to any file.
Only a truncated hash and length are stored.

Per-call steps:
  1. Read stdin payload via read_hook_input()
  2. Exit 0 if: empty stdin, no session_id
  3. Resolve package_root via resolve_package_root(session_id). Exit 0 if None.
  4. Extract prompt from input_data.get("prompt", "") (top-level field)
  5. Hash the prompt: sha256(prompt)[:16] — do NOT store full prompt text
  6. Compute prompt_length
  7. Detect plan mode: check if prompt contains "/plan", "enterplanmode", "plan mode"
  8. Emit prompt.observed event via append_event()
  9. Exit 0 always. Do NOT write to stdout (no hookSpecificOutput).
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
from hook_utils import read_hook_input, run_fail_open
from obs_utils import resolve_package_root, append_event

_HOOK_NAME = "obs-prompt-submit"
_EVENT_NAME = "UserPromptSubmit"

# Plan-mode trigger phrases (case-insensitive substring match)
_PLAN_TRIGGERS = ("/plan", "enterplanmode", "plan mode")


def _detect_plan_mode(prompt: str) -> bool:
    """Return True if the prompt appears to activate plan mode."""
    lower = prompt.lower()
    return any(trigger in lower for trigger in _PLAN_TRIGGERS)


def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = input_data.get("session_id")
    if not session_id:
        sys.exit(0)

    # Allow tests to override the observability root via env var
    obs_root_override = os.environ.get("OBS_ROOT")
    kwargs: dict = {}
    if obs_root_override:
        kwargs["obs_root"] = obs_root_override

    # Resolve package — if None, session was never packaged; exit silently
    package_root = resolve_package_root(session_id, **kwargs)
    if package_root is None:
        sys.exit(0)

    # ------------------------------------------------------------------
    # Extract prompt from top-level field (proved contract)
    # ------------------------------------------------------------------
    prompt: str = input_data.get("prompt", "")

    # ------------------------------------------------------------------
    # Hash + length — NEVER store the full prompt text
    # ------------------------------------------------------------------
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
    prompt_length = len(prompt)

    # ------------------------------------------------------------------
    # Plan mode heuristic
    # ------------------------------------------------------------------
    plan_mode_active = _detect_plan_mode(prompt)

    # ------------------------------------------------------------------
    # Emit event — no stdout, no hookSpecificOutput
    # ------------------------------------------------------------------
    append_event(
        package_root,
        "prompt.observed",
        session_id,
        {
            "prompt_hash": prompt_hash,
            "prompt_length": prompt_length,
            "plan_mode_active": plan_mode_active,
        },
        origin_type="prompt_hook",
        hook=_HOOK_NAME,
    )

    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
