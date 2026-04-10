#!/usr/bin/env python3
"""UserPromptSubmit observability hook: records prompt metadata without storing prompt text.

Privacy contract: full prompt text is NEVER written to any file.
Only a truncated hash and length are stored.

Per-call steps (preamble handled by run_obs_hook):
  1. Extract prompt from input_data.get("prompt", "") (top-level field)
  2. Hash the prompt: sha256(prompt)[:16] — do NOT store full prompt text
  3. Compute prompt_length
  4. Detect plan mode: check if prompt contains "/plan", "enterplanmode", "plan mode"
  5. Emit prompt.observed event via append_event()
  6. Do NOT write to stdout (no hookSpecificOutput).
"""
from hook_utils import run_fail_open, run_obs_hook, hash16
from obs_utils import append_event

_HOOK_NAME = "obs-prompt-submit"
_EVENT_NAME = "UserPromptSubmit"

# Plan-mode trigger phrases (case-insensitive substring match)
_PLAN_TRIGGERS = ("/plan", "enterplanmode", "plan mode")


def _detect_plan_mode(prompt: str) -> bool:
    """Return True if the prompt appears to activate plan mode."""
    lower = prompt.lower()
    return any(trigger in lower for trigger in _PLAN_TRIGGERS)


def _handle(input_data: dict, session_id: str, package_root: str) -> None:
    # ------------------------------------------------------------------
    # Extract prompt from top-level field (proved contract)
    # ------------------------------------------------------------------
    prompt: str = input_data.get("prompt", "")

    # ------------------------------------------------------------------
    # Hash + length — NEVER store the full prompt text
    # ------------------------------------------------------------------
    prompt_hash = hash16(prompt)
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


if __name__ == "__main__":
    run_fail_open(lambda: run_obs_hook(_handle, _HOOK_NAME, _EVENT_NAME), _HOOK_NAME, _EVENT_NAME)
