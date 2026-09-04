#!/usr/bin/env python3
"""Canonical, fail-closed verification entrypoint for qLine.

Exit 0 means every selected check completed and passed. Exit 1 means every
selected check completed, with at least one actionable failure. Exit 2 means
verification was blocked or inconclusive (missing prerequisite, timeout,
unreadable repository, log failure, or an unexpected check exit).

Completed reports, including failures, are written to stdout. The process
keeps stderr empty so JSON output remains a single machine-readable document.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Callable, Iterable, Sequence


SCHEMA_VERSION = "qline.verify.v1"
MAX_STREAM_BYTES = 32_768
MAX_PROCESS_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_SUMMARY_CHARS = 600
DEFAULT_TIMEOUT_SECONDS = 300.0
PROCESS_POLL_SECONDS = 0.02
PROCESS_REAP_SECONDS = 0.5

ERROR_KINDS = frozenset(
    {
        "ast_parse_failed",
        "base_diff_failed",
        "check_execution_error",
        "check_timeout",
        "diff_check_failed",
        "internal_error",
        "install_regression_failed",
        "lint_failed",
        "log_destination_not_fresh",
        "log_write_failed",
        "output_capture_failed",
        "output_limit_exceeded",
        "prerequisite_missing",
        "process_group_reap_failed",
        "python_tests_failed",
        "repository_unreadable",
        "shell_lint_failed",
        "shell_regression_failed",
        "test_integrity_failed",
        "unexpected_check_exit",
    }
)

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@dataclass(frozen=True)
class Effects:
    read_only: bool = True
    destructive: bool = False
    idempotent: bool = True
    network: bool = False


@dataclass(frozen=True)
class CheckSpec:
    name: str
    code: str
    purpose: str
    severity: str
    error_kind: str
    failure_hint: str
    command: tuple[str, ...]
    implementation: str
    prerequisites: tuple[str, ...]
    effects: Effects = Effects()


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    stdout_bytes: int | None = None
    stderr_bytes: int | None = None
    stdout_omitted_bytes: int = 0
    stderr_omitted_bytes: int = 0


class InterruptedCheck(RuntimeError):
    """A bounded runner interruption with diagnostics preserved in ``result``."""

    def __init__(self, result: RunResult):
        super().__init__(type(self).__name__)
        self.result = result


class CheckTimeout(InterruptedCheck):
    """The process group exceeded its deadline and was reaped."""


class OutputLimitExceeded(InterruptedCheck):
    """The process group exceeded its combined output ceiling and was reaped."""


class ProcessGroupReapFailed(InterruptedCheck):
    """The runner could not prove the interrupted process group was reaped."""


class OutputCaptureFailed(InterruptedCheck):
    """The private file-backed output capture could not be created or read."""


class CheckExecutionFailed(InterruptedCheck):
    """The check process could not be started after capture was established."""


CHECKS = (
    CheckSpec(
        name="python-ast",
        code="QLV-001",
        purpose="Parse every tracked Python source with the running interpreter.",
        severity="error",
        error_kind="ast_parse_failed",
        failure_hint="Fix the reported Python syntax error and rerun the gate.",
        command=("{python}", "{verify}", "_python_ast"),
        implementation="builtin:tracked-python-ast",
        prerequisites=("git", "python>=3.10"),
    ),
    CheckSpec(
        name="ruff",
        code="QLV-002",
        purpose="Run the repository's deterministic Python lint ratchet without cache.",
        severity="error",
        error_kind="lint_failed",
        failure_hint="Resolve every reported Ruff finding; do not mask or cache the run.",
        command=("{python}", "-m", "ruff", "check", "--no-cache", "."),
        implementation="subprocess:ruff",
        prerequisites=("python>=3.10", "python-module:ruff"),
    ),
    CheckSpec(
        name="shellcheck",
        code="QLV-003",
        purpose="Run full ShellCheck over tracked shell entrypoints.",
        severity="error",
        error_kind="shell_lint_failed",
        failure_hint="Fix every ShellCheck finding in the named tracked entrypoint.",
        command=("{shellcheck}", "{tracked-shell-entrypoints}"),
        implementation="subprocess:tracked-shell-entrypoints",
        prerequisites=("git", "shellcheck"),
    ),
    CheckSpec(
        name="pytest",
        code="QLV-004",
        purpose="Run hook, renderer, and verifier Python tests without pytest cache.",
        severity="error",
        error_kind="python_tests_failed",
        failure_hint="Repair the failing or errored test and rerun the same gate.",
        command=(
            "{python}",
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "hooks/tests",
            "src/tests",
            "scripts/tests",
            "-q",
        ),
        implementation="subprocess:pytest",
        prerequisites=("python>=3.10", "python-module:pytest"),
    ),
    CheckSpec(
        name="shell-regression",
        code="QLV-005",
        purpose="Run the full shell-first status-line regression suite.",
        severity="error",
        error_kind="shell_regression_failed",
        failure_hint="Repair the failing numbered assertion and rerun the full suite.",
        command=("{bash}", "tests/test-statusline.sh"),
        implementation="subprocess:shell-regression",
        prerequisites=("bash", "python>=3.10"),
    ),
    CheckSpec(
        name="git-diff",
        code="QLV-006",
        purpose="Reject whitespace errors in the working-tree diff.",
        severity="error",
        error_kind="diff_check_failed",
        failure_hint="Correct the reported whitespace error and rerun the gate.",
        command=("{git}", "diff", "--check"),
        implementation="subprocess:git-diff-check",
        prerequisites=("git",),
    ),
    CheckSpec(
        name="test-integrity",
        code="QLV-007",
        purpose="Reject masked Python diagnostics and exit-masking test pipelines.",
        severity="error",
        error_kind="test_integrity_failed",
        failure_hint="Retain subprocess stderr, preserve pipeline exits, and rerun the gate.",
        command=("{python}", "{verify}", "_test_integrity"),
        implementation="builtin:shell-test-integrity",
        prerequisites=("git", "python>=3.10"),
    ),
    CheckSpec(
        name="base-diff",
        code="QLV-008",
        purpose="Reject whitespace errors in every commit since the configured base.",
        severity="error",
        error_kind="base_diff_failed",
        failure_hint="Correct the committed whitespace error and rerun against the same base.",
        command=("{python}", "{verify}", "_base_diff"),
        implementation="builtin:base-range-diff-check",
        prerequisites=("git", "python>=3.10"),
    ),
    CheckSpec(
        name="install-regression",
        code="QLV-009",
        purpose="Run the sandboxed core installer regression suite.",
        severity="error",
        error_kind="install_regression_failed",
        failure_hint="Repair the failing installer assertion and rerun the full gate.",
        command=("{bash}", "tests/test-install-core.sh"),
        implementation="subprocess:install-regression",
        prerequisites=("bash", "python>=3.10"),
    ),
)

_CHECK_BY_NAME = {spec.name: spec for spec in CHECKS}

REPORT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "schema_version",
        "verdict",
        "summary",
        "checks",
        "effects",
        "elapsed_ms",
    ],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "verdict": {"enum": ["pass", "fail", "blocked"]},
        "summary": {
            "type": "object",
            "required": ["blocked", "failed", "passed", "selected"],
            "properties": {
                key: {"type": "integer", "minimum": 0}
                for key in ("blocked", "failed", "passed", "selected")
            },
            "additionalProperties": False,
        },
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "name",
                    "code",
                    "purpose",
                    "severity",
                    "status",
                    "command",
                    "implementation",
                    "prerequisites",
                    "exit_code",
                    "duration_ms",
                    "stdout_summary",
                    "stderr_summary",
                ],
                "properties": {
                    "name": {"type": "string"},
                    "code": {"type": "string", "pattern": r"^QLV-\d{3}$"},
                    "purpose": {"type": "string"},
                    "severity": {"const": "error"},
                    "status": {"enum": ["pass", "fail", "blocked"]},
                    "command": {"type": "array", "items": {"type": "string"}},
                    "implementation": {"type": "string"},
                    "prerequisites": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "exit_code": {"type": ["integer", "null"]},
                    "duration_ms": {"type": "integer", "minimum": 0},
                    "stdout_summary": {"type": "string"},
                    "stderr_summary": {"type": "string"},
                    "error": {"type": "object"},
                    "diagnostics": {
                        "type": "object",
                        "required": ["prerequisites"],
                        "properties": {
                            "prerequisites": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": [
                                        "prerequisite",
                                        "kind",
                                        "available",
                                        "path",
                                        "version",
                                    ],
                                    "properties": {
                                        "prerequisite": {"type": "string"},
                                        "kind": {
                                            "enum": [
                                                "executable",
                                                "interpreter",
                                                "python-module",
                                            ]
                                        },
                                        "available": {"type": "boolean"},
                                        "path": {"type": "string"},
                                        "version": {"type": "string"},
                                    },
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "additionalProperties": False,
                    },
                    "stdout": {"type": "object"},
                    "stderr": {"type": "object"},
                },
                "additionalProperties": False,
            },
        },
        "effects": {
            "type": "object",
            "required": ["destructive", "idempotent", "network", "read_only", "writes"],
            "properties": {
                "destructive": {"const": False},
                "idempotent": {"type": "boolean"},
                "network": {"const": False},
                "read_only": {"type": "boolean"},
                "writes": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        "elapsed_ms": {"type": "integer", "minimum": 0},
    },
    "additionalProperties": False,
}

Runner = Callable[[CheckSpec, tuple[str, ...], float, Path], RunResult]


def _positive_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if timeout <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return timeout


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify.py",
        description="Run qLine's canonical fail-closed verification gate.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    schema = subparsers.add_parser(
        "schema", help="Describe commands, checks, effects, and report fields."
    )
    schema.add_argument("check", nargs="?", choices=tuple(_CHECK_BY_NAME))
    _add_output_arguments(schema)

    doctor = subparsers.add_parser(
        "doctor", help="Check repository access and prerequisites without running checks."
    )
    _add_selection_arguments(doctor)
    _add_output_arguments(doctor)

    run = subparsers.add_parser("run", help="Run selected checks in registry order.")
    _add_selection_arguments(run)
    _add_output_arguments(run)
    run.add_argument(
        "--timeout-seconds",
        type=_positive_timeout,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Per-check timeout in seconds (default: %(default)s).",
    )
    run.add_argument(
        "--log-dir",
        type=Path,
        help="Optional directory for full per-check logs and report.json.",
    )
    return parser


def _add_selection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--check",
        action="append",
        choices=tuple(_CHECK_BY_NAME),
        help="Run or inspect one check; repeat to select more (default: all).",
    )


def _add_output_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format; deterministic and never inferred from the terminal.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include bounded stdout and stderr objects for each check.",
    )
    parser.add_argument(
        "--fields",
        action="append",
        help="Comma-separated root fields for JSON projection.",
    )


def _select(names: Sequence[str] | None) -> tuple[CheckSpec, ...]:
    if not names:
        return CHECKS
    selected = set(names)
    return tuple(spec for spec in CHECKS if spec.name in selected)


def _error(
    kind: str,
    message: str,
    hint: str,
    *,
    retryable: bool,
    details: dict | None = None,
) -> dict:
    if kind not in ERROR_KINDS:
        raise ValueError(f"unregistered error kind: {kind}")
    return {
        "kind": kind,
        "message": message,
        "hint": hint,
        "retryable": retryable,
        "details": details or {},
    }


def _check_schema(spec: CheckSpec) -> dict:
    return {
        "name": spec.name,
        "code": spec.code,
        "purpose": spec.purpose,
        "severity": spec.severity,
        "error_kind": spec.error_kind,
        "failure_hint": spec.failure_hint,
        "command": list(spec.command),
        "implementation": spec.implementation,
        "prerequisites": list(spec.prerequisites),
        "effects": asdict(spec.effects),
    }


def _schema_report(selected: Sequence[CheckSpec]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": "pass",
        "summary": {"checks": len(selected), "commands": 3},
        "checks": [_check_schema(spec) for spec in selected],
        "effects": {
            "schema": asdict(Effects()),
            "doctor": asdict(Effects()),
            "run": {
                "read_only": True,
                "destructive": False,
                "idempotent": True,
                "network": False,
                "optional_writes": ["--log-dir"],
                "with_log_dir": {
                    "read_only": False,
                    "idempotent": False,
                    "fresh_destination_required": True,
                },
            },
        },
        "elapsed_ms": 0,
        "report_schema": REPORT_SCHEMA,
        "report_schema_scope": ["doctor", "run"],
        "error_kinds": sorted(ERROR_KINDS),
    }


def _global_blocked(
    error: dict, *, elapsed_ms: int = 0, log_dir: Path | None = None
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": "blocked",
        "summary": {"blocked": 1, "failed": 0, "passed": 0, "selected": 1},
        "checks": [
            {
                "name": "repository",
                "code": "QLV-000",
                "purpose": "Establish a readable qLine Git worktree.",
                "severity": "error",
                "status": "blocked",
                "command": ["git", "rev-parse", "--show-toplevel"],
                "implementation": "builtin:repository-preflight",
                "prerequisites": ["git"],
                "exit_code": None,
                "duration_ms": 0,
                "stdout_summary": "",
                "stderr_summary": "",
                "error": error,
            }
        ],
        "effects": _run_effects(log_dir),
        "elapsed_ms": max(0, elapsed_ms),
    }


def _validate_repo(repo: Path) -> dict | None:
    if not repo.is_dir() or not os.access(repo, os.R_OK | os.X_OK):
        return _error(
            "repository_unreadable",
            "The repository directory is absent or unreadable.",
            "Provide a readable qLine Git worktree and rerun the same command.",
            retryable=False,
            details={"repo": str(repo)},
        )
    git = shutil.which("git")
    if git is None:
        return _error(
            "prerequisite_missing",
            "Required tool 'git' is unavailable.",
            "Install Git and rerun the same command.",
            retryable=True,
            details={"prerequisite": "git"},
        )
    try:
        proc = subprocess.run(
            [git, "-C", str(repo), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _error(
            "repository_unreadable",
            "The qLine worktree could not be inspected.",
            "Restore Git access to the worktree and rerun the same command.",
            retryable=True,
            details={"exception": type(exc).__name__, "repo": str(repo)},
        )
    if proc.returncode != 0:
        return _error(
            "repository_unreadable",
            "The selected directory is not a readable Git worktree.",
            "Run from a qLine Git worktree or pass the repository through the caller.",
            retryable=False,
            details={"repo": str(repo), "git_exit_code": proc.returncode},
        )
    return None


def _prerequisite_evidence(prerequisite: str) -> dict:
    if prerequisite == "python>=3.10":
        return {
            "prerequisite": prerequisite,
            "kind": "interpreter",
            "available": sys.version_info >= (3, 10),
            "path": str(Path(sys.executable).resolve()),
            "version": ".".join(str(part) for part in sys.version_info[:3]),
        }
    if prerequisite.startswith("python-module:"):
        module = prerequisite.split(":", 1)[1]
        try:
            module_spec = importlib.util.find_spec(module)
        except (ImportError, ValueError):
            module_spec = None
        version = ""
        if module_spec is not None:
            try:
                version = importlib_metadata.version(module)
            except importlib_metadata.PackageNotFoundError:
                pass
        return {
            "prerequisite": prerequisite,
            "kind": "python-module",
            "available": module_spec is not None,
            "path": (
                ""
                if module_spec is None or module_spec.origin is None
                else module_spec.origin
            ),
            "version": version,
        }
    path = shutil.which(prerequisite)
    return {
        "prerequisite": prerequisite,
        "kind": "executable",
        "available": path is not None,
        "path": path or "",
        "version": "",
    }


def _prerequisite_error(spec: CheckSpec) -> dict | None:
    for prerequisite in spec.prerequisites:
        evidence = _prerequisite_evidence(prerequisite)
        if prerequisite == "python>=3.10":
            display = "Python 3.10+"
            hint = "Run the verifier with Python 3.10 or newer."
        elif prerequisite.startswith("python-module:"):
            module = prerequisite.split(":", 1)[1]
            display = module
            hint = f"Install the pinned development dependency for {module} and rerun."
        else:
            display = prerequisite
            if prerequisite == "shellcheck":
                hint = "Install ShellCheck and rerun the same command."
            else:
                hint = f"Install {prerequisite} and rerun the same command."
        if not evidence["available"]:
            return _error(
                "prerequisite_missing",
                f"Required tool '{display}' is unavailable.",
                hint,
                retryable=True,
                details={"prerequisite": display},
            )
    return None


def _git_tracked(repo: Path) -> tuple[str, ...]:
    proc = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"],
        capture_output=True,
        check=False,
        timeout=10,
    )
    if proc.returncode != 0:
        raise OSError(f"git ls-files exited {proc.returncode}")
    return tuple(
        chunk.decode("utf-8", errors="surrogateescape")
        for chunk in proc.stdout.split(b"\0")
        if chunk
    )


def _tracked_shell_entrypoints(repo: Path) -> tuple[str, ...]:
    entrypoints = []
    for relative in _git_tracked(repo):
        path = repo / relative
        try:
            first_line = path.open("rb").readline(256).decode("utf-8", errors="replace")
        except OSError as exc:
            raise OSError(
                f"tracked shell input is unreadable: {relative}: {exc}"
            ) from exc
        explicit_suffix = relative.endswith((".sh", ".bash", ".zsh"))
        shell_shebang = first_line.startswith("#!") and bool(
            re.search(r"(?:/|env\s+)(?:ba|z|da|k)?sh(?:\s|$)", first_line)
        )
        if explicit_suffix or shell_shebang:
            entrypoints.append(relative)
    return tuple(sorted(entrypoints))


def _tracked_test_shells(repo: Path) -> tuple[str, ...]:
    return tuple(
        relative
        for relative in _git_tracked(repo)
        if relative.endswith((".sh", ".bash", ".zsh"))
        and (relative.startswith("tests/") or relative.startswith("hooks/tests/"))
    )


def _tracked_python_tests(repo: Path) -> tuple[str, ...]:
    roots = ("tests/", "hooks/tests/", "src/tests/", "scripts/tests/")
    return tuple(
        relative
        for relative in _git_tracked(repo)
        if relative.endswith(".py")
        and relative.startswith(roots)
        and Path(relative).name.startswith("test_")
    )


_KNOWN_CAPABILITY_PROBES = frozenset(
    {
        'if command -v "$_candidate" > /dev/null 2>&1; then',
        (
            'read -r _major _minor <<< "$("$_candidate" -c '
            "'import sys; print(sys.version_info.major, sys.version_info.minor)' "
            '2>/dev/null || echo "0 0")"'
        ),
        'SNAP_COUNT=$(wc -l < "$SNAP_FILE" 2>/dev/null | tr -d \' \' || echo 0)',
        'SNAP_COUNT2=$(wc -l < "$SNAP_FILE" 2>/dev/null | tr -d \' \' || echo 0)',
        'SNAP_COUNT3=$(wc -l < "$SNAP_FILE" 2>/dev/null | tr -d \' \' || echo 0)',
        (
            'NO_SID_SNAP=$(find "$OBS_TEST_ROOT_6" -name "snapshots.jsonl" '
            '2>/dev/null | wc -l | tr -d \' \')'
        ),
    }
)


def _is_known_capability_probe(line: str) -> bool:
    return line.strip() in _KNOWN_CAPABILITY_PROBES


def _test_integrity_findings(repo: Path) -> list[dict]:
    findings = []
    discarded_stderr = re.compile(
        r"(?:2\s*>\s*/dev/null|>\s*/dev/null\s+2\s*>\s*&1)"
    )
    python_token = re.compile(r'(?:\$\{?PYTHON\}?|["\']?python(?:3(?:\.\d+)?)?["\']?)')
    for relative in _tracked_test_shells(repo):
        lines = (repo / relative).read_text(encoding="utf-8").splitlines()
        has_pipefail = any(
            re.match(r"^\s*set\s+-[^#\n]*o\s+pipefail(?:\s|$)", line)
            for line in lines
        )
        for line_number, line in enumerate(lines, 1):
            capability_probe = _is_known_capability_probe(line)
            if (
                discarded_stderr.search(line)
                and python_token.search(line)
                and not capability_probe
            ):
                findings.append(
                    {
                        "path": relative,
                        "line": line_number,
                        "kind": "python_stderr_discarded",
                        "message": "test subprocess stderr is discarded instead of retained",
                    }
                )
            has_pipeline = re.search(r"(?<!\|)\|(?!\|)", line) is not None
            if has_pipeline and python_token.search(line) and not has_pipefail:
                findings.append(
                    {
                        "path": relative,
                        "line": line_number,
                        "kind": "pipeline_without_pipefail",
                        "message": "Python test pipeline can hide an upstream exit",
                    }
                )
            if python_token.search(line) and re.search(r"\|\|\s*(?:true|:)(?:\s|$)", line):
                findings.append(
                    {
                        "path": relative,
                        "line": line_number,
                        "kind": "python_exit_masked",
                        "message": "Python test exit is unconditionally discarded",
                    }
                )
    for relative in _tracked_python_tests(repo):
        source = (repo / relative).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            body_nodes = list(ast.walk(ast.Module(body=node.body, type_ignores=[])))
            sleeps = [
                item
                for item in body_nodes
                if isinstance(item, ast.Call)
                and isinstance(item.func, ast.Attribute)
                and isinstance(item.func.value, ast.Name)
                and item.func.value.id == "time"
                and item.func.attr == "sleep"
            ]
            for _sleep in sleeps:
                findings.append(
                    {
                        "path": relative,
                        "line": node.lineno,
                        "kind": "python_sleep_in_test",
                        "message": "test uses time.sleep() instead of a controlled condition",
                    }
                )
            has_assertion = any(isinstance(item, ast.Assert) for item in body_nodes)
            if not has_assertion:
                for item in body_nodes:
                    if not isinstance(item, ast.Call):
                        continue
                    func = item.func
                    if isinstance(func, ast.Attribute) and (
                        func.attr.startswith("assert_")
                        or (
                            isinstance(func.value, ast.Name)
                            and func.value.id == "pytest"
                            and func.attr in {"raises", "warns", "fail"}
                        )
                    ):
                        has_assertion = True
                        break
                    if isinstance(func, ast.Name) and func.id in {"fail", "assert_raises"}:
                        has_assertion = True
                        break
            if not has_assertion:
                findings.append(
                    {
                        "path": relative,
                        "line": node.lineno,
                        "kind": "python_test_without_assertion",
                        "message": "test body contains no assertion or explicit failure check",
                    }
                )
    findings.sort(key=lambda item: (item["path"], item["line"], item["kind"]))
    return findings


def _resolve_command(spec: CheckSpec, repo: Path) -> tuple[str, ...]:
    resolved = []
    for token in spec.command:
        if token == "{python}":
            resolved.append(sys.executable)
        elif token == "{verify}":
            resolved.append(str(Path(__file__).resolve()))
        elif token == "{shellcheck}":
            resolved.append(shutil.which("shellcheck") or "shellcheck")
        elif token == "{bash}":
            resolved.append(shutil.which("bash") or "bash")
        elif token == "{git}":
            resolved.append(shutil.which("git") or "git")
        elif token == "{tracked-shell-entrypoints}":
            entrypoints = _tracked_shell_entrypoints(repo)
            if not entrypoints:
                raise OSError("no tracked shell entrypoints were found")
            resolved.extend(entrypoints)
        else:
            resolved.append(token)
    return tuple(resolved)


def _clip_bytes_head_tail(payload: bytes, limit: int) -> tuple[str, int]:
    if len(payload) <= limit:
        return payload.decode("utf-8", errors="replace"), 0
    marker = b"\n... output omitted ...\n"
    source_budget = max(0, limit - len(marker))
    head = source_budget // 2
    tail = source_budget - head
    clipped = payload[:head] + marker + (payload[-tail:] if tail else b"")
    return clipped.decode("utf-8", errors="replace"), len(payload) - source_budget


def _read_capture(path: Path, *, bounded: bool) -> tuple[str, int, int]:
    size = path.stat().st_size
    if not bounded:
        return path.read_bytes().decode("utf-8", errors="replace"), size, 0
    with path.open("rb") as handle:
        head_size = MAX_STREAM_BYTES // 2
        head = handle.read(head_size)
        tail_size = max(0, MAX_STREAM_BYTES - head_size - 64)
        handle.seek(max(0, size - tail_size))
        tail = handle.read(tail_size)
    marker = b"\n... output omitted ...\n"
    payload = head + marker + tail
    text, extra_omitted = _clip_bytes_head_tail(payload, MAX_STREAM_BYTES)
    source_kept = len(head) + len(tail) - extra_omitted
    return text, size, max(0, size - source_kept)


def _terminate_process_group(proc: subprocess.Popen) -> bool:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError:
        return False
    try:
        proc.wait(timeout=PROCESS_REAP_SECONDS)
        return True
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        return False
    try:
        proc.wait(timeout=PROCESS_REAP_SECONDS)
    except subprocess.TimeoutExpired:
        return False
    return True


def _subprocess_runner(
    spec: CheckSpec, command: tuple[str, ...], timeout_seconds: float, cwd: Path
) -> RunResult:
    started = time.monotonic()
    environment = {
        **os.environ,
        "NO_COLOR": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if spec.name == "shell-regression":
        environment["QLINE_TEST_PYTHON"] = sys.executable
    capture_dir: Path | None = None
    try:
        capture_dir = Path(tempfile.mkdtemp(prefix="qline-verify-capture-"))
        os.chmod(capture_dir, 0o700)
        stdout_path = capture_dir / "stdout"
        stderr_path = capture_dir / "stderr"
        with stdout_path.open("wb", buffering=0) as stdout_handle, stderr_path.open(
            "wb", buffering=0
        ) as stderr_handle:
            os.chmod(stdout_path, 0o600)
            os.chmod(stderr_path, 0o600)
            try:
                proc = subprocess.Popen(
                    command,
                    cwd=cwd,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    start_new_session=True,
                    env=environment,
                )
            except OSError as exc:
                result = RunResult(
                    exit_code=2,
                    stdout="",
                    stderr=f"{type(exc).__name__}: {exc}\n",
                    duration_ms=max(0, round((time.monotonic() - started) * 1000)),
                )
                raise CheckExecutionFailed(result) from exc
            deadline = started + timeout_seconds
            interrupted: str | None = None
            while proc.poll() is None:
                output_bytes = os.fstat(stdout_handle.fileno()).st_size + os.fstat(
                    stderr_handle.fileno()
                ).st_size
                if output_bytes > MAX_PROCESS_OUTPUT_BYTES:
                    interrupted = "output"
                    break
                if time.monotonic() >= deadline:
                    interrupted = "timeout"
                    break
                time.sleep(PROCESS_POLL_SECONDS)
            if interrupted is not None:
                reaped = _terminate_process_group(proc)
                stdout_bytes = os.fstat(stdout_handle.fileno()).st_size
                stderr_bytes = os.fstat(stderr_handle.fileno()).st_size
                stdout, _, stdout_omitted = _read_capture(stdout_path, bounded=True)
                stderr, _, stderr_omitted = _read_capture(stderr_path, bounded=True)
                result = RunResult(
                    exit_code=2,
                    stdout=stdout,
                    stderr=stderr,
                    duration_ms=max(0, round((time.monotonic() - started) * 1000)),
                    stdout_bytes=stdout_bytes,
                    stderr_bytes=stderr_bytes,
                    stdout_omitted_bytes=stdout_omitted,
                    stderr_omitted_bytes=stderr_omitted,
                )
                if not reaped:
                    raise ProcessGroupReapFailed(result)
                if interrupted == "timeout":
                    raise CheckTimeout(result)
                raise OutputLimitExceeded(result)
            stdout, stdout_bytes, _ = _read_capture(stdout_path, bounded=False)
            stderr, stderr_bytes, _ = _read_capture(stderr_path, bounded=False)
            return RunResult(
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_ms=max(0, round((time.monotonic() - started) * 1000)),
                stdout_bytes=stdout_bytes,
                stderr_bytes=stderr_bytes,
            )
    except InterruptedCheck:
        raise
    except OSError as exc:
        result = RunResult(
            exit_code=2,
            stdout="",
            stderr=f"{type(exc).__name__}: {exc}\n",
            duration_ms=max(0, round((time.monotonic() - started) * 1000)),
        )
        raise OutputCaptureFailed(result) from exc
    finally:
        if capture_dir is not None:
            shutil.rmtree(capture_dir, ignore_errors=True)


def _strip_ansi(value: str) -> str:
    return _ANSI_RE.sub("", value)


def _stream(
    value: str, *, total_bytes: int | None = None, omitted_bytes: int = 0
) -> dict:
    clean = _strip_ansi(value)
    payload = clean.encode("utf-8")
    text, clipped_omitted = _clip_bytes_head_tail(payload, MAX_STREAM_BYTES)
    observed_bytes = len(payload) if total_bytes is None else total_bytes
    total_omitted = max(omitted_bytes, clipped_omitted)
    return {
        "text": text,
        "bytes": observed_bytes,
        "truncated": total_omitted > 0,
        "omitted_bytes": total_omitted,
    }


def _summary(value: str) -> str:
    lines = [line.strip() for line in _strip_ansi(value).splitlines() if line.strip()]
    selected = lines if len(lines) <= 3 else [*lines[:2], "…", lines[-1]]
    summary = " | ".join(selected)
    if len(summary) <= MAX_SUMMARY_CHARS:
        return summary
    return summary[: MAX_SUMMARY_CHARS - 1] + "…"


def _timeout_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _base_check(spec: CheckSpec, command: Sequence[str] | None = None) -> dict:
    return {
        "name": spec.name,
        "code": spec.code,
        "purpose": spec.purpose,
        "severity": spec.severity,
        "status": "blocked",
        "command": list(command or spec.command),
        "implementation": spec.implementation,
        "prerequisites": list(spec.prerequisites),
        "exit_code": None,
        "duration_ms": 0,
        "stdout_summary": "",
        "stderr_summary": "",
    }


def _blocked_check(
    spec: CheckSpec,
    error: dict,
    *,
    command: Sequence[str] | None = None,
    duration_ms: int = 0,
    stdout: str = "",
    stderr: str = "",
    verbose: bool = False,
) -> dict:
    check = _base_check(spec, command)
    check["duration_ms"] = max(0, duration_ms)
    check["stdout_summary"] = _summary(stdout)
    check["stderr_summary"] = _summary(stderr)
    check["error"] = error
    if verbose:
        check["stdout"] = _stream(stdout)
        check["stderr"] = _stream(stderr)
    return check


def _completed_check(
    spec: CheckSpec, command: tuple[str, ...], result: RunResult, verbose: bool
) -> dict:
    check = _base_check(spec, command)
    check.update(
        {
            "status": "pass" if result.exit_code == 0 else "fail",
            "exit_code": result.exit_code,
            "duration_ms": max(0, result.duration_ms),
            "stdout_summary": _summary(result.stdout),
            "stderr_summary": _summary(result.stderr),
        }
    )
    if result.exit_code != 0:
        check["error"] = _error(
            spec.error_kind,
            f"Check '{spec.name}' completed with findings.",
            spec.failure_hint,
            retryable=False,
            details={"exit_code": result.exit_code},
        )
    if verbose:
        check["stdout"] = _stream(
            result.stdout,
            total_bytes=result.stdout_bytes,
            omitted_bytes=result.stdout_omitted_bytes,
        )
        check["stderr"] = _stream(
            result.stderr,
            total_bytes=result.stderr_bytes,
            omitted_bytes=result.stderr_omitted_bytes,
        )
    return check


def _unexpected_exit_check(
    spec: CheckSpec, command: tuple[str, ...], result: RunResult, verbose: bool
) -> dict:
    check = _base_check(spec, command)
    check.update(
        {
            "exit_code": result.exit_code,
            "duration_ms": max(0, result.duration_ms),
            "stdout_summary": _summary(result.stdout),
            "stderr_summary": _summary(result.stderr),
            "error": _error(
                "unexpected_check_exit",
                f"Check '{spec.name}' exited {result.exit_code}; its result is inconclusive.",
                "Inspect the bounded diagnostics or full log, repair the check environment, and retry.",
                retryable=True,
                details={"exit_code": result.exit_code},
            ),
        }
    )
    if verbose:
        check["stdout"] = _stream(
            result.stdout,
            total_bytes=result.stdout_bytes,
            omitted_bytes=result.stdout_omitted_bytes,
        )
        check["stderr"] = _stream(
            result.stderr,
            total_bytes=result.stderr_bytes,
            omitted_bytes=result.stderr_omitted_bytes,
        )
    return check


def _run_effects(log_dir: Path | None) -> dict:
    return {
        "destructive": False,
        "idempotent": log_dir is None,
        "network": False,
        "read_only": log_dir is None,
        "writes": [] if log_dir is None else [str(log_dir.resolve())],
    }


def _report(checks: list[dict], *, log_dir: Path | None, elapsed_ms: int) -> dict:
    passed = sum(check["status"] == "pass" for check in checks)
    failed = sum(check["status"] == "fail" for check in checks)
    blocked = sum(check["status"] == "blocked" for check in checks)
    verdict = "blocked" if blocked else "fail" if failed else "pass"
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": verdict,
        "summary": {
            "blocked": blocked,
            "failed": failed,
            "passed": passed,
            "selected": len(checks),
        },
        "checks": checks,
        "effects": _run_effects(log_dir),
        "elapsed_ms": max(0, elapsed_ms),
    }


def _validate_report(report: dict) -> None:
    if list(report) != REPORT_SCHEMA["required"]:
        raise ValueError("report root fields do not match the published schema")
    if report["schema_version"] != SCHEMA_VERSION:
        raise ValueError("report schema_version is invalid")
    if report["verdict"] not in {"pass", "fail", "blocked"}:
        raise ValueError("report verdict is invalid")
    if not isinstance(report["checks"], list) or not isinstance(report["effects"], dict):
        raise ValueError("report containers are invalid")
    if not isinstance(report["elapsed_ms"], int) or report["elapsed_ms"] < 0:
        raise ValueError("report elapsed_ms is invalid")

    summary = report["summary"]
    summary_keys = {"blocked", "failed", "passed", "selected"}
    if not isinstance(summary, dict) or set(summary) != summary_keys:
        raise ValueError("report summary fields are invalid")
    if any(not isinstance(summary[key], int) or summary[key] < 0 for key in summary_keys):
        raise ValueError("report summary values are invalid")

    required_check_fields = set(
        REPORT_SCHEMA["properties"]["checks"]["items"]["required"]
    )
    allowed_check_fields = set(
        REPORT_SCHEMA["properties"]["checks"]["items"]["properties"]
    )
    for check in report["checks"]:
        if not isinstance(check, dict):
            raise ValueError("check entry is invalid")
        if not required_check_fields <= set(check) or not set(check) <= allowed_check_fields:
            raise ValueError("check fields are invalid")
        if check.get("status") not in {"pass", "fail", "blocked"}:
            raise ValueError("check status is invalid")
        if not re.fullmatch(r"QLV-\d{3}", str(check.get("code", ""))):
            raise ValueError("check code is invalid")
        for key in ("name", "purpose", "implementation", "stdout_summary", "stderr_summary"):
            if not isinstance(check[key], str):
                raise ValueError(f"check {key} is invalid")
        if check["severity"] != "error":
            raise ValueError("check severity is invalid")
        if not isinstance(check["command"], list) or not all(
            isinstance(item, str) for item in check["command"]
        ):
            raise ValueError("check command is invalid")
        if not isinstance(check["prerequisites"], list) or not all(
            isinstance(item, str) for item in check["prerequisites"]
        ):
            raise ValueError("check prerequisites are invalid")
        if "diagnostics" in check:
            diagnostics = check["diagnostics"]
            if not isinstance(diagnostics, dict) or set(diagnostics) != {
                "prerequisites"
            }:
                raise ValueError("check diagnostics fields are invalid")
            evidence = diagnostics["prerequisites"]
            if not isinstance(evidence, list):
                raise ValueError("check prerequisite evidence is invalid")
            expected_evidence_fields = {
                "prerequisite",
                "kind",
                "available",
                "path",
                "version",
            }
            for item in evidence:
                if not isinstance(item, dict) or set(item) != expected_evidence_fields:
                    raise ValueError("check prerequisite evidence fields are invalid")
                if item["kind"] not in {
                    "executable",
                    "interpreter",
                    "python-module",
                }:
                    raise ValueError("check prerequisite evidence kind is invalid")
                if not isinstance(item["available"], bool) or not all(
                    isinstance(item[key], str)
                    for key in ("prerequisite", "path", "version")
                ):
                    raise ValueError("check prerequisite evidence values are invalid")
        if not isinstance(check["duration_ms"], int) or check["duration_ms"] < 0:
            raise ValueError("check duration_ms is invalid")
        if check["exit_code"] is not None and not isinstance(check["exit_code"], int):
            raise ValueError("check exit_code is invalid")
        if check["status"] == "pass" and (check["exit_code"] != 0 or "error" in check):
            raise ValueError("passing check result is inconsistent")
        if check["status"] == "fail" and (check["exit_code"] != 1 or "error" not in check):
            raise ValueError("failing check result is inconsistent")
        if check["status"] == "blocked" and "error" not in check:
            raise ValueError("blocked check lacks an error")
        if "error" in check:
            error = check["error"]
            if not isinstance(error, dict) or set(error) != {
                "kind",
                "message",
                "hint",
                "retryable",
                "details",
            }:
                raise ValueError("check error fields are invalid")
            if error["kind"] not in ERROR_KINDS:
                raise ValueError("check error kind is invalid")
            if not all(isinstance(error[key], str) for key in ("message", "hint")):
                raise ValueError("check error text is invalid")
            if not isinstance(error["retryable"], bool) or not isinstance(
                error["details"], dict
            ):
                raise ValueError("check error metadata is invalid")
        for stream_name in ("stdout", "stderr"):
            if stream_name not in check:
                continue
            stream = check[stream_name]
            if not isinstance(stream, dict) or set(stream) != {
                "text",
                "bytes",
                "truncated",
                "omitted_bytes",
            }:
                raise ValueError("check stream fields are invalid")
            if not isinstance(stream["text"], str) or not isinstance(
                stream["truncated"], bool
            ):
                raise ValueError("check stream values are invalid")
            if any(
                not isinstance(stream[key], int) or stream[key] < 0
                for key in ("bytes", "omitted_bytes")
            ):
                raise ValueError("check stream sizes are invalid")

    observed = {
        "blocked": sum(check["status"] == "blocked" for check in report["checks"]),
        "failed": sum(check["status"] == "fail" for check in report["checks"]),
        "passed": sum(check["status"] == "pass" for check in report["checks"]),
        "selected": len(report["checks"]),
    }
    if summary != observed:
        raise ValueError("report summary counts are inconsistent")
    expected_verdict = "blocked" if observed["blocked"] else "fail" if observed["failed"] else "pass"
    if report["verdict"] != expected_verdict:
        raise ValueError("report verdict is inconsistent")

    effects = report["effects"]
    if not isinstance(effects, dict) or set(effects) != {
        "destructive",
        "idempotent",
        "network",
        "read_only",
        "writes",
    }:
        raise ValueError("report effects fields are invalid")
    if effects["destructive"] is not False or effects["network"] is not False:
        raise ValueError("report effects are unsafe")
    if not isinstance(effects["idempotent"], bool) or not isinstance(
        effects["read_only"], bool
    ):
        raise ValueError("report effects values are invalid")
    if not isinstance(effects["writes"], list) or not all(
        isinstance(path, str) for path in effects["writes"]
    ):
        raise ValueError("report writes are invalid")
    if effects["read_only"] != (effects["writes"] == []):
        raise ValueError("report write effects are inconsistent")
    if effects["idempotent"] != effects["read_only"]:
        raise ValueError("report idempotency effects are inconsistent")


class LogDestinationNotFresh(OSError):
    """Raised before execution when a log destination contains prior-run artifacts."""


def _prepare_log_dir(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise OSError("log directory may not be a symlink")
    if expanded.exists() and expanded.is_dir() and any(expanded.iterdir()):
        raise LogDestinationNotFresh("log directory is not empty")
    expanded.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not expanded.is_dir():
        raise OSError("log path is not a directory")
    os.chmod(expanded, 0o700)
    return expanded.resolve()


def _write_private(path: Path, content: str) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _write_check_logs(log_dir: Path, check: dict, result: RunResult) -> None:
    stem = f"{check['code']}-{check['name']}"
    _write_private(log_dir / f"{stem}.stdout.log", result.stdout)
    _write_private(log_dir / f"{stem}.stderr.log", result.stderr)


def _persist_interrupted_logs(
    log_dir: Path | None,
    check: dict,
    result: RunResult,
    spec: CheckSpec,
) -> None:
    """Persist retained interruption output or convert the check to a log failure."""
    if log_dir is None:
        return
    original_kind = check["error"]["kind"]
    try:
        _write_check_logs(log_dir, check, result)
    except OSError as exc:
        check["error"] = _error(
            "log_write_failed",
            f"Logs for interrupted check '{spec.name}' could not be written.",
            "Repair --log-dir permissions or rerun without log persistence.",
            retryable=True,
            details={
                "exception": type(exc).__name__,
                "log_dir": str(log_dir),
                "interrupted_kind": original_kind,
            },
        )


def _doctor(selected: Sequence[CheckSpec], *, verbose: bool) -> list[dict]:
    checks = []
    for spec in selected:
        prerequisite_error = _prerequisite_error(spec)
        if prerequisite_error:
            check = _blocked_check(spec, prerequisite_error)
            if verbose:
                check["diagnostics"] = {
                    "prerequisites": [
                        _prerequisite_evidence(item) for item in spec.prerequisites
                    ]
                }
            checks.append(check)
            continue
        check = _base_check(spec)
        check.update({"status": "pass", "exit_code": 0})
        if verbose:
            check["diagnostics"] = {
                "prerequisites": [
                    _prerequisite_evidence(item) for item in spec.prerequisites
                ]
            }
        checks.append(check)
    return checks


def _interrupted_check(
    spec: CheckSpec,
    command: tuple[str, ...],
    result: RunResult,
    *,
    kind: str,
    message: str,
    hint: str,
    details: dict,
    verbose: bool,
) -> dict:
    check = _blocked_check(
        spec,
        _error(kind, message, hint, retryable=True, details=details),
        command=command,
        duration_ms=result.duration_ms,
        stdout=result.stdout,
        stderr=result.stderr,
        verbose=False,
    )
    if verbose:
        check["stdout"] = _stream(
            result.stdout,
            total_bytes=result.stdout_bytes,
            omitted_bytes=result.stdout_omitted_bytes,
        )
        check["stderr"] = _stream(
            result.stderr,
            total_bytes=result.stderr_bytes,
            omitted_bytes=result.stderr_omitted_bytes,
        )
    return check


def _run_checks(
    selected: Sequence[CheckSpec],
    *,
    repo: Path,
    runner: Runner,
    timeout_seconds: float,
    verbose: bool,
    log_dir: Path | None,
) -> list[dict]:
    checks = []
    for spec in selected:
        prerequisite_error = _prerequisite_error(spec)
        if prerequisite_error:
            checks.append(_blocked_check(spec, prerequisite_error))
            continue
        started = time.monotonic()
        try:
            command = _resolve_command(spec, repo)
        except OSError as exc:
            checks.append(
                _blocked_check(
                    spec,
                    _error(
                        "check_execution_error",
                        f"Check '{spec.name}' could not resolve its tracked inputs.",
                        "Restore readable tracked inputs and rerun the same command.",
                        retryable=True,
                        details={"exception": type(exc).__name__, "message": str(exc)},
                    ),
                )
            )
            continue
        except Exception as exc:
            checks.append(
                _blocked_check(
                    spec,
                    _error(
                        "internal_error",
                        f"Check '{spec.name}' raised an internal verifier error.",
                        "Report this verifier defect with the exception type and rerun after repair.",
                        retryable=False,
                        details={"exception": type(exc).__name__, "message": str(exc)},
                    ),
                    command=spec.command,
                    duration_ms=round((time.monotonic() - started) * 1000),
                )
            )
            continue
        try:
            result = runner(spec, command, timeout_seconds, repo)
            if not isinstance(result, RunResult):
                raise TypeError("runner must return RunResult")
        except CheckTimeout as exc:
            check = _interrupted_check(
                spec,
                command,
                exc.result,
                kind="check_timeout",
                message=f"Check '{spec.name}' exceeded its per-check timeout.",
                hint="Increase --timeout-seconds only after confirming the check is making progress, then retry.",
                details={"timeout_seconds": timeout_seconds},
                verbose=verbose,
            )
            _persist_interrupted_logs(log_dir, check, exc.result, spec)
            checks.append(check)
            continue
        except OutputLimitExceeded as exc:
            check = _interrupted_check(
                spec,
                command,
                exc.result,
                kind="output_limit_exceeded",
                message=f"Check '{spec.name}' exceeded the output ceiling.",
                hint="Repair the noisy check or run it directly with a private destination, then retry.",
                details={
                    "limit_bytes": MAX_PROCESS_OUTPUT_BYTES,
                    "stdout_bytes": exc.result.stdout_bytes,
                    "stderr_bytes": exc.result.stderr_bytes,
                },
                verbose=verbose,
            )
            _persist_interrupted_logs(log_dir, check, exc.result, spec)
            checks.append(check)
            continue
        except ProcessGroupReapFailed as exc:
            check = _interrupted_check(
                spec,
                command,
                exc.result,
                kind="process_group_reap_failed",
                message=f"Check '{spec.name}' was interrupted but its process group was not proven reaped.",
                hint="Reap the recorded process group before rerunning verification.",
                details={"process_group": "unreaped"},
                verbose=verbose,
            )
            _persist_interrupted_logs(log_dir, check, exc.result, spec)
            checks.append(check)
            continue
        except CheckExecutionFailed as exc:
            check = _interrupted_check(
                spec,
                command,
                exc.result,
                kind="check_execution_error",
                message=f"Check '{spec.name}' could not be started.",
                hint="Restore the resolved executable and retry the same check.",
                details={"execution": "start_failed"},
                verbose=verbose,
            )
            _persist_interrupted_logs(log_dir, check, exc.result, spec)
            checks.append(check)
            continue
        except OutputCaptureFailed as exc:
            check = _interrupted_check(
                spec,
                command,
                exc.result,
                kind="output_capture_failed",
                message=f"Check '{spec.name}' could not establish private output capture.",
                hint="Repair temporary-directory capacity or permissions and retry.",
                details={"capture": "unavailable"},
                verbose=verbose,
            )
            _persist_interrupted_logs(log_dir, check, exc.result, spec)
            checks.append(check)
            continue
        except subprocess.TimeoutExpired as exc:
            partial = RunResult(
                exit_code=2,
                stdout=_timeout_output(exc.stdout),
                stderr=_timeout_output(exc.stderr),
                duration_ms=round((time.monotonic() - started) * 1000),
            )
            check = _blocked_check(
                spec,
                _error(
                    "check_timeout",
                    f"Check '{spec.name}' exceeded its per-check timeout.",
                    "Increase --timeout-seconds only after confirming the check is making progress, then retry.",
                    retryable=True,
                    details={"timeout_seconds": timeout_seconds},
                ),
                command=command,
                duration_ms=partial.duration_ms,
                stdout=partial.stdout,
                stderr=partial.stderr,
                verbose=verbose,
            )
            _persist_interrupted_logs(log_dir, check, partial, spec)
            checks.append(check)
            continue
        except OSError as exc:
            checks.append(
                _blocked_check(
                    spec,
                    _error(
                        "check_execution_error",
                        f"Check '{spec.name}' could not be executed.",
                        "Repair the local execution environment and retry the same check.",
                        retryable=True,
                        details={"exception": type(exc).__name__, "message": str(exc)},
                    ),
                    command=command,
                    duration_ms=round((time.monotonic() - started) * 1000),
                )
            )
            continue
        except Exception as exc:
            checks.append(
                _blocked_check(
                    spec,
                    _error(
                        "internal_error",
                        f"Check '{spec.name}' raised an internal verifier error.",
                        "Report this verifier defect with the exception type and rerun after repair.",
                        retryable=False,
                        details={"exception": type(exc).__name__, "message": str(exc)},
                    ),
                    command=command,
                    duration_ms=round((time.monotonic() - started) * 1000),
                )
            )
            continue
        if result.exit_code in (0, 1):
            check = _completed_check(spec, command, result, verbose)
        else:
            check = _unexpected_exit_check(spec, command, result, verbose)
        if log_dir is not None:
            try:
                _write_check_logs(log_dir, check, result)
            except OSError as exc:
                check["status"] = "blocked"
                check["error"] = _error(
                    "log_write_failed",
                    f"Logs for check '{spec.name}' could not be written.",
                    "Repair --log-dir permissions or rerun without log persistence.",
                    retryable=True,
                    details={"exception": type(exc).__name__, "log_dir": str(log_dir)},
                )
        checks.append(check)
    return checks


def _ensure_verbose_streams(report: dict, verbose: bool) -> None:
    if not verbose:
        return
    empty_stream = _stream("")
    for check in report["checks"]:
        check.setdefault("stdout", dict(empty_stream))
        check.setdefault("stderr", dict(empty_stream))


def _parse_fields(
    parser: argparse.ArgumentParser, args: argparse.Namespace, allowed: Iterable[str]
) -> tuple[str, ...] | None:
    raw = getattr(args, "fields", None)
    if not raw:
        return None
    if args.format != "json":
        parser.error("--fields requires --format json")
    requested = []
    for value in raw:
        requested.extend(field.strip() for field in value.split(",") if field.strip())
    allowed_set = set(allowed)
    unknown = sorted(set(requested) - allowed_set)
    if unknown:
        parser.error("unknown --fields value(s): " + ", ".join(unknown))
    fields = ["schema_version", "verdict"]
    fields.extend(field for field in requested if field not in fields)
    return tuple(fields)


def _project(report: dict, fields: Sequence[str] | None) -> dict:
    if fields is None:
        return report
    return {field: report[field] for field in fields}


def _render_text(report: dict, *, command: str, verbose: bool) -> str:
    if command == "schema":
        lines = [
            f"qLine verifier schema {report['schema_version']}",
            "commands: schema, doctor, run",
            "report schema scope: doctor, run",
        ]
        for check in report["checks"]:
            lines.append(
                f"{check['code']} {check['name']}: {check['purpose']} "
                f"[{check['implementation']}]"
            )
        lines.append("effects: read-only; run may write only to an explicit --log-dir")
        return "\n".join(lines) + "\n"

    lines = [
        f"qLine verification: {report['verdict'].upper()}",
        (
            "summary: "
            f"selected={report['summary']['selected']} "
            f"passed={report['summary']['passed']} "
            f"failed={report['summary']['failed']} "
            f"blocked={report['summary']['blocked']} "
            f"elapsed_ms={report['elapsed_ms']}"
        ),
    ]
    for check in report["checks"]:
        lines.append(
            f"[{check['status'].upper()}] {check['code']} {check['name']} "
            f"exit={check['exit_code']} duration_ms={check['duration_ms']}"
        )
        summary = check["stderr_summary"] or check["stdout_summary"]
        if summary:
            lines.append(f"  summary: {summary}")
        if "error" in check:
            lines.append(
                f"  error: {check['error']['kind']}: {check['error']['message']}"
            )
            lines.append(f"  hint: {check['error']['hint']}")
        if verbose:
            for item in check.get("diagnostics", {}).get("prerequisites", []):
                lines.append(
                    "  prerequisite: "
                    f"{item['prerequisite']} available={str(item['available']).lower()} "
                    f"kind={item['kind']} path={item['path'] or '-'} "
                    f"version={item['version'] or '-'}"
                )
            for stream_name in ("stdout", "stderr"):
                stream = check.get(stream_name)
                if stream and stream["text"]:
                    lines.append(
                        f"  {stream_name} (bytes={stream['bytes']} "
                        f"truncated={str(stream['truncated']).lower()}):"
                    )
                    lines.extend(f"    {line}" for line in stream["text"].splitlines())
    effect = "read-only" if report["effects"]["read_only"] else "writes --log-dir only"
    lines.append(f"effects: {effect}; network=false; destructive=false")
    return "\n".join(lines) + "\n"


def _emit(report: dict, *, command: str, output_format: str, verbose: bool) -> None:
    if output_format == "json":
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(_render_text(report, command=command, verbose=verbose))


def _exit_for(report: dict) -> int:
    return {"pass": 0, "fail": 1, "blocked": 2}[report["verdict"]]


def _ast_child(repo: Path) -> int:
    try:
        tracked = tuple(path for path in _git_tracked(repo) if path.endswith(".py"))
    except (OSError, subprocess.TimeoutExpired) as exc:
        sys.stdout.write(f"unable to enumerate tracked Python files: {exc}\n")
        return 2
    failures = []
    for relative in tracked:
        path = repo / relative
        try:
            source = path.read_bytes()
            compile(source, relative, "exec", dont_inherit=True)
        except (OSError, SyntaxError, ValueError) as exc:
            failures.append(f"{relative}: {type(exc).__name__}: {exc}")
    if failures:
        sys.stdout.write("\n".join(failures) + "\n")
        return 1
    sys.stdout.write(f"AST parsed {len(tracked)} tracked Python files.\n")
    return 0


def _test_integrity_child(repo: Path) -> int:
    try:
        test_shells = _tracked_test_shells(repo)
        python_tests = _tracked_python_tests(repo)
        findings = _test_integrity_findings(repo)
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        sys.stdout.write(f"unable to inspect tracked shell tests: {exc}\n")
        return 2
    if findings:
        for finding in findings:
            sys.stdout.write(
                f"{finding['path']}:{finding['line']}: {finding['kind']}: "
                f"{finding['message']}\n"
            )
        return 1
    sys.stdout.write(
        "Test integrity inspected "
        f"{len(test_shells)} tracked shell and {len(python_tests)} Python test files.\n"
    )
    return 0


def _base_diff_child(repo: Path, *, base_ref: str | None = None) -> int:
    requested = base_ref or os.environ.get("QLINE_BASE_REF")
    if requested is None:
        github_base = os.environ.get("GITHUB_BASE_REF")
        requested = f"refs/remotes/origin/{github_base}" if github_base else "refs/remotes/origin/main"
    candidates = [requested]
    if requested.startswith("refs/remotes/origin/"):
        candidates.append(requested.removeprefix("refs/remotes/origin/"))
    selected = None
    for candidate in candidates:
        probe = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode == 0:
            selected = candidate
            break
    if selected is None:
        sys.stdout.write(f"base ref is unavailable: {requested}\n")
        return 2
    merge_base = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "HEAD", selected],
        capture_output=True,
        text=True,
        check=False,
    )
    if merge_base.returncode != 0 or not merge_base.stdout.strip():
        sys.stdout.write(f"base ref has no merge base with HEAD: {selected}\n")
        return 2
    base = merge_base.stdout.strip()
    diff = subprocess.run(
        ["git", "-C", str(repo), "diff", "--check", f"{base}..HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    sys.stdout.write(diff.stdout)
    if diff.stderr:
        sys.stdout.write(diff.stderr)
    if diff.returncode == 0:
        sys.stdout.write(f"Committed range is whitespace-clean from {selected}.\n")
        return 0
    return 1 if diff.stdout.strip() else 2


def main(
    argv: Sequence[str] | None = None,
    *,
    repo: Path | None = None,
    runner: Runner | None = None,
) -> int:
    args_list = list(argv) if argv is not None else sys.argv[1:]
    if args_list == ["_python_ast"]:
        return _ast_child((repo or Path(__file__).resolve().parents[1]).resolve())
    if args_list == ["_test_integrity"]:
        return _test_integrity_child(
            (repo or Path(__file__).resolve().parents[1]).resolve()
        )
    if args_list == ["_base_diff"]:
        return _base_diff_child(
            (repo or Path(__file__).resolve().parents[1]).resolve()
        )

    parser = _parser()
    args = parser.parse_args(args_list)
    selected = (
        (_CHECK_BY_NAME[args.check],)
        if args.command == "schema" and args.check
        else _select(getattr(args, "check", None))
    )

    if args.command == "schema":
        report = _schema_report(selected)
        fields = _parse_fields(parser, args, report)
        _emit(
            _project(report, fields),
            command=args.command,
            output_format=args.format,
            verbose=args.verbose,
        )
        return 0

    started = time.monotonic()
    repo_path = (repo or Path(__file__).resolve().parents[1]).expanduser().resolve()
    repo_error = _validate_repo(repo_path)
    if repo_error:
        report = _global_blocked(
            repo_error, elapsed_ms=round((time.monotonic() - started) * 1000)
        )
        _ensure_verbose_streams(report, args.verbose)
        fields = _parse_fields(parser, args, report)
        _emit(
            _project(report, fields),
            command=args.command,
            output_format=args.format,
            verbose=args.verbose,
        )
        return 2

    log_dir = None
    if args.command == "run" and args.log_dir is not None:
        try:
            log_dir = _prepare_log_dir(args.log_dir)
        except OSError as exc:
            not_fresh = isinstance(exc, LogDestinationNotFresh)
            report = _global_blocked(
                _error(
                    "log_destination_not_fresh" if not_fresh else "log_write_failed",
                    (
                        "The requested log directory contains prior-run artifacts."
                        if not_fresh
                        else "The requested log directory could not be prepared."
                    ),
                    (
                        "Choose an absent or empty --log-dir so every retained file belongs to this run."
                        if not_fresh
                        else "Choose a writable, non-symlink --log-dir and retry."
                    ),
                    retryable=True,
                    details={"exception": type(exc).__name__, "path": str(args.log_dir)},
                ),
                elapsed_ms=round((time.monotonic() - started) * 1000),
            )
            _ensure_verbose_streams(report, args.verbose)
            fields = _parse_fields(parser, args, report)
            _emit(
                _project(report, fields),
                command=args.command,
                output_format=args.format,
                verbose=args.verbose,
            )
            return 2

    if args.command == "doctor":
        checks = _doctor(selected, verbose=args.verbose)
    else:
        checks = _run_checks(
            selected,
            repo=repo_path,
            runner=runner or _subprocess_runner,
            timeout_seconds=args.timeout_seconds,
            verbose=args.verbose,
            log_dir=log_dir,
        )
    report = _report(
        checks,
        log_dir=log_dir,
        elapsed_ms=round((time.monotonic() - started) * 1000),
    )
    _ensure_verbose_streams(report, args.verbose)
    try:
        _validate_report(report)
    except (TypeError, ValueError) as exc:
        report = _global_blocked(
            _error(
                "internal_error",
                "The verifier produced an invalid internal report.",
                "Report this verifier defect with the exception type and rerun after repair.",
                retryable=False,
                details={"exception": type(exc).__name__, "message": str(exc)},
            ),
            elapsed_ms=round((time.monotonic() - started) * 1000),
            log_dir=log_dir,
        )
        _ensure_verbose_streams(report, args.verbose)

    if log_dir is not None:
        try:
            _write_private(
                log_dir / "report.json",
                json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            )
        except OSError as exc:
            report = _global_blocked(
                _error(
                    "log_write_failed",
                    "The verification report could not be persisted.",
                    "Repair --log-dir permissions or rerun without log persistence.",
                    retryable=True,
                    details={"exception": type(exc).__name__, "log_dir": str(log_dir)},
                ),
                elapsed_ms=round((time.monotonic() - started) * 1000),
                log_dir=log_dir,
            )
            _ensure_verbose_streams(report, args.verbose)

    fields = _parse_fields(parser, args, report)
    output = _project(report, fields)
    _emit(
        output,
        command=args.command,
        output_format=args.format,
        verbose=args.verbose,
    )
    return _exit_for(report)


if __name__ == "__main__":
    raise SystemExit(main())
