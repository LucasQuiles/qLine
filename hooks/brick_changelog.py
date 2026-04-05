"""Artifact changelog — semantic log of file changes with Brick analysis.

Records every code file change with: what changed, why (from Brick analysis),
when, and which session. Enables queries like "why did auth.py change?" without
reading full session transcripts.

Append-only JSONL at ~/.local/share/brick-lab/artifact-changelog.jsonl
"""
import json
import os
import time
from pathlib import Path

CHANGELOG_PATH = Path(
    os.environ.get(
        "BRICK_CHANGELOG_PATH",
        os.path.expanduser("~/.local/share/brick-lab/artifact-changelog.jsonl"),
    )
)


def log_artifact_change(
    session_id: str,
    tool_name: str,
    file_path: str,
    lines_changed: int,
    brick_findings: str = "",
    cwd: str = "",
) -> None:
    """Log a code file change with Brick's analysis. Never raises."""
    try:
        CHANGELOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Extract repo name from file path or cwd
        repo = ""
        for part in (cwd or file_path).split("/"):
            if part and part not in ("home", "q", "LAB", "tmp", "src", ""):
                repo = part
                break

        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "session_id": session_id,
            "tool": tool_name,
            "file_path": file_path,
            "lines_changed": lines_changed,
            "repo": repo,
            "module": os.path.basename(file_path),
            "brick_summary": brick_findings[:500] if brick_findings else "",
            "cwd": cwd,
        }

        with open(CHANGELOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Never fail the hook for changelog
