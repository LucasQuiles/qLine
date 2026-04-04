#!/usr/bin/env python3
"""PreCompact observability hook: records compaction events to the session package.

PURELY OBSERVATIONAL. Does not output systemMessage or hookSpecificOutput.
The existing precompact-preserve.py handles context injection.

Steps:
  1. Read stdin; exit 0 if empty or no session_id.
  2. Resolve package_root via runtime map; exit 0 if unknown session.
  3. Compute compact_seq = len(manifest.compactions) + 1.
  4. Emit compact.started event with {trigger, compact_seq}.
  5. Update manifest compactions array with {seq, trigger, timestamp}.
  6. Exit 0 always (fail-open).
"""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
from hook_utils import read_hook_input, run_fail_open
from obs_utils import resolve_package_root, append_event, update_manifest_array, _now_iso


def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = input_data.get("session_id")
    if not session_id:
        sys.exit(0)

    trigger = str(input_data.get("trigger") or "unknown")

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
    # Compute compact_seq from existing compactions in the manifest
    # ------------------------------------------------------------------
    manifest_path = os.path.join(package_root, "manifest.json")
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
        compact_seq = len(manifest.get("compactions", [])) + 1
    except Exception:
        compact_seq = 1

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
            "timestamp": _now_iso(),
        },
    )

    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, "obs-precompact", "PreCompact")
