#!/usr/bin/env python3
"""Compatibility matrix for package manifests and new JSONL sidecars."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

import hook_utils  # noqa: E402
import obs_utils  # noqa: E402


@pytest.mark.parametrize(
    ("value", "normalized", "state"),
    [
        (None, "1.0.0", "legacy"),
        ("1.0.0", "1.0.0", "supported"),
        ("1.1.0", "1.1.0", "current"),
        ("1.9.4", "1.9.4", "supported"),
        ("2.0.0", "2.0.0", "unsupported_major"),
        (1, "", "invalid"),
        ("bogus", "", "invalid"),
    ],
)
def test_manifest_schema_compatibility_matrix(value, normalized, state) -> None:
    manifest = {} if value is None else {"schema_version": value}
    assert obs_utils.classify_manifest_schema(manifest) == {
        "version": normalized,
        "state": state,
    }


def test_create_package_writes_current_additive_schema(tmp_path: Path) -> None:
    package = Path(
        obs_utils.create_package(
            "schema-current", "/tmp", "/tmp/t.jsonl", "test", obs_root=str(tmp_path)
        )
    )
    manifest = json.loads((package / "manifest.json").read_text())
    assert manifest["schema_version"] == obs_utils.MANIFEST_SCHEMA_VERSION == "1.1.0"
    assert obs_utils.load_manifest(str(package))["session_id"] == "schema-current"


def test_load_manifest_accepts_missing_and_v1_but_rejects_unknown_major(
    tmp_path: Path,
) -> None:
    package = tmp_path / "package"
    package.mkdir()
    path = package / "manifest.json"
    for manifest in (
        {"health": {"overall": "legacy"}},
        {"schema_version": "1.0.0", "health": {"overall": "old"}},
        {"schema_version": "1.1.0", "health": {"overall": "current"}},
    ):
        path.write_text(json.dumps(manifest), encoding="utf-8")
        assert obs_utils.load_manifest(str(package))["health"] == manifest["health"]

    path.write_text(json.dumps({"schema_version": "2.0.0", "secret": "future"}))
    assert obs_utils.load_manifest(str(package)) == {}


def test_manifest_mutators_do_not_overwrite_an_unknown_major_schema(
    tmp_path: Path,
) -> None:
    package = tmp_path / "package"
    package.mkdir()
    path = package / "manifest.json"
    original = b'{"schema_version":"2.0.0","future":{"opaque":true}}\n'
    mutations = (
        lambda: obs_utils.update_manifest(str(package), {"status": "changed"}),
        lambda: obs_utils.update_manifest_array(str(package), "items", {"id": 1}),
        lambda: obs_utils.update_manifest_if_absent_batch(
            str(package), "gate", {"gate": True}
        ),
        lambda: obs_utils.update_health(str(package), "hook_ledger", "degraded"),
    )

    for mutate in mutations:
        path.write_bytes(original)
        obs_utils._health_cache.clear()
        mutate()
        assert path.read_bytes() == original


def test_hook_perf_rows_declare_schema_producer_and_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = "perf-schema"
    package = Path(
        obs_utils.create_package(
            session_id, "/tmp", "/tmp/t.jsonl", "test", obs_root=str(tmp_path)
        )
    )
    monkeypatch.setenv("OBS_ROOT", str(tmp_path))
    obs_utils._package_root_cache.clear()

    hook_utils._write_hook_perf(session_id, "obs-test", "Stop", 12.34)

    row = json.loads((package / "metadata" / "hook_perf.jsonl").read_text())
    assert row["schema_version"] == hook_utils.HOOK_PERF_SCHEMA_VERSION == "1.0.0"
    assert row["producer"] == "hook_utils"
    assert row["code"] == "hook_duration"
