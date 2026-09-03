#!/usr/bin/env python3
"""E2: the status line names the degraded state instead of rendering nothing.

When the guarded obs_utils import fails, `_OBS_AVAILABLE` is False and no
module ever writes `obs_health`, so `render_obs_health` used to return None --
visually identical to a healthy line. These tests pin the "obs off" pill.

Isolation is deliberate and load-bearing. The renderer runs in a child
interpreter (`-I -B`) with HOME pointed at an empty directory, so an installed
~/.claude/obs_utils.py cannot satisfy the import. The sources are also copied
to a directory with no sibling `hooks/`, because context_overhead.py inserts
`<parent of its own dir>/hooks` into sys.path at import time: pointing the
child straight at a real checkout's `src/` would import obs_utils from the
sibling `hooks/` and never reach the degraded branch at all.

Paths come from the environment so the same file runs against a scratch copy
and against a real qLine checkout:
    QLINE_SRC    statusline source dir   (default: this file's parent's parent,
                                          i.e. src/ when installed at src/tests/)
    QLINE_HOOKS  obs_utils/hook_utils dir (default: <QLINE_SRC>/../hooks)
    QLINE_PYTHON child interpreter        (default: the current test interpreter)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

GLYPH = "\U000f0565"  # nf-md-shield_check, the obs_health glyph
PILL_TEXT = "obs off"
SESSION_ID = "probe-session-e2"
TIMEOUT_S = 60

_HERE = Path(__file__).resolve().parent
SRC = Path(os.environ.get("QLINE_SRC") or _HERE.parent).resolve()
HOOKS = Path(os.environ.get("QLINE_HOOKS") or (SRC.parent / "hooks")).resolve()
PYTHON = os.environ.get("QLINE_PYTHON", sys.executable)

_CHILD_SOURCE = r"""
import json, os, sys

for entry in reversed(json.loads(os.environ["QLINE_TEST_PATHS"])):
    sys.path.insert(0, entry)

import statusline

theme = json.loads(os.environ["QLINE_TEST_THEME"])
state = {}
statusline._inject_obs_counters(state, {"session_id": os.environ["QLINE_TEST_SESSION"]})
pill = statusline.render_obs_health(state, theme)
line = statusline.render(state, theme)
unknown_pill = statusline.render_obs_health({"_has_session_id": True}, theme)
healthy_pill = statusline.render_obs_health({"obs_health": "healthy"}, theme)
sys.stdout.write(json.dumps({
    "obs_available": bool(statusline._OBS_AVAILABLE),
    "healthy_pill": healthy_pill,
    "line": line,
    "pill": pill,
    "state_keys": sorted(state),
    "unknown_pill": unknown_pill,
}))
"""


def _require(paths: list[Path]) -> None:
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        pytest.fail("missing qLine source files: " + ", ".join(missing))


def _isolated_src(tmp_path: Path) -> Path:
    """Copy the statusline sources where no sibling hooks/ dir can be found."""
    _require([SRC / "statusline.py", SRC / "context_overhead.py"])
    src = tmp_path / "isolated-pkg" / "src"
    src.mkdir(parents=True)
    for name in ("statusline.py", "context_overhead.py"):
        shutil.copy2(SRC / name, src / name)
    sibling_hooks = src.parent / "hooks"
    assert not sibling_hooks.exists(), (
        f"isolation broken: {sibling_hooks} exists, so context_overhead would "
        "put obs_utils back on sys.path"
    )
    return src


def _render(tmp_path: Path, paths: list[Path], theme: dict | None = None) -> dict:
    """Render the obs_health module in a child interpreter and return its report."""
    empty_home = tmp_path / "empty-home"
    empty_home.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(empty_home),
        "QLINE_TEST_PATHS": json.dumps([str(p) for p in paths]),
        "QLINE_TEST_SESSION": SESSION_ID,
        "QLINE_TEST_THEME": json.dumps(theme or {}),
        "QLINE_CACHE_PATH": str(tmp_path / "qline-cache.json"),
    }
    proc = subprocess.run(
        [PYTHON, "-I", "-B", "-c", _CHILD_SOURCE],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=TIMEOUT_S,
    )
    if proc.returncode != 0:
        pytest.fail(f"child exited {proc.returncode}; stderr={proc.stderr!r}")
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        pytest.fail(
            f"child stdout was not JSON ({exc}); "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )


def test_obs_unavailable_renders_the_obs_off_pill(tmp_path: Path) -> None:
    report = _render(tmp_path, [_isolated_src(tmp_path)])

    assert report["obs_available"] is False, "obs_utils must be unimportable here"
    assert report["pill"] is not None, "degraded state must not render nothing"
    assert PILL_TEXT in report["pill"]
    assert GLYPH in report["pill"]


def test_obs_unavailable_sets_its_own_flag_not_has_session_id(tmp_path: Path) -> None:
    report = _render(tmp_path, [_isolated_src(tmp_path)])

    assert report["obs_available"] is False
    assert "_obs_unavailable" in report["state_keys"]
    # _has_session_id means "obs is expected here" and is only set once the
    # guarded import succeeded; conflating the two would mislabel the state.
    assert "_has_session_id" not in report["state_keys"]


def test_obs_health_uses_the_configured_glyph_in_every_state(tmp_path: Path) -> None:
    custom_glyph = "CUSTOM"
    report = _render(
        tmp_path,
        [_isolated_src(tmp_path)],
        {"obs_health": {"glyph": f"{custom_glyph} "}},
    )

    for key in ("pill", "unknown_pill", "healthy_pill"):
        assert custom_glyph in report[key]
        assert GLYPH not in report[key]


def test_obs_off_is_dimmed_through_the_default_render_layout(tmp_path: Path) -> None:
    report = _render(tmp_path, [_isolated_src(tmp_path)])

    assert "\033[2m" in report["pill"]
    assert "\033[2m" in report["line"]
    assert PILL_TEXT in report["line"]
    assert GLYPH in report["line"]


def test_positive_control_hooks_on_path_gives_no_obs_off_pill(tmp_path: Path) -> None:
    _require([HOOKS / "obs_utils.py", HOOKS / "hook_utils.py"])

    report = _render(tmp_path, [_isolated_src(tmp_path), HOOKS])

    # Control: the degraded assertions above are caused by the missing modules,
    # not by a renderer that always emits the pill.
    assert report["obs_available"] is True
    assert PILL_TEXT not in (report["pill"] or "")
    assert "_obs_unavailable" not in report["state_keys"]
    assert "_has_session_id" in report["state_keys"]
