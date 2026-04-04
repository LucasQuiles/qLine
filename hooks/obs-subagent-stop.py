#!/usr/bin/env python3
"""SubagentStop observability hook: archives subagent transcript and emits subagent.stopped event."""
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
from hook_utils import read_hook_input, run_fail_open
from obs_utils import (
    resolve_package_root,
    append_event,
    register_artifact,
    update_manifest_array,
    record_error,
    update_health,
)


def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = input_data.get("session_id")
    if not session_id:
        sys.exit(0)

    agent_id = input_data.get("agent_id", "")
    agent_type = input_data.get("agent_type", "")
    agent_transcript_path = input_data.get("agent_transcript_path", "")
    last_assistant_message = input_data.get("last_assistant_message", "")
    message_length = len(last_assistant_message)

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
    # Step 1: Copy subagent transcript if it exists
    # ------------------------------------------------------------------
    dest_path = ""
    if agent_transcript_path and os.path.exists(agent_transcript_path):
        subagents_dir = os.path.join(package_root, "native", "transcripts", "subagents")
        dest_path = os.path.join(subagents_dir, f"{agent_id}.jsonl")
        try:
            os.makedirs(subagents_dir, exist_ok=True)
            shutil.copy2(agent_transcript_path, dest_path)
            register_artifact(
                package_root,
                f"subagent_transcript_{agent_id}",
                artifact_type="subagent_transcript",
                path=dest_path,
                agent_id=agent_id,
                agent_type=agent_type,
                source=agent_transcript_path,
            )
        except OSError as exc:
            record_error(
                package_root,
                "SUBAGENT_TRANSCRIPT_COPY_FAILED",
                "warning",
                "subagent_archive",
                "copy_transcript",
                message=str(exc),
            )
            update_health(package_root, "subagent_archive", "degraded")
            dest_path = ""

    # ------------------------------------------------------------------
    # Step 2: Emit subagent.stopped event
    # ------------------------------------------------------------------
    append_event(
        package_root,
        "subagent.stopped",
        session_id,
        {
            "agent_id": agent_id,
            "agent_type": agent_type,
            "transcript_path": agent_transcript_path,
            "message_length": message_length,
            "archived_path": dest_path,
        },
        origin_type="native_snapshot",
        hook="obs-subagent-stop",
    )

    # ------------------------------------------------------------------
    # Step 3: Update manifest subagents array
    # ------------------------------------------------------------------
    update_manifest_array(
        package_root,
        "subagents",
        {
            "agent_id": agent_id,
            "agent_type": agent_type,
            "transcript_path": agent_transcript_path,
            "archived_path": dest_path,
            "message_length": message_length,
        },
    )

    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, "obs-subagent-stop", "SubagentStop")
