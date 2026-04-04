#!/usr/bin/env python3
"""PostToolUse(Edit) observability hook: records Edit diffs as patch artifacts.

Scope: Edit tool only. Exits 0 for any other tool_name including MultiEdit
(gated until MultiEdit fixture is captured).
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
    update_health,
)

_HOOK_NAME = "obs-posttool-edit"
_EVENT_NAME = "PostToolUse"


def _load_read_state(state_path: str) -> dict[str, Any]:
    try:
        with open(state_path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_read_state(state_path: str, state: dict) -> None:
    try:
        parent = os.path.dirname(state_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp_path = state_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(state, f)
        os.replace(tmp_path, state_path)
    except Exception:
        pass


def _build_patch_from_structured(file_path: str, structured_patch: list) -> tuple[str, int, int]:
    patch_lines = [
        f"--- a/{file_path.lstrip('/')}",
        f"+++ b/{file_path.lstrip('/')}",
    ]
    total_added = 0
    total_removed = 0

    for hunk in structured_patch:
        old_start = hunk.get("oldStart", 0)
        old_lines_count = hunk.get("oldLines", 0)
        new_start = hunk.get("newStart", 0)
        new_lines_count = hunk.get("newLines", 0)
        lines = hunk.get("lines", [])

        patch_lines.append(f"@@ -{old_start},{old_lines_count} +{new_start},{new_lines_count} @@")
        for line in lines:
            if isinstance(line, str):
                if line.startswith("\\"):
                    continue
                patch_lines.append(line)
                if line.startswith("+"):
                    total_added += 1
                elif line.startswith("-"):
                    total_removed += 1

    return "\n".join(patch_lines) + "\n", total_added, total_removed


def _build_patch_from_strings(file_path: str, old_string: str, new_string: str) -> tuple[str, int, int]:
    old_lines = old_string.splitlines() if old_string else []
    new_lines = new_string.splitlines() if new_string else []

    patch_lines = [
        f"--- a/{file_path.lstrip('/')}",
        f"+++ b/{file_path.lstrip('/')}",
        f"@@ -1,{len(old_lines)} +1,{len(new_lines)} @@",
    ]
    for line in old_lines:
        patch_lines.append(f"-{line}")
    for line in new_lines:
        patch_lines.append(f"+{line}")

    return "\n".join(patch_lines) + "\n", len(new_lines), len(old_lines)


def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = input_data.get("session_id")
    if not session_id:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    if tool_name != "Edit":
        sys.exit(0)

    tool_response = input_data.get("tool_response")
    if not isinstance(tool_response, dict):
        sys.exit(0)

    obs_root_override = os.environ.get("OBS_ROOT")
    kwargs: dict = {}
    if obs_root_override:
        kwargs["obs_root"] = obs_root_override

    package_root = resolve_package_root(session_id, **kwargs)
    if package_root is None:
        sys.exit(0)

    tool_input: dict = input_data.get("tool_input", {})
    tool_ref = input_data.get("tool_use_id", "")
    file_path: str = tool_input.get("file_path", "") or tool_response.get("filePath", "")

    structured_patch = tool_response.get("structuredPatch", [])
    if structured_patch and isinstance(structured_patch, list) and len(structured_patch) > 0:
        patch_content, added, removed = _build_patch_from_structured(file_path, structured_patch)
    else:
        old_string = tool_input.get("old_string", "")
        new_string = tool_input.get("new_string", "")
        patch_content, added, removed = _build_patch_from_strings(file_path, old_string, new_string)
        record_error(
            package_root,
            "EDIT_STRUCTURED_PATCH_MISSING",
            "info",
            "patch_capture",
            "build_edit_patch",
            message=f"structuredPatch empty for {file_path}; fell back to old_string/new_string",
        )

    patch_hash = hashlib.sha256(patch_content.encode()).hexdigest()[:16]

    event_data: dict[str, Any] = {
        "tool": "Edit",
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
            package_root, "PATCH_WRITE_FAILED", "warning", "patch_capture",
            "write_patch_file", message=f"Failed to write patch for {file_path}: {exc}",
        )
        update_health(
            package_root, "patch_capture", "degraded",
            warning={"code": "PATCH_WRITE_FAILED"},
        )
        patch_path = os.path.join(write_diffs_dir, patch_filename)

    artifact_id = f"write_diff:{seq}:{tool_use_short}"
    register_artifact(
        package_root, artifact_id,
        artifact_type="write_diff", path=patch_path,
        seq=seq, file_path=file_path, patch_hash=patch_hash,
    )

    state_path = os.path.join(custom_dir, ".read_state.json")
    state = _load_read_state(state_path)
    existing: dict = state.get(file_path, {})
    existing["last_write_seq"] = seq
    state[file_path] = existing
    _save_read_state(state_path, state)

    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
