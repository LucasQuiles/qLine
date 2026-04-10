#!/usr/bin/env python3
"""PreCompact observability hook: records compaction events to the session package.

PURELY OBSERVATIONAL. Does not output systemMessage or hookSpecificOutput.
The existing precompact-preserve.py handles context injection.

Per-call steps (preamble handled by run_obs_hook):
  1. Compute compact_seq = len(manifest.compactions) + 1.
  2. Emit compact.started event with {trigger, compact_seq}.
  3. Update manifest compactions array with {seq, trigger, timestamp}.
  4. Emit compact.anchor_invalidated event.
"""
from hook_utils import run_fail_open, run_obs_hook
from obs_utils import append_event, update_manifest_array, now_iso, load_manifest


def _handle(input_data: dict, session_id: str, package_root: str) -> None:
    trigger = str(input_data.get("trigger") or "unknown")

    compact_seq = len(load_manifest(package_root).get("compactions", [])) + 1

    # ------------------------------------------------------------------
    # Emit compact.started event to hook_events.jsonl
    # ------------------------------------------------------------------
    append_event(
        package_root,
        "compact.started",
        session_id,
        {
            "trigger": trigger,
            "compact_seq": compact_seq,
        },
        origin_type="native_snapshot",
        hook="obs-precompact",
    )

    # ------------------------------------------------------------------
    # Update manifest compactions array
    # ------------------------------------------------------------------
    update_manifest_array(
        package_root,
        "compactions",
        {
            "seq": compact_seq,
            "trigger": trigger,
            "timestamp": now_iso(),
        },
    )

    # ------------------------------------------------------------------
    # Emit anchor invalidation event (compaction breaks the turn-1 anchor)
    # ------------------------------------------------------------------
    append_event(
        package_root,
        "compact.anchor_invalidated",
        session_id,
        {
            "trigger": trigger,
            "compact_seq": compact_seq,
        },
        origin_type="native_snapshot",
        hook="obs-precompact",
    )


if __name__ == "__main__":
    run_fail_open(lambda: run_obs_hook(_handle, "obs-precompact", "PreCompact"), "obs-precompact", "PreCompact")
