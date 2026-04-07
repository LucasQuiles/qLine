#!/usr/bin/env python3
"""SessionStart observability hook: creates session package and publishes runtime mapping."""
import json
import os
import sys
from datetime import datetime, timezone

from hook_utils import read_hook_input, run_fail_open, _now_iso
from obs_utils import create_package, append_event, resolve_package_root_env, update_health, record_error


def _file_stats(path: str) -> dict | None:
    """Return {path, lines, bytes, mtime} for a file, or None if missing/unreadable."""
    try:
        stat = os.stat(path)
        with open(path) as f:
            lines = sum(1 for _ in f)
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        return {"path": path, "lines": lines, "bytes": stat.st_size, "mtime": mtime}
    except (OSError, ValueError):
        return None


def _scan_inventory(package_root: str, cwd: str) -> None:
    """Scan Claude runtime environment and write metadata/session_inventory.json.

    Tier 2: caller must wrap in try/except — any failure here must not block the package.
    Supports OBS_INVENTORY_SETTINGS_PATH env override for testing.
    """
    home = os.path.expanduser("~")
    claude_dir = os.path.join(home, ".claude")

    # --- CLAUDE.md paths ---
    def _md_section(filename: str) -> dict:
        return {
            "global": _file_stats(os.path.join(claude_dir, filename)),
            "project": _file_stats(os.path.join(cwd, ".claude", filename)) if cwd else None,
            "local": _file_stats(os.path.join(cwd, ".claude", filename.replace(".md", ".local.md"))) if cwd else None,
        }

    claude_md = _md_section("CLAUDE.md")
    agents_md = _md_section("AGENTS.md")

    # --- settings.json ---
    settings_path = os.environ.get(
        "OBS_INVENTORY_SETTINGS_PATH",
        os.path.join(claude_dir, "settings.json"),
    )
    settings_stat = os.stat(settings_path)
    settings_mtime = datetime.fromtimestamp(settings_stat.st_mtime, tz=timezone.utc).isoformat()
    settings_info: dict = {
        "path": settings_path,
        "bytes": settings_stat.st_size,
        "mtime": settings_mtime,
    }

    # --- plugins + hooks from settings.json ---
    with open(settings_path) as f:
        settings = json.load(f)

    enabled_plugins = settings.get("enabledPlugins", {})
    total_enabled = sum(1 for v in enabled_plugins.values() if v is True)
    total_disabled = sum(1 for v in enabled_plugins.values() if v is False)
    plugin_list = [
        {
            "name": key.split("@")[0] if "@" in key else key,
            "marketplace": key.split("@")[1] if "@" in key else "",
            "enabled": bool(val),
        }
        for key, val in enabled_plugins.items()
    ]

    hooks_cfg = settings.get("hooks", {})
    by_event: dict[str, int] = {}
    for event, entries in hooks_cfg.items():
        if isinstance(entries, list):
            # Count actual hook commands, not matcher blocks
            count = 0
            for entry in entries:
                hooks_list = entry.get("hooks", []) if isinstance(entry, dict) else []
                count += len(hooks_list)
            by_event[event] = count
    total_hooks = sum(by_event.values())

    # --- Assemble and write ---
    inventory = {
        "captured_at": _now_iso(),
        "claude_md": claude_md,
        "agents_md": agents_md,
        "plugins": {
            "total_enabled": total_enabled,
            "total_disabled": total_disabled,
            "list": plugin_list,
        },
        "hooks": {
            "total": total_hooks,
            "by_event": by_event,
        },
        "settings_json": settings_info,
    }

    inventory_path = os.path.join(package_root, "metadata", "session_inventory.json")
    with open(inventory_path, "w") as f:
        json.dump(inventory, f, indent=2)


def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = input_data.get("session_id")
    if not session_id:
        sys.exit(0)  # No identity — cannot create package

    transcript_path = input_data.get("transcript_path", "")
    cwd = input_data.get("cwd", "")
    source = input_data.get("source", "unknown")

    # Handle re-entry: package already exists (any source, including repeated startup)
    existing = resolve_package_root_env(session_id)
    if existing:
        append_event(
            existing,
            "session.reentry",
            session_id,
            {"source": source},
            origin_type="native_snapshot",
            hook="obs-session-start",
        )
        sys.exit(0)

    # Create new package (Tier 0 — raises OSError on failure)
    try:
        obs_root_override = os.environ.get("OBS_ROOT")
        cp_kwargs: dict = {"obs_root": obs_root_override} if obs_root_override else {}
        package_root = create_package(session_id, cwd, transcript_path, source, **cp_kwargs)
    except Exception as exc:
        print(f"[obs-session-start] Tier 0 failure: {exc}", file=sys.stderr)
        sys.exit(0)  # fail open for Claude

    # Write transcript origin-path.txt
    origin_dir = os.path.join(package_root, "native", "transcripts")
    try:
        os.makedirs(origin_dir, exist_ok=True)
        with open(os.path.join(origin_dir, "origin-path.txt"), "w") as f:
            f.write(transcript_path + "\n")
    except OSError:
        pass  # Non-critical; package itself already exists

    # Emit session.started event
    append_event(
        package_root,
        "session.started",
        session_id,
        {
            "cwd": cwd,
            "source": source,
            "transcript_path": transcript_path,
            "package_root": package_root,
        },
        origin_type="native_snapshot",
        hook="obs-session-start",
    )

    # Mark core packaging healthy in health model
    update_health(package_root, "core_packaging", "healthy")

    # CLAUDE_ENV_FILE export (SessionStart-scoped; other SessionStart hooks in the same
    # event batch can read OBS_PACKAGE_ROOT, but NO subsequent event hooks will see it)
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        try:
            with open(env_file, "a") as f:
                f.write(f"\nexport OBS_PACKAGE_ROOT='{package_root}'\n")
                f.write(f"export OBS_SESSION_ID='{session_id}'\n")
        except OSError:
            pass  # Non-critical; runtime mapping is the real cross-hook contract

    # Tier 2: session inventory (non-blocking but diagnosable)
    try:
        _scan_inventory(package_root, cwd)
    except Exception as exc:
        # Tier 2 failure: record error and degrade, but never block package creation
        record_error(
            package_root, "INVENTORY_SCAN_FAILED", "warning", "session_inventory",
            "scan_inventory", message=str(exc),
        )
        update_health(package_root, "session_inventory", "degraded",
                     warning={"code": "INVENTORY_SCAN_FAILED", "message": str(exc)})

    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, "obs-session-start", "SessionStart")
