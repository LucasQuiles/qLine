from __future__ import annotations

import importlib.util
import fcntl
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
VERIFY_PATH = ROOT / "scripts" / "verify.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "verify.yml"
CONTRIBUTING_PATH = ROOT / "CONTRIBUTING.md"
PULL_REQUEST_TEMPLATE_PATH = ROOT / ".github" / "pull_request_template.md"


@pytest.fixture(scope="module")
def verifier():
    spec = importlib.util.spec_from_file_location("qline_verify", VERIFY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return path


def _success(verifier, stdout: str = "ok\n"):
    def run(spec, command, timeout_seconds, cwd):
        del spec, command, timeout_seconds, cwd
        return verifier.RunResult(exit_code=0, stdout=stdout, stderr="", duration_ms=3)

    return run


def _invoke(verifier, capsys, argv, *, repo=None, runner=None):
    rc = verifier.main(argv, repo=repo, runner=runner or _success(verifier))
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _forbid_doctor_checks(*args, **kwargs):
    raise AssertionError(f"doctor invoked a check: {args!r} {kwargs!r}")


def test_schema_json_is_self_contained_and_does_not_run_checks(verifier, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError(f"schema invoked a check: {args!r} {kwargs!r}")

    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        ["schema", "--format", "json"],
        runner=forbidden,
    )

    assert rc == 0
    assert stderr == ""
    report = json.loads(stdout)
    assert report["schema_version"] == verifier.SCHEMA_VERSION
    assert report["verdict"] == "pass"
    assert [check["name"] for check in report["checks"]] == [
        "python-ast",
        "ruff",
        "shellcheck",
        "pytest",
        "shell-regression",
        "git-diff",
        "test-integrity",
        "base-diff",
        "install-regression",
    ]
    assert report["report_schema"]["required"] == [
        "schema_version",
        "verdict",
        "summary",
        "checks",
        "effects",
        "elapsed_ms",
    ]
    assert report["report_schema_scope"] == ["doctor", "run"]


def test_parser_constructs_with_one_fields_option_per_command(verifier):
    parser = verifier._parser()
    subparsers_action = next(
        action
        for action in parser._actions
        if isinstance(action, verifier.argparse._SubParsersAction)
    )

    assert sorted(subparsers_action.choices) == ["doctor", "run", "schema"]
    for subparser in subparsers_action.choices.values():
        fields_actions = [
            action for action in subparser._actions if "--fields" in action.option_strings
        ]
        assert len(fields_actions) == 1
        assert fields_actions[0].option_strings == ["--fields"]


def test_schema_text_is_deterministic_and_separate_from_stderr(verifier, capsys):
    first = _invoke(verifier, capsys, ["schema"])
    second = _invoke(verifier, capsys, ["schema"])

    assert first == second
    assert first[0] == 0
    assert first[2] == ""
    assert first[1].startswith("qLine verifier schema")
    assert not first[1].lstrip().startswith("{")


def test_schema_can_discover_one_check(verifier, capsys):
    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        ["schema", "ruff", "--format", "json"],
    )

    assert rc == 0
    assert stderr == ""
    report = json.loads(stdout)
    assert [item["name"] for item in report["checks"]] == ["ruff"]
    assert report["checks"][0]["code"] == "QLV-002"
    assert report["checks"][0]["effects"]["read_only"] is True


def test_json_projection_retains_identity_fields(verifier, repo, capsys):
    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        [
            "run",
            "--format",
            "json",
            "--check",
            "python-ast",
            "--fields",
            "summary,effects",
        ],
        repo=repo,
    )

    assert rc == 0
    assert stderr == ""
    report = json.loads(stdout)
    assert list(report) == ["schema_version", "verdict", "summary", "effects"]


def test_unknown_check_is_invalid_cli_use(verifier, capsys):
    with pytest.raises(SystemExit) as raised:
        verifier.main(["run", "--check", "not-a-check"])

    captured = capsys.readouterr()
    assert raised.value.code == 2
    assert captured.out == ""
    assert "invalid choice" in captured.err


def test_missing_prerequisite_is_structured_blocked_exit_2(
    verifier, repo, capsys, monkeypatch
):
    real_which = verifier.shutil.which

    def without_shellcheck(name):
        return None if name == "shellcheck" else real_which(name)

    monkeypatch.setattr(verifier.shutil, "which", without_shellcheck)
    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        ["run", "--format", "json", "--check", "shellcheck"],
        repo=repo,
    )

    assert rc == 2
    assert stderr == ""
    report = json.loads(stdout)
    assert report["verdict"] == "blocked"
    check = report["checks"][0]
    assert check["status"] == "blocked"
    assert check["error"] == {
        "kind": "prerequisite_missing",
        "message": "Required tool 'shellcheck' is unavailable.",
        "hint": "Install ShellCheck and rerun the same command.",
        "retryable": True,
        "details": {"prerequisite": "shellcheck"},
    }


def test_timeout_is_inconclusive_and_never_collapses_to_check_failure(
    verifier, repo, capsys
):
    def timeout(spec, command, timeout_seconds, cwd):
        del spec, cwd
        raise subprocess.TimeoutExpired(command, timeout_seconds)

    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        [
            "run",
            "--format",
            "json",
            "--check",
            "git-diff",
            "--timeout-seconds",
            "0.25",
        ],
        repo=repo,
        runner=timeout,
    )

    assert rc == 2
    assert stderr == ""
    check = json.loads(stdout)["checks"][0]
    assert check["status"] == "blocked"
    assert check["exit_code"] is None
    assert check["error"]["kind"] == "check_timeout"
    assert check["error"]["retryable"] is True
    assert check["error"]["details"]["timeout_seconds"] == 0.25


def test_timeout_retains_partial_diagnostics_and_private_logs(
    verifier, repo, tmp_path, capsys
):
    def timeout(spec, command, timeout_seconds, cwd):
        del spec, cwd
        raise subprocess.TimeoutExpired(
            command,
            timeout_seconds,
            output=b"partial stdout\n",
            stderr=b"partial stderr\n",
        )

    log_dir = tmp_path / "timeout-logs"
    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        [
            "run",
            "--format",
            "json",
            "--verbose",
            "--check",
            "git-diff",
            "--timeout-seconds",
            "0.25",
            "--log-dir",
            str(log_dir),
        ],
        repo=repo,
        runner=timeout,
    )

    assert rc == 2
    assert stderr == ""
    check = json.loads(stdout)["checks"][0]
    assert check["status"] == "blocked"
    assert check["stdout"]["text"] == "partial stdout\n"
    assert check["stderr"]["text"] == "partial stderr\n"
    assert check["stdout_summary"] == "partial stdout"
    assert check["stderr_summary"] == "partial stderr"
    assert (log_dir / "QLV-006-git-diff.stdout.log").read_bytes() == b"partial stdout\n"
    assert (log_dir / "QLV-006-git-diff.stderr.log").read_bytes() == b"partial stderr\n"


def test_unexpected_runner_exception_is_structured_internal_exit_2(
    verifier, repo, capsys
):
    def crash(spec, command, timeout_seconds, cwd):
        del spec, command, timeout_seconds, cwd
        raise RuntimeError("synthetic runner defect")

    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        ["run", "--format", "json", "--check", "git-diff"],
        repo=repo,
        runner=crash,
    )

    assert rc == 2
    assert stderr == ""
    check = json.loads(stdout)["checks"][0]
    assert check["status"] == "blocked"
    assert check["error"]["kind"] == "internal_error"
    assert check["error"]["retryable"] is False
    assert check["error"]["details"]["exception"] == "RuntimeError"


def test_malformed_runner_result_is_structured_internal_exit_2(
    verifier, repo, capsys
):
    def malformed(spec, command, timeout_seconds, cwd):
        del spec, command, timeout_seconds, cwd
        return {"exit_code": 0}

    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        ["run", "--format", "json", "--check", "git-diff"],
        repo=repo,
        runner=malformed,
    )

    assert rc == 2
    assert stderr == ""
    check = json.loads(stdout)["checks"][0]
    assert check["status"] == "blocked"
    assert check["error"]["kind"] == "internal_error"
    assert check["error"]["details"]["exception"] == "TypeError"


def test_unexpected_tool_exit_is_blocked_not_failed(verifier, repo, capsys):
    def exit_two(spec, command, timeout_seconds, cwd):
        del spec, command, timeout_seconds, cwd
        return verifier.RunResult(2, "partial\n", "tool error\n", 2)

    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        ["run", "--format", "json", "--verbose", "--check", "ruff"],
        repo=repo,
        runner=exit_two,
    )

    assert rc == 2
    assert stderr == ""
    check = json.loads(stdout)["checks"][0]
    assert check["status"] == "blocked"
    assert check["error"]["kind"] == "unexpected_check_exit"
    assert check["stdout"]["text"] == "partial\n"
    assert check["stderr"]["text"] == "tool error\n"


def test_verbose_blocked_check_still_has_bounded_stream_contract(
    verifier, repo, capsys, monkeypatch
):
    real_which = verifier.shutil.which
    monkeypatch.setattr(
        verifier.shutil,
        "which",
        lambda name: None if name == "shellcheck" else real_which(name),
    )

    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        ["run", "--format", "json", "--verbose", "--check", "shellcheck"],
        repo=repo,
    )

    assert rc == 2
    assert stderr == ""
    check = json.loads(stdout)["checks"][0]
    assert check["stdout"] == {
        "text": "",
        "bytes": 0,
        "truncated": False,
        "omitted_bytes": 0,
    }
    assert check["stderr"] == check["stdout"]


def test_completed_failing_check_is_reported_on_stdout_with_exit_1(
    verifier, repo, capsys
):
    def fail(spec, command, timeout_seconds, cwd):
        del spec, command, timeout_seconds, cwd
        return verifier.RunResult(
            exit_code=1,
            stdout="",
            stderr="F401 unused import\n",
            duration_ms=8,
        )

    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        ["run", "--format", "json", "--check", "ruff"],
        repo=repo,
        runner=fail,
    )

    assert rc == 1
    assert stderr == ""
    report = json.loads(stdout)
    assert report["verdict"] == "fail"
    check = report["checks"][0]
    assert check["status"] == "fail"
    assert check["exit_code"] == 1
    assert check["error"]["kind"] == "lint_failed"
    assert "F401" in check["stderr_summary"]
    assert "stderr" not in check


def test_full_success_uses_registry_order_and_never_recurses(
    verifier, repo, capsys
):
    calls = []

    def succeed(spec, command, timeout_seconds, cwd):
        calls.append((spec.name, command, timeout_seconds, cwd))
        return verifier.RunResult(0, f"{spec.name} ok\n", "", 1)

    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        [
            "run",
            "--format",
            "json",
            "--check",
            "pytest",
            "--check",
            "python-ast",
            "--check",
            "ruff",
        ],
        repo=repo,
        runner=succeed,
    )

    assert rc == 0
    assert stderr == ""
    assert [item[0] for item in calls] == ["python-ast", "ruff", "pytest"]
    pytest_command = next(command for name, command, *_ in calls if name == "pytest")
    assert pytest_command[-4:] == (
        "hooks/tests",
        "src/tests",
        "scripts/tests",
        "-q",
    )
    assert "run" not in pytest_command
    assert json.loads(stdout)["summary"] == {
        "blocked": 0,
        "failed": 0,
        "passed": 3,
        "selected": 3,
    }


def test_shell_regression_is_pinned_to_the_verifier_interpreter(
    verifier, repo
):
    spec = next(item for item in verifier.CHECKS if item.name == "shell-regression")
    result = verifier._subprocess_runner(
        spec,
        (
            sys.executable,
            "-c",
            "import os; print(os.environ.get('QLINE_TEST_PYTHON', ''))",
        ),
        10.0,
        repo,
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == verifier.sys.executable
    harness = (ROOT / "tests" / "test-statusline.sh").read_text(encoding="utf-8")
    assert 'QLINE_TEST_PYTHON' in harness
    assert 'FATAL: QLINE_TEST_PYTHON must name Python 3.10+' in harness


def test_shell_harness_interpreter_override_has_precedence_and_fails_closed(
    tmp_path
):
    marker = tmp_path / "ambient-python-used"
    fake_python = tmp_path / "python3.13"
    fake_python.write_text(
        f"#!/bin/sh\ntouch {marker}\nexit 99\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o700)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "QLINE_TEST_PYTHON": sys.executable,
    }

    preferred = subprocess.run(
        ["bash", str(ROOT / "tests" / "test-statusline.sh"), "--section", "none"],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert preferred.returncode == 0
    assert "=== Results: 0/0 passed, 0 failed ===" in preferred.stdout
    assert not marker.exists()

    invalid = subprocess.run(
        ["bash", str(ROOT / "tests" / "test-statusline.sh"), "--section", "none"],
        capture_output=True,
        text=True,
        check=False,
        env={**environment, "QLINE_TEST_PYTHON": str(tmp_path / "missing")},
    )
    assert invalid.returncode == 1
    assert invalid.stdout == ""
    assert "FATAL: QLINE_TEST_PYTHON must name Python 3.10+" in invalid.stderr


def test_verbose_output_is_bounded_with_truncation_metadata(
    verifier, repo, capsys
):
    payload = "x" * (verifier.MAX_STREAM_BYTES + 41)

    def noisy(spec, command, timeout_seconds, cwd):
        del spec, command, timeout_seconds, cwd
        return verifier.RunResult(0, payload, payload, 1)

    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        ["run", "--format", "json", "--verbose", "--check", "git-diff"],
        repo=repo,
        runner=noisy,
    )

    assert rc == 0
    assert stderr == ""
    check = json.loads(stdout)["checks"][0]
    for stream in (check["stdout"], check["stderr"]):
            assert stream["truncated"] is True
            assert stream["bytes"] == len(payload)
            assert stream["omitted_bytes"] >= 41
            assert "output omitted" in stream["text"]
            assert len(stream["text"].encode()) <= verifier.MAX_STREAM_BYTES


def test_bounded_stream_and_summary_retain_head_and_tail(verifier):
    payload = "first-line\n" + ("middle\n" * 10_000) + "last-line\n"

    stream = verifier._stream(payload)
    summary = verifier._summary(payload)

    assert stream["truncated"] is True
    assert stream["text"].startswith("first-line\n")
    assert stream["text"].endswith("last-line\n")
    assert "omitted" in stream["text"]
    assert "first-line" in summary and "last-line" in summary


def test_subprocess_timeout_reaps_descendants(verifier, repo, tmp_path):
    lock_path = tmp_path / "descendant.lock"
    child = (
        "import fcntl,time; "
        f"handle=open({str(lock_path)!r},'w'); "
        "fcntl.flock(handle, fcntl.LOCK_EX); "
        "print('child-ready', flush=True); "
        "time.sleep(60)"
    )
    parent = (
        "import subprocess,sys,time; "
        f"child=subprocess.Popen([sys.executable, '-c', {child!r}], "
        "stdout=subprocess.PIPE, text=True); "
        "print(child.stdout.readline().strip(), flush=True); "
        "print('parent-ready', flush=True); time.sleep(60)"
    )
    spec = next(item for item in verifier.CHECKS if item.name == "git-diff")

    with pytest.raises(verifier.CheckTimeout) as raised:
        verifier._subprocess_runner(
            spec, (sys.executable, "-c", parent), 0.1, repo
        )

    assert "child-ready" in raised.value.result.stdout
    assert "parent-ready" in raised.value.result.stdout
    with lock_path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(handle, fcntl.LOCK_UN)


def test_subprocess_output_ceiling_is_blocked_and_bounded(
    verifier, repo, monkeypatch
):
    monkeypatch.setattr(verifier, "MAX_PROCESS_OUTPUT_BYTES", 1024)
    script = "import sys,time; sys.stdout.write('x' * 8192); sys.stdout.flush(); time.sleep(60)"
    spec = next(item for item in verifier.CHECKS if item.name == "git-diff")

    with pytest.raises(verifier.OutputLimitExceeded) as raised:
        verifier._subprocess_runner(
            spec, (sys.executable, "-c", script), 5.0, repo
        )

    assert raised.value.result.stdout_bytes > 1024
    assert len(raised.value.result.stdout.encode("utf-8")) <= verifier.MAX_STREAM_BYTES


def test_output_limit_persists_retained_logs_when_requested(
    verifier, repo, tmp_path, capsys
) -> None:
    log_dir = tmp_path / "logs"
    result = verifier.RunResult(
        exit_code=2,
        stdout="bounded stdout\n",
        stderr="bounded stderr\n",
        duration_ms=4,
        stdout_bytes=8192,
        stderr_bytes=4096,
        stdout_omitted_bytes=8177,
        stderr_omitted_bytes=4081,
    )

    def output_limited(*_args):
        raise verifier.OutputLimitExceeded(result)

    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        [
            "run",
            "--format",
            "json",
            "--check",
            "ruff",
            "--log-dir",
            str(log_dir),
        ],
        repo=repo,
        runner=output_limited,
    )

    assert rc == 2
    assert stderr == ""
    assert json.loads(stdout)["checks"][0]["error"]["kind"] == "output_limit_exceeded"
    assert (log_dir / "QLV-002-ruff.stdout.log").read_text() == result.stdout
    assert (log_dir / "QLV-002-ruff.stderr.log").read_text() == result.stderr


def test_subprocess_spawn_failure_is_not_misclassified_as_capture_failure(
    verifier, repo, monkeypatch
) -> None:
    spec = next(item for item in verifier.CHECKS if item.name == "git-diff")

    def cannot_spawn(*_args, **_kwargs):
        raise FileNotFoundError("synthetic executable vanished")

    monkeypatch.setattr(verifier.subprocess, "Popen", cannot_spawn)
    with pytest.raises(verifier.CheckExecutionFailed) as raised:
        verifier._subprocess_runner(spec, ("vanished",), 1.0, repo)

    assert "FileNotFoundError" in raised.value.result.stderr


def test_log_dir_is_the_only_write_effect_and_uses_private_modes(
    verifier, repo, tmp_path, capsys
):
    log_dir = tmp_path / "logs"
    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        [
            "run",
            "--format",
            "json",
            "--check",
            "ruff",
            "--log-dir",
            str(log_dir),
        ],
        repo=repo,
        runner=_success(verifier, "ruff clean\n"),
    )

    assert rc == 0
    assert stderr == ""
    report = json.loads(stdout)
    assert report["effects"] == {
        "destructive": False,
        "idempotent": False,
        "network": False,
        "read_only": False,
        "writes": [str(log_dir.resolve())],
    }
    assert stat.S_IMODE(log_dir.stat().st_mode) == 0o700
    assert (log_dir / "QLV-002-ruff.stdout.log").read_text() == "ruff clean\n"
    assert (log_dir / "QLV-002-ruff.stderr.log").read_text() == ""
    json.loads((log_dir / "report.json").read_text())
    for path in log_dir.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_nonempty_log_dir_is_blocked_and_stale_files_survive_unchanged(
    verifier, repo, tmp_path, capsys
):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    stale_report = log_dir / "report.json"
    stale_check = log_dir / "QLV-002-ruff.stdout.log"
    stale_report.write_text('{"stale": true}\n', encoding="utf-8")
    stale_check.write_text("old output\n", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in log_dir.iterdir()}

    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        [
            "run",
            "--format",
            "json",
            "--check",
            "ruff",
            "--log-dir",
            str(log_dir),
        ],
        repo=repo,
    )

    assert rc == 2
    assert stderr == ""
    assert {path.name: path.read_bytes() for path in log_dir.iterdir()} == before
    error = json.loads(stdout)["checks"][0]["error"]
    assert error["kind"] == "log_destination_not_fresh"
    assert error["details"]["path"] == str(log_dir)


def test_report_persistence_failure_preserves_observed_log_write_effect(
    verifier, repo, tmp_path, capsys, monkeypatch
):
    log_dir = tmp_path / "logs"
    real_write_private = verifier._write_private

    def fail_report(path, content):
        if path.name == "report.json":
            raise OSError("synthetic report failure")
        real_write_private(path, content)

    monkeypatch.setattr(verifier, "_write_private", fail_report)
    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        [
            "run",
            "--format",
            "json",
            "--check",
            "ruff",
            "--log-dir",
            str(log_dir),
        ],
        repo=repo,
        runner=_success(verifier),
    )

    assert rc == 2
    assert stderr == ""
    report = json.loads(stdout)
    assert report["checks"][0]["error"]["kind"] == "log_write_failed"
    assert report["effects"] == {
        "destructive": False,
        "idempotent": False,
        "network": False,
        "read_only": False,
        "writes": [str(log_dir.resolve())],
    }


def test_symlink_log_dir_is_refused_without_writing_target(
    verifier, repo, tmp_path, capsys
):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "logs"
    link.symlink_to(target, target_is_directory=True)

    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        [
            "run",
            "--format",
            "json",
            "--check",
            "git-diff",
            "--log-dir",
            str(link),
        ],
        repo=repo,
    )

    assert rc == 2
    assert stderr == ""
    assert list(target.iterdir()) == []
    error = json.loads(stdout)["checks"][0]["error"]
    assert error["kind"] == "log_write_failed"


def test_without_log_dir_run_is_read_only(verifier, repo, capsys):
    before = sorted(path.relative_to(repo) for path in repo.rglob("*"))
    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        ["run", "--format", "json", "--check", "git-diff"],
        repo=repo,
    )
    after = sorted(path.relative_to(repo) for path in repo.rglob("*"))

    assert rc == 0
    assert stderr == ""
    assert before == after
    assert json.loads(stdout)["effects"]["read_only"] is True
    assert json.loads(stdout)["effects"]["idempotent"] is True


def test_unreadable_tracked_shell_entrypoint_blocks_before_shellcheck(
    verifier, repo, capsys
):
    shell = repo / "missing.sh"
    shell.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "add", "missing.sh"],
        check=True,
        capture_output=True,
        text=True,
    )
    shell.unlink()

    def forbidden(*args, **kwargs):
        raise AssertionError(f"unreadable input still invoked ShellCheck: {args!r} {kwargs!r}")

    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        ["run", "--format", "json", "--check", "shellcheck"],
        repo=repo,
        runner=forbidden,
    )

    assert rc == 2
    assert stderr == ""
    check = json.loads(stdout)["checks"][0]
    assert check["status"] == "blocked"
    assert check["error"]["kind"] == "check_execution_error"
    assert "missing.sh" in check["error"]["details"]["message"]


def test_unreadable_or_missing_repo_is_structured_exit_2(
    verifier, tmp_path, capsys
):
    missing = tmp_path / "missing"
    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        ["run", "--format", "json", "--check", "git-diff"],
        repo=missing,
    )

    assert rc == 2
    assert stderr == ""
    report = json.loads(stdout)
    assert report["verdict"] == "blocked"
    assert report["checks"][0]["code"] == "QLV-000"
    assert report["checks"][0]["error"]["kind"] == "repository_unreadable"


def test_doctor_reports_prerequisites_without_running_checks(
    verifier, repo, capsys
):
    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        ["doctor", "--format", "json", "--check", "python-ast"],
        repo=repo,
        runner=_forbid_doctor_checks,
    )

    assert rc == 0
    assert stderr == ""
    check = json.loads(stdout)["checks"][0]
    assert check["status"] == "pass"
    assert check["implementation"] == "builtin:tracked-python-ast"
    assert check["prerequisites"] == ["git", "python>=3.10"]


def test_verbose_doctor_reports_bounded_structured_prerequisite_evidence(
    verifier, repo, capsys
):
    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        ["doctor", "--format", "json", "--verbose", "--check", "python-ast"],
        repo=repo,
        runner=_forbid_doctor_checks,
    )

    assert rc == 0
    assert stderr == ""
    report = json.loads(stdout)
    verifier._validate_report(report)
    evidence = report["checks"][0]["diagnostics"]["prerequisites"]
    assert [item["prerequisite"] for item in evidence] == ["git", "python>=3.10"]
    assert [item["kind"] for item in evidence] == ["executable", "interpreter"]
    assert all(item["available"] is True for item in evidence)
    assert all(item["path"] for item in evidence)
    assert evidence[1]["version"] == ".".join(
        str(part) for part in verifier.sys.version_info[:3]
    )
    assert set(evidence[0]) == {
        "prerequisite",
        "kind",
        "available",
        "path",
        "version",
    }
    assert "environ" not in json.dumps(report).lower()


def test_every_check_has_stable_typed_effect_and_error_metadata(verifier):
    assert len(verifier.CHECKS) == len({spec.name for spec in verifier.CHECKS})
    assert len(verifier.CHECKS) == len({spec.code for spec in verifier.CHECKS})
    assert all(spec.code.startswith("QLV-") for spec in verifier.CHECKS)
    assert all(spec.severity == "error" for spec in verifier.CHECKS)
    assert all(spec.effects.read_only for spec in verifier.CHECKS)
    assert all(not spec.effects.network for spec in verifier.CHECKS)
    assert all(spec.error_kind in verifier.ERROR_KINDS for spec in verifier.CHECKS)


def test_shellcheck_and_test_integrity_are_full_fail_closed_checks(verifier):
    shellcheck = next(spec for spec in verifier.CHECKS if spec.name == "shellcheck")
    integrity = next(spec for spec in verifier.CHECKS if spec.name == "test-integrity")

    assert shellcheck.command == ("{shellcheck}", "{tracked-shell-entrypoints}")
    assert integrity.code == "QLV-007"
    assert integrity.error_kind == "test_integrity_failed"
    assert integrity.command == ("{python}", "{verify}", "_test_integrity")


def test_registry_covers_committed_range_and_installer_regression(verifier):
    base_diff = next(spec for spec in verifier.CHECKS if spec.name == "base-diff")
    installer = next(
        spec for spec in verifier.CHECKS if spec.name == "install-regression"
    )

    assert base_diff.code == "QLV-008"
    assert base_diff.error_kind == "base_diff_failed"
    assert base_diff.command == ("{python}", "{verify}", "_base_diff")
    assert installer.code == "QLV-009"
    assert installer.error_kind == "install_regression_failed"
    assert installer.command == ("{bash}", "tests/test-install-core.sh")


def test_test_integrity_finds_python_sleep_and_assertion_free_test(verifier, repo):
    tests = repo / "tests"
    tests.mkdir()
    unsafe = tests / "test_unsafe.py"
    unsafe.write_text(
        "import time\n\n"
        "def test_waits_for_time():\n"
        "    time.sleep(0.01)\n\n"
        "def test_only_calls_a_helper():\n"
        "    helper()\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "-C", str(repo), "add", "tests/test_unsafe.py"],
        check=True,
        capture_output=True,
        text=True,
    )

    findings = verifier._test_integrity_findings(repo)

    assert [(item["kind"], item["line"]) for item in findings] == [
        ("python_sleep_in_test", 3),
        ("python_test_without_assertion", 3),
        ("python_test_without_assertion", 6),
    ]


def test_base_diff_child_checks_the_committed_range(verifier, repo, capsys):
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test User"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    tracked = repo / "tracked.txt"
    tracked.write_text("clean\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--quiet", "-m", "base"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "branch", "-M", "main"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "switch", "--quiet", "-c", "feature"],
        check=True,
    )
    tracked.write_text("trailing whitespace   \n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--quiet", "-m", "feature"], check=True
    )

    rc = verifier._base_diff_child(repo, base_ref="main")

    captured = capsys.readouterr()
    assert rc == 1
    assert "trailing whitespace" in captured.out


def test_base_diff_child_fails_closed_when_base_is_missing(verifier, repo, capsys):
    rc = verifier._base_diff_child(repo, base_ref="refs/remotes/origin/missing")

    captured = capsys.readouterr()
    assert rc == 2
    assert "base ref is unavailable" in captured.out


def test_test_integrity_finds_masked_python_stderr_and_pipeline_exit(
    verifier, repo
):
    tests = repo / "tests"
    tests.mkdir()
    unsafe = tests / "unsafe.sh"
    unsafe.write_text(
        "#!/bin/bash\n"
        'RESULT=$("$PYTHON" -c "raise SystemExit(1)" 2>/dev/null)\n'
        'printf "%s" x | "$PYTHON" script.py\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "-C", str(repo), "add", "tests/unsafe.sh"],
        check=True,
        capture_output=True,
        text=True,
    )

    findings = verifier._test_integrity_findings(repo)

    assert [(item["kind"], item["line"]) for item in findings] == [
        ("python_stderr_discarded", 2),
        ("pipeline_without_pipefail", 3),
    ]


def test_test_integrity_capability_probe_allowlist_cannot_be_spoofed(
    verifier, repo
):
    tests = repo / "tests"
    tests.mkdir()
    unsafe = tests / "spoofed.sh"
    unsafe.write_text(
        "#!/bin/bash\n"
        'RESULT=$("$PYTHON" script.py 2>/dev/null) # command -v tool\n'
        'OTHER=$("$PYTHON" script.py 2>/dev/null) # version_info _candidate\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "-C", str(repo), "add", "tests/spoofed.sh"],
        check=True,
        capture_output=True,
        text=True,
    )

    findings = verifier._test_integrity_findings(repo)

    assert [(item["kind"], item["line"]) for item in findings] == [
        ("python_stderr_discarded", 2),
        ("python_stderr_discarded", 3),
    ]


def test_shell_harness_retains_diagnostics_and_t_obs_9_exit_is_not_vacuous(
    verifier
):
    harness = (ROOT / "tests" / "test-statusline.sh").read_text(encoding="utf-8")

    assert verifier._test_integrity_findings(ROOT) == []
    assert "TEST_DIAGNOSTIC_LOG=" in harness
    assert "show_diagnostics" in harness
    assert "OUTPUT_9_EXIT=$?" in harness
    assert harness.index("OUTPUT_9_EXIT=$?") < harness.index(
        'assert_exit_zero "T-obs-9: exits 0 when obs fails" "$OUTPUT_9_EXIT"'
    )


def test_internal_validator_checks_nested_published_report_contract(
    verifier, repo, capsys
):
    rc, stdout, stderr = _invoke(
        verifier,
        capsys,
        ["run", "--format", "json", "--verbose", "--check", "ruff"],
        repo=repo,
    )

    assert rc == 0
    assert stderr == ""
    report = json.loads(stdout)
    verifier._validate_report(report)
    assert verifier.REPORT_SCHEMA["properties"]["checks"]["items"]["required"]

    report["summary"]["passed"] = 0
    with pytest.raises(ValueError, match="summary counts"):
        verifier._validate_report(report)


def test_scripts_do_not_import_or_execute_the_gate_recursively(verifier):
    pytest_spec = next(spec for spec in verifier.CHECKS if spec.name == "pytest")
    assert pytest_spec.command == (
        "{python}",
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "hooks/tests",
        "src/tests",
        "scripts/tests",
        "-q",
    )
    assert "verify.py" not in " ".join(pytest_spec.command)


def test_verifier_is_executable_and_ci_uses_the_same_pinned_entrypoint():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert VERIFY_PATH.stat().st_mode & stat.S_IXUSR
    assert "permissions:\n  contents: read\n" in workflow
    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert '          - "3.10"' in workflow
    assert '          - "3.12"' in workflow
    assert (
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1"
        in workflow
    )
    assert (
        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0"
        in workflow
    )
    assert "fetch-depth: 0" in workflow
    assert 'test "$actual_shellcheck" = "0.11.0"' in workflow
    assert "pip install --disable-pip-version-check --require-hashes -r requirements-dev.lock" in workflow
    assert "python scripts/verify.py doctor --verbose" in workflow
    assert (
        "python scripts/verify.py run --timeout-seconds 600 "
        '--log-dir "${{ runner.temp }}/qline-verify-${{ matrix.python-version }}"'
        in workflow
    )
    uses = re.findall(r"^\s*uses:\s*([^\s#]+)", workflow, flags=re.MULTILINE)
    assert uses
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", action) for action in uses)
    assert "upload-artifact" not in workflow
    assert 'cat "$report"' not in workflow
    assert "stdout_summary" not in workflow
    assert "GITHUB_STEP_SUMMARY" in workflow
    assert 'print(f"::error title={title}::{body}")' in workflow
    assert 'print(f"::warning title={title}::{body}")' in workflow
    assert "gate_exit=$?" in workflow
    assert 'exit "$gate_exit"' in workflow
    assert "Verification report missing or invalid" in workflow
    assert "exit 2" in workflow
    assert (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines() == [
        "pytest==8.4.2",
        "ruff==0.15.10",
    ]
    lock = (ROOT / "requirements-dev.lock").read_text(encoding="utf-8")
    assert "pytest==8.4.2" in lock and "ruff==0.15.10" in lock
    assert lock.count("--hash=sha256:") >= 4


def test_durable_adoption_docs_require_unmasked_canonical_verification():
    contributing = CONTRIBUTING_PATH.read_text(encoding="utf-8")
    template = PULL_REQUEST_TEMPLATE_PATH.read_text(encoding="utf-8")
    verification = (ROOT / "docs" / "VERIFICATION.md").read_text(encoding="utf-8")

    for document in (contributing, template):
        assert "scripts/verify.py" in document
        assert "masked" in document.lower()
        assert "docs/VERIFICATION.md" in document
    assert "doctor" in contributing
    assert "--check" in contributing
    assert "--format json" in contributing
    assert "--verbose" in contributing
    assert "--log-dir" in contributing
    assert "effect" in template.lower()
    assert "does not print the JSON report or its stream summaries" in verification
    assert "public repository" in verification
