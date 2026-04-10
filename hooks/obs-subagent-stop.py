#!/usr/bin/env python3
"""SubagentStop observability hook: archives subagent transcript and emits subagent.stopped event."""
import os
import shutil

from hook_utils import run_fail_open, run_obs_hook
from obs_utils import (
    append_event,
    register_artifact,
    update_manifest_array,
    record_error,
    update_health,
)


def _handle(input_data: dict, session_id: str, package_root: str) -> None:
    agent_id = input_data.get("agent_id", "")
    agent_type = input_data.get("agent_type", "")
    agent_transcript_path = input_data.get("agent_transcript_path", "")
    last_assistant_message = input_data.get("last_assistant_message", "")
    message_length = len(last_assistant_message)

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


if __name__ == "__main__":
    run_fail_open(lambda: run_obs_hook(_handle, "obs-subagent-stop", "SubagentStop"), "obs-subagent-stop", "SubagentStop")
