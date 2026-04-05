#!/usr/bin/env python3
"""PostToolUse(Write) observability hook: records file writes as patch artifacts.

Scope: Write tool only. Exits 0 immediately for any other tool_name.

Per-call steps:
  1. Read stdin payload via read_hook_input()
  2. Exit 0 if: empty stdin, no session_id, tool_name != "Write"
  3. Resolve package_root via resolve_package_root(session_id). Exit 0 if None.
  4. Extract file_path and content from tool_input
  5. Compute line count: added = len(content.splitlines()), removed = 0
  6. Build patch content (unified-diff-like, first 100 lines)
  7. Emit file.write.diff event via append_event() — returns seq
  8. Name patch file: custom/write_diffs/<seq>-<tool_use_id[:12]>.patch
  9. Write patch file to disk
  10. Register artifact via register_artifact()
  11. Update custom/.read_state.json with last_write_seq for this file
  12. Exit 0 always
"""
import hashlib
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
from hook_utils import read_hook_input, run_fail_open
from obs_utils import (
    resolve_package_root,
    append_event,
    register_artifact,
    record_error,
    _load_read_state,
    _save_read_state,
)

_HOOK_NAME = "obs-posttool-write"
_EVENT_NAME = "PostToolUse"
_MAX_PATCH_LINES = 100


def _build_patch(file_path: str, content: str) -> str:
    """Build a unified-diff-like patch string for a Write (full replacement).

    Format:
        --- /dev/null
        +++ b/<relative_path>
        @@ new file @@
        +<content first 100 lines>
        +... (N more lines)
    """
    # Use the basename for the +++ line to keep it readable
    # but include full path as reference
    lines = content.splitlines() if content else []
    shown = lines[:_MAX_PATCH_LINES]
    remaining = len(lines) - len(shown)

    patch_lines = [
        "--- /dev/null",
        f"+++ b/{file_path.lstrip('/')}",
        "@@ new file @@",
    ]
    for line in shown:
        patch_lines.append(f"+{line}")
    if remaining > 0:
        patch_lines.append(f"+... ({remaining} more lines)")

    return "\n".join(patch_lines) + "\n"


def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = input_data.get("session_id")
    if not session_id:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    if tool_name != "Write":
        sys.exit(0)

    # Log to action ledger for decision tree tracing (no Brick call)
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from brick_action_ledger import log_action, derive_action_id
        _ti = input_data.get("tool_input", {})
        _action_id = derive_action_id(input_data)
        log_action(session_id, "Write", file_path=_ti.get("file_path", ""),
                   lines=len(_ti.get("content", "").splitlines()),
                   cwd=input_data.get("cwd", ""), action_id=_action_id)
    except Exception:
        pass

    # Guard: tool_response must be a dict to confirm successful write.
    # Missing or non-dict tool_response = malformed or failed payload — skip.
    tool_response = input_data.get("tool_response")
    if not isinstance(tool_response, dict):
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
    # Step 1: Extract tool_input fields
    # ------------------------------------------------------------------
    tool_input: dict = input_data.get("tool_input", {})
    tool_ref = input_data.get("tool_use_id", "")
    file_path: str = tool_input.get("file_path", "")
    content: str = tool_input.get("content", "")

    # ------------------------------------------------------------------
    # Step 2: Compute line counts
    #   added  = number of lines in new content
    #   removed = 0 (Write is full replacement — no diff against prior content)
    # ------------------------------------------------------------------
    added = len(content.splitlines()) if content else 0
    removed = 0

    # ------------------------------------------------------------------
    # Step 3: Build patch content
    # ------------------------------------------------------------------
    patch_content = _build_patch(file_path, content)
    patch_hash = hashlib.sha256(patch_content.encode()).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Step 4: Emit file.write.diff event to event ledger
    # ------------------------------------------------------------------
    event_data: dict[str, Any] = {
        "tool": tool_name,
        "tool_ref": tool_ref,
        "path": file_path,
        "added": added,
        "removed": removed,
        "patch_hash": patch_hash,
    }

    seq = append_event(
        package_root,
        "file.write.diff",
        session_id,
        event_data,
        origin_type="posttool_hook",
        hook=_HOOK_NAME,
    )

    # ------------------------------------------------------------------
    # Step 5: Write patch file to disk
    #   custom/write_diffs/<seq>-<tool_use_id[:12]>.patch
    # ------------------------------------------------------------------
    tool_use_short = tool_ref[:12] if tool_ref else "unknown"
    patch_filename = f"{seq}-{tool_use_short}.patch"
    custom_dir = os.path.join(package_root, "custom")
    write_diffs_dir = os.path.join(custom_dir, "write_diffs")

    try:
        os.makedirs(write_diffs_dir, exist_ok=True)
        patch_path = os.path.join(write_diffs_dir, patch_filename)
        with open(patch_path, "w") as f:
            f.write(patch_content)
    except Exception as exc:
        record_error(
            package_root,
            "PATCH_WRITE_FAILED",
            "warning",
            "patch_capture",
            "write_patch_file",
            message=f"Failed to write patch for {file_path}: {exc}",
        )
        patch_path = os.path.join(write_diffs_dir, patch_filename)  # best-effort path

    # ------------------------------------------------------------------
    # Step 6: Register artifact in artifact_index.jsonl
    # ------------------------------------------------------------------
    artifact_id = f"write_diff:{seq}:{tool_use_short}"
    register_artifact(
        package_root,
        artifact_id,
        artifact_type="write_diff",
        path=patch_path,
        seq=seq,
        file_path=file_path,
        patch_hash=patch_hash,
    )

    # ------------------------------------------------------------------
    # Step 7: Update read_state sidecar with last_write_seq
    # ------------------------------------------------------------------
    state_path = os.path.join(custom_dir, ".read_state.json")
    state = _load_read_state(state_path)

    # Preserve any existing entry (e.g., read_count, last_read_seq)
    existing: dict = state.get(file_path, {})
    existing["last_write_seq"] = seq
    state[file_path] = existing
    _save_read_state(state_path, state)

    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
