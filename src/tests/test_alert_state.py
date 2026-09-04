#!/usr/bin/env python3
"""Security and lifecycle contract for persisted alert onset state."""

from __future__ import annotations

import json
import os
import stat
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import statusline  # noqa: E402


def _use_alert_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "alert-state"
    monkeypatch.setattr(statusline, "ALERT_STATE_DIR", str(root))
    return root


def test_alert_path_is_session_scoped_without_disclosing_the_session_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _use_alert_dir(monkeypatch, tmp_path)

    alpha = statusline._alert_state_path("session/alpha")
    beta = statusline._alert_state_path("session/beta")

    assert alpha is not None and beta is not None
    assert alpha.parent == root
    assert beta.parent == root
    assert alpha != beta
    assert "session" not in alpha.name
    assert alpha.name.startswith("alert-")
    assert len(alpha.stem.removeprefix("alert-")) == 64
    assert statusline._alert_state_path("") is None


def test_alert_write_is_atomic_private_and_round_trips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _use_alert_dir(monkeypatch, tmp_path)
    payload = {"key": "bust", "onset": 123.5, "session_id": "alpha"}

    assert statusline._write_alert_state("alpha", payload) is True
    path = statusline._alert_state_path("alpha")
    assert path is not None
    assert statusline._load_alert_state("alpha") == payload
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(root.glob(".alert-*.tmp"))


def test_alert_state_refuses_symlink_root_and_symlink_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target_dir = tmp_path / "target-dir"
    target_dir.mkdir()
    root_link = tmp_path / "root-link"
    root_link.symlink_to(target_dir, target_is_directory=True)
    monkeypatch.setattr(statusline, "ALERT_STATE_DIR", str(root_link))
    assert statusline._write_alert_state("alpha", {"key": "bust"}) is False
    assert list(target_dir.iterdir()) == []

    root = _use_alert_dir(monkeypatch, tmp_path)
    root.mkdir(mode=0o700)
    victim = tmp_path / "victim.json"
    victim.write_text("do-not-touch", encoding="utf-8")
    path = statusline._alert_state_path("alpha")
    assert path is not None
    path.symlink_to(victim)

    assert statusline._load_alert_state("alpha") == {}
    assert statusline._write_alert_state("alpha", {"key": "bust"}) is False
    assert statusline._clear_alert_state("alpha") is False
    assert victim.read_text(encoding="utf-8") == "do-not-touch"
    assert path.is_symlink()


def test_concurrent_alert_writes_never_leave_partial_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_alert_dir(monkeypatch, tmp_path)

    def write(i: int) -> bool:
        return statusline._write_alert_state(
            "shared-session",
            {"key": "bust", "onset": float(i), "session_id": "shared-session"},
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(write, range(64)))

    assert all(results)
    loaded = statusline._load_alert_state("shared-session")
    assert loaded["key"] == "bust"
    assert loaded["session_id"] == "shared-session"
    assert isinstance(loaded["onset"], float)


def test_clear_unlinks_only_the_current_session_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_alert_dir(monkeypatch, tmp_path)
    assert statusline._write_alert_state("alpha", {"key": "bust"})
    assert statusline._write_alert_state("beta", {"key": "heavy"})
    alpha = statusline._alert_state_path("alpha")
    beta = statusline._alert_state_path("beta")
    assert alpha is not None and beta is not None

    assert statusline._clear_alert_state("alpha") is True
    assert not alpha.exists()
    assert beta.exists()
    assert statusline._load_alert_state("beta") == {"key": "heavy"}
    assert statusline._clear_alert_state("alpha") is True


def test_cleanup_is_bounded_and_ignores_fresh_files_and_symlinks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _use_alert_dir(monkeypatch, tmp_path)
    root.mkdir(mode=0o700)
    stale_time = time.time() - statusline.ALERT_STATE_MAX_AGE_S - 60
    for i in range(statusline.ALERT_STATE_CLEANUP_LIMIT + 5):
        path = root / f"alert-{i:064x}.json"
        path.write_text("{}", encoding="utf-8")
        path.chmod(0o600)
        os.utime(path, (stale_time, stale_time))
    fresh = root / f"alert-{'f' * 64}.json"
    fresh.write_text("{}", encoding="utf-8")
    fresh.chmod(0o600)
    victim = tmp_path / "cleanup-victim"
    victim.write_text("keep", encoding="utf-8")
    link = root / f"alert-{'e' * 64}.json"
    link.symlink_to(victim)

    deleted = statusline._cleanup_alert_state(now=time.time())

    assert deleted == statusline.ALERT_STATE_CLEANUP_LIMIT
    assert fresh.exists()
    assert link.is_symlink()
    assert victim.read_text(encoding="utf-8") == "keep"
    assert sum(1 for p in root.iterdir() if not p.is_symlink()) == 6


def test_render_persists_and_clears_only_its_hashed_alert_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_alert_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(statusline, "NO_COLOR", True)
    session_id = "render-session"
    alert = {
        "context_used": 200_000,
        "context_total": 1_000_000,
        "cache_busting": True,
        "_session_id": session_id,
    }

    rendered = statusline.render_context_bar(alert, statusline.DEFAULT_THEME)
    path = statusline._alert_state_path(session_id)
    assert rendered is not None and "\u26a0" in rendered
    assert path is not None and path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["session_id"] == session_id

    normal = {
        "context_used": 100_000,
        "context_total": 1_000_000,
        "_session_id": session_id,
    }
    statusline.render_context_bar(normal, statusline.DEFAULT_THEME)
    assert not path.exists()
