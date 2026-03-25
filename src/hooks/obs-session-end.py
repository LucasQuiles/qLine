#!/opt/homebrew/bin/python3.12
"""SessionEnd observability hook: finalizes session package and emits session.ended event.

Critical constraint: must complete within ~1.5s (CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS).
All I/O is bounded: symlink (not copy), line-count only for event ledger, no heavy analysis.
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
from hook_utils import read_hook_input, run_fail_open
from obs_utils import (
    resolve_package_root,
    append_event,
    update_manifest,
    update_health,
    register_artifact,
    record_error,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _count_lines(path: str) -> int:
    """Fast line count via raw read — avoids JSON parsing overhead."""
    try:
        with open(path, "rb") as f:
            return f.read().count(b"\n")
    except OSError:
        return 0


def _load_manifest(package_root: str) -> dict:
    """Load manifest.json, returning {} on any error."""
    manifest_path = os.path.join(package_root, "manifest.json")
    try:
        with open(manifest_path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def validate_finalization(package_root: str) -> tuple[str, list[str]]:
    """Returns (final_status, warnings_or_errors_list).

    Tier 0 failures → 'failed' or 'incomplete'
    Tier 1 degraded subsystems → 'finalized_with_warnings'
    All clear → 'finalized'
    """
    # Tier 0: manifest exists and is valid
    manifest_path = os.path.join(package_root, "manifest.json")
    if not os.path.exists(manifest_path):
        return ("failed", ["Manifest does not exist"])

    manifest = _load_manifest(package_root)
    errors: list[str] = []

    # Tier 0: session_id present
    if not manifest.get("session_id"):
        errors.append("Session identity missing")

    # Tier 0: event ledger exists
    ledger_path = os.path.join(package_root, "metadata", "hook_events.jsonl")
    if not os.path.exists(ledger_path):
        errors.append("Event ledger does not exist")

    # Tier 0: transcript linkage
    if not manifest.get("native_links", {}).get("transcript_origin"):
        errors.append("Transcript linkage missing")

    if errors:
        return ("incomplete", errors)

    # Tier 1: check subsystem health
    health = manifest.get("health", {}).get("subsystems", {})
    has_degraded = any(v == "degraded" for v in health.values())

    if has_degraded:
        warnings = [k for k, v in health.items() if v == "degraded"]
        return ("finalized_with_warnings", warnings)

    return ("finalized", [])


def generate_session_summary(package_root: str, session_id: str, end_reason: str) -> dict:
    """Quick summary — must complete in <200ms.

    Uses fast line count for event_count; reads manifest for structured fields.
    """
    manifest = _load_manifest(package_root)

    ledger_path = os.path.join(package_root, "metadata", "hook_events.jsonl")
    event_count = _count_lines(ledger_path)

    return {
        "session_id": session_id,
        "started_at": manifest.get("created_at"),
        "ended_at": _now_iso(),
        "end_reason": end_reason,
        "cwd": manifest.get("cwd") or manifest.get("source_map", {}).get("cwd"),
        "event_count": event_count,
        "task_count": len(manifest.get("tasks", [])),
        "subagent_count": len(manifest.get("subagents", [])),
        "compaction_count": len(manifest.get("compactions", [])),
        "patch_count": manifest.get("patches", {}).get("count", 0),
    }


def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = input_data.get("session_id")
    if not session_id:
        sys.exit(0)

    transcript_path = input_data.get("transcript_path", "")
    end_reason = input_data.get("reason", "unknown")

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
    # Step 1: Symlink main transcript (NOT copy — too slow for 1.5s cap)
    # ------------------------------------------------------------------
    manifest = _load_manifest(package_root)
    transcript_origin = manifest.get("native_links", {}).get("transcript_origin") or transcript_path

    if transcript_origin:
        transcripts_dir = os.path.join(package_root, "native", "transcripts")
        symlink_path = os.path.join(transcripts_dir, "main.jsonl")
        try:
            os.makedirs(transcripts_dir, exist_ok=True)
            if os.path.islink(symlink_path):
                os.unlink(symlink_path)
            os.symlink(transcript_origin, symlink_path)
        except OSError as exc:
            record_error(
                package_root, "SYMLINK_FAILED", "warning", "transcript_linkage",
                "create_symlink", message=str(exc),
            )

        # Register artifact
        register_artifact(
            package_root,
            "transcript_main_symlink",
            artifact_type="transcript_symlink",
            path=symlink_path,
            notes="symlink_only:pending_archive_copy",
            origin=transcript_origin,
        )

    # ------------------------------------------------------------------
    # Step 2: Run finalization validator
    # ------------------------------------------------------------------
    final_status, validator_items = validate_finalization(package_root)

    # ------------------------------------------------------------------
    # Step 3: Update manifest — ended_at, end_reason, status
    # ------------------------------------------------------------------
    manifest_updates: dict = {
        "ended_at": _now_iso(),
        "end_reason": end_reason,
        "status": final_status,
    }
    if validator_items:
        manifest_updates["finalization_notes"] = validator_items
    update_manifest(package_root, manifest_updates)

    # ------------------------------------------------------------------
    # Step 4: Recompute overall health (derived_analysis now available)
    # ------------------------------------------------------------------
    update_health(package_root, "derived_analysis", "healthy")

    # ------------------------------------------------------------------
    # Step 5: Emit session.ended event
    # ------------------------------------------------------------------
    append_event(
        package_root,
        "session.ended",
        session_id,
        {
            "end_reason": end_reason,
            "final_status": final_status,
            "transcript_origin": transcript_origin,
        },
        origin_type="native_snapshot",
        hook="obs-session-end",
    )

    # ------------------------------------------------------------------
    # Step 6: Generate derived/session_summary.json (fast, bounded)
    # ------------------------------------------------------------------
    derived_dir = os.path.join(package_root, "derived")
    try:
        os.makedirs(derived_dir, exist_ok=True)
        summary = generate_session_summary(package_root, session_id, end_reason)
        summary_path = os.path.join(derived_dir, "session_summary.json")
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
    except OSError as exc:
        record_error(
            package_root, "SUMMARY_WRITE_FAILED", "warning", "derived_analysis",
            "write_session_summary", message=str(exc),
        )

    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, "obs-session-end", "SessionEnd")
