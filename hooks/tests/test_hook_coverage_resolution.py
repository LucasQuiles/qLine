#!/usr/bin/env python3
"""Path-safe resolution contract for the SessionStart hook inventory."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "qline_obs_session_start_resolution", HOOKS / "obs-session-start.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def module():
    return _load_module()


def _script(path: Path, mode: int = 0o700) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    path.chmod(mode)
    return path


def test_resolves_quoted_and_controlled_variable_paths(module, tmp_path: Path) -> None:
    hooks = tmp_path / "plugin" / "hooks"
    script = _script(hooks / "obs quoted.py")
    env = {"CLAUDE_PLUGIN_ROOT": str(tmp_path / "plugin"), "HOME": str(tmp_path)}

    quoted = module._resolve_hook_command(f'python3 "{script}"', str(hooks), env)
    variable = module._resolve_hook_command(
        'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/obs quoted.py"', str(hooks), env
    )

    assert quoted == {"state": "resolved", "path": str(script.resolve())}
    assert variable == quoted


def test_prefix_confusion_and_symlink_escape_are_outside_root(module, tmp_path: Path) -> None:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    prefix_evil = _script(tmp_path / "hooks-evil" / "obs-bad.py")
    outside = _script(tmp_path / "outside" / "obs-outside.py")
    link = hooks / "obs-link.py"
    link.symlink_to(outside)

    assert module._resolve_hook_command(str(prefix_evil), str(hooks))["state"] == "outside_root"
    assert module._resolve_hook_command(str(link), str(hooks))["state"] == "outside_root"


def test_missing_unreadable_and_ambiguous_commands_have_closed_states(
    module, tmp_path: Path
) -> None:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    unreadable = _script(hooks / "obs-unreadable.py", 0o000)
    one = _script(hooks / "obs-one.py")
    two = _script(hooks / "obs-two.py")

    assert module._resolve_hook_command(str(hooks / "obs-missing.py"), str(hooks))["state"] == "missing"
    assert module._resolve_hook_command(str(unreadable), str(hooks))["state"] == "unreadable"
    assert module._resolve_hook_command(f"python3 {one} {two}", str(hooks))["state"] == "ambiguous"
    assert module._resolve_hook_command("python3 'unterminated", str(hooks))["state"] == "ambiguous"
    assert module._resolve_hook_command(f"bash -lc 'python3 {one}'", str(hooks))["state"] == "ambiguous"
    assert module._resolve_hook_command("python3 $UNCONTROLLED/obs.py", str(hooks))["state"] == "ambiguous"


def test_inventory_records_each_resolution_state(module, tmp_path: Path, monkeypatch) -> None:
    hooks = tmp_path / "plugin" / "hooks"
    good = _script(hooks / "obs-good.py")
    _script(hooks / "obs-expected-only.py")
    module.__file__ = str(hooks / "obs-session-start.py")

    settings = {
        "enabledPlugins": {},
        "hooks": {
            "PreToolUse": [
                {
                    "hooks": [
                        {"command": f'python3 "{good}"'},
                        {"command": str(hooks / "obs-missing.py")},
                        {"command": "echo no-script"},
                    ]
                }
            ]
        },
    }
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    monkeypatch.setenv("OBS_INVENTORY_SETTINGS_PATH", str(settings_path))
    package_root = tmp_path / "package"
    (package_root / "metadata").mkdir(parents=True)

    module._scan_inventory(str(package_root), str(tmp_path))

    inventory = json.loads(
        (package_root / "metadata" / "session_inventory.json").read_text()
    )
    coverage = inventory["hook_coverage"]
    assert coverage["registered"] == [str(good.resolve())]
    assert {row["state"] for row in coverage["resolutions"]} == {
        "resolved",
        "missing",
        "ambiguous",
    }
    assert all("command" not in row for row in coverage["resolutions"])
