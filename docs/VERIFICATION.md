# Verification

qLine has one verification entrypoint for local development and continuous
integration:

```bash
python3 scripts/verify.py doctor
python3 scripts/verify.py run
```

`doctor` verifies repository access and every selected prerequisite without
running a check. With `--verbose`, it reports a schema-validated prerequisite
inventory: availability, resolved executable or module path, and the Python or
installed module version when available. It does not dump environment variables
or invoke the check commands. `run` executes checks in the fixed registry order below. CI
uses the same commands on macOS with Python 3.10 and 3.12; development Python
packages come from the hashes in `requirements-dev.lock`, generated from the
top-level pins in `requirements-dev.txt`.

For `QLV-005`, the verifier passes its own absolute interpreter path through
`QLINE_TEST_PYTHON`. The shell harness validates that override and fails closed,
so each CI matrix job runs the Python-backed shell assertions with its selected
interpreter. A direct harness invocation without the override retains qLine's
normal highest-supported-version discovery order.

## Checks

| Code | Name | Purpose |
|---|---|---|
| `QLV-001` | `python-ast` | Parse every Git-tracked Python file. |
| `QLV-002` | `ruff` | Run `ruff check --no-cache .`. |
| `QLV-003` | `shellcheck` | Run full default ShellCheck over tracked shell entrypoints. |
| `QLV-004` | `pytest` | Run `hooks/tests`, `src/tests`, and `scripts/tests` without pytest cache. |
| `QLV-005` | `shell-regression` | Run the full shell-first status-line suite. |
| `QLV-006` | `git-diff` | Run `git diff --check`. |
| `QLV-007` | `test-integrity` | Reject masked shell diagnostics and exits, plus wall-clock sleeps and assertion-free tracked Python tests. |
| `QLV-008` | `base-diff` | Run `git diff --check` over every commit since the configured merge base. |
| `QLV-009` | `install-regression` | Run the sandboxed `tests/test-install-core.sh` suite. |

The typed registry in `scripts/verify.py` is the single source for each check's
name, code, command, purpose, severity, expected failure kind, prerequisites,
and effect metadata. The gate deliberately does not enforce physical
deduplication of replay fixture snapshots: those files are independent test
witnesses, not production-code clones.

Run a focused subset by repeating `--check`. Selection never changes registry
order:

```bash
python3 scripts/verify.py run --check python-ast --check pytest
python3 scripts/verify.py doctor --check shellcheck
```

## Output contract

Text is the default, even when stdout is redirected or a pseudo-terminal is
allocated. Select JSON explicitly:

```bash
python3 scripts/verify.py run --format json
python3 scripts/verify.py run --format json --fields summary,effects
python3 scripts/verify.py schema --format json
python3 scripts/verify.py schema ruff --format json
```

`--fields` projects JSON root fields while always retaining `schema_version`
and `verdict`. `schema [check]` is offline discovery: it needs only the running
Python interpreter and never invokes Git, a checker, or the network. Its
`report_schema_scope` field makes explicit that the embedded JSON Schema
validates `doctor` and `run` reports; the discovery document also carries
`report_schema` and `error_kinds` and is not itself a run report.

A completed verification report—including an actionable failed check—is one
schema-valid document on stdout. Stderr remains empty. That separation lets a
caller parse the same report on exit 0 or 1 without merging diagnostic streams.
Invalid command-line use is the exception: `argparse` reports it on stderr and
exits 2 before verification starts.

By default each check includes bounded, high-signal head-and-tail summaries.
`--verbose` adds structured `stdout` and `stderr` objects with byte counts, a
truncation flag, and omitted-byte count. Each stream retains a 32 KiB
head-and-tail window in the report.
The verifier emits no prompts, spinners, terminal-dependent output, or ANSI
escape sequences.

Use `--log-dir` when full child output below the process ceiling must survive
report truncation:

```bash
python3 scripts/verify.py run --verbose --log-dir /tmp/qline-verify
```

The directory must be absent or empty before the run. A non-empty destination
is blocked as `log_destination_not_fresh` before any check runs, so stale logs
or an old `report.json` can never be mistaken for current evidence. The
directory is mode 0700 and its files are mode 0600. Without this option, all
verifier commands are read-only. With it, the named directory is the only write
effect. A read-only run is idempotent. A log-writing run reports
`idempotent: false` because replaying the same command against its now non-empty
destination blocks instead of overwriting evidence. Every check command is
non-destructive and network-free; the machine-readable `effects` object records
the actual mode. Each subprocess writes to a private ephemeral capture directory
while it runs, so report memory stays bounded. A combined stdout/stderr total
above 16 MiB stops and reaps the process group and is blocked as
`output_limit_exceeded`.

## Exit status

| Exit | Verdict | Meaning |
|---|---|---|
| 0 | `pass` | Every selected check completed and passed. |
| 1 | `fail` | Every selected check completed; at least one reported an actionable finding. |
| 2 | `blocked` | At least one result is unavailable or inconclusive. Do not treat it as a pass. |

Only child exit 1 is an actionable check failure. A timeout, missing tool,
execution failure, or an unexpected child exit is blocked and therefore exits
2. This prevents infrastructure faults from being misreported as clean runs.
Each structured error has a stable `kind`, human `message`, actionable `hint`,
`retryable` boolean, and typed `details` object. A timeout terminates and reaps
the whole process group, then retains whatever stdout and stderr the child
produced before expiry in the bounded verbose streams and, when requested, in
the private full-log files. Failure to prove that reap is a distinct blocked
result.

## Error taxonomy

| Kind | Class | Meaning |
|---|---|---|
| `ast_parse_failed` | failure | A tracked Python source did not parse. |
| `lint_failed` | failure | Ruff reported a lint finding. |
| `shell_lint_failed` | failure | ShellCheck reported an error-severity finding. |
| `python_tests_failed` | failure | Pytest completed with failing tests. |
| `shell_regression_failed` | failure | The shell regression suite completed with failures. |
| `diff_check_failed` | failure | `git diff --check` found whitespace errors. |
| `test_integrity_failed` | failure | A tracked test masks subprocess evidence, sleeps on wall time, or lacks an assertion/failure check. |
| `base_diff_failed` | failure | A commit since the configured base contains a whitespace error. |
| `install_regression_failed` | failure | The sandboxed installer suite completed with failures. |
| `prerequisite_missing` | blocked | A required executable or Python package is absent. |
| `check_timeout` | blocked | A check exceeded `--timeout-seconds`. |
| `output_limit_exceeded` | blocked | A check exceeded the combined 16 MiB output ceiling. |
| `output_capture_failed` | blocked | Private file-backed output capture could not be established. |
| `process_group_reap_failed` | blocked | An interrupted process group was not proven terminated and reaped. |
| `repository_unreadable` | blocked | The selected path is not a readable Git worktree. |
| `check_execution_error` | blocked | A check or its tracked inputs could not be opened or launched. |
| `unexpected_check_exit` | blocked | A child exited outside the 0/1 completed-result contract. |
| `log_destination_not_fresh` | blocked | The selected log directory contains artifacts from a prior run. |
| `log_write_failed` | blocked | The optional private log destination could not be written. |
| `internal_error` | blocked | The verifier violated its own result contract. |

## Continuous integration

`.github/workflows/verify.yml` runs on pull requests and pushes to `main`, uses
read-only repository permissions, cancels superseded runs for the same ref, and
sets a job timeout. The checkout and Python setup actions are pinned to full
commit SHAs with their release tags recorded in comments. ShellCheck is
installed before `doctor` and required to report version 0.11.0; Python
dependencies are installed with `--require-hashes` before the same `run`
entrypoint used locally. Homebrew and pip remain networked bootstrap steps, but
an unexpected package version or Python distribution hash fails closed. Once
those prerequisites exist, every verifier check is network-free. CI retains
child output in a matrix-specific directory under `runner.temp` only for the lifetime of the
hosted runner, leaving no untracked files in the checkout. It deliberately does
not upload that directory: full checker and test output
can contain local paths, environment details, or session-derived fixture data,
and an uploaded artifact is a separate public-log privacy surface. The workflow
does not print the JSON report or its stream summaries. It emits only the closed
check code/name/status/error-kind fields and writes the same compact status table
to the job summary. Because this is a public repository, those closed fields are
the complete public diagnostic surface. A missing or invalid
report is emitted as blocked `QLV-000`; the workflow preserves the gate's real
exit status after successful report parsing.

For local shell-test failures, `tests/test-statusline.sh` retains Python stderr in
one mode-0600 temporary diagnostic log and prints it only when an assertion
fails. The exit trap removes the file. This preserves diagnostics without
merging stderr into values whose stdout is under test. `QLV-007` enforces the
corresponding no-masking rule for tracked shell tests and the local Python
sleep/assertion policy. The workstation's broader external integrity scanner
remains an independent adversarial control; its result is not relabeled as QLV-007.

To investigate CI infrastructure problems, use GitHub's documented
[re-run with debug logging](https://docs.github.com/en/actions/monitoring-and-troubleshooting-workflows/enabling-debug-logging)
controls. Do not replace the gate with a hand-picked command or publish the
private log directory. Workflow annotations use GitHub's
[workflow command](https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions)
format and contain only the bounded error message and hint.

## Reuse and consolidation decisions

The repository intentionally has one standard-library verification driver. The
workflow, contributor guide, and pull-request template all invoke that same
registry instead of maintaining separate check lists. Pre-commit, Nox, pytest
JUnit export, and actionlint were considered but are not additional required
layers: qLine keeps a low-dependency local path, the current report already has
a typed machine contract, and duplicating orchestration would create another
source of truth. A pinned actionlint check remains a reasonable future addition
if workflow complexity grows; its absence is not hidden by downloading a tool at
verification runtime. Because actionlint is not a selected check today, its
coverage is unmeasured rather than passed; if an optional scanner is unavailable,
record that scanner result as inconclusive.

### Prior error-catalog compatibility

The April accuracy-overhaul artifacts used broad operator codes. The verifier's
typed contract deliberately refines, rather than silently duplicates, them:

| Prior code | Current representation | Reason |
|---|---|---|
| `QL-VALIDATION-FAIL` | A failing `QLV-*` check plus its specific `*_failed` error kind | Preserves the check identity and remediation instead of collapsing every validation failure. |
| `QL-TOOL-MISSING` | `prerequisite_missing`, verdict `blocked`, exit 2 | Preserves the prior rule that a missing scanner or tool is inconclusive, never clean. |
| `QL-DEPLOY-BLOCKED` | No verifier equivalent | Deployment and live installation are outside this read-only quality gate. |
| `QL-PRICE-UNKNOWN`, `QL-CACHE-DEGRADED`, `QL-LATENCY-BUDGET` | No verifier equivalent | These remain runtime or product-health diagnostics and are not renamed by this branch. |

`QLV-*` therefore names a gate check; `error.kind` names its precise failure or
blocking mechanism. The older `QL-*` runtime/operator vocabulary remains valid
for the separate surfaces that emit it.

## Known boundaries

`QLV-008` uses `QLINE_BASE_REF` when set, then the pull-request base, then
`refs/remotes/origin/main`; an unavailable base blocks rather than silently
checking an empty range. QLV-007 implements the two Python policies that caught
this branch's observed defects, not every rule in the workstation's external
scanner. Private full logs remain unsanitized and must be reviewed before
sharing. These limits are explicit so the gate does not imply wider coverage.

These are quality-gate boundaries. This branch also carries focused runtime
hardening with its own tests: private session alert state, versioned diagnostics,
JSONL parsing, path-safe hook coverage, and additive manifest/sidecar schemas.
Passing QLV-001 through QLV-009 proves those checked source tests; it does not
by itself prove installation or live observability adoption.

These controls follow GitHub's guidance
to [pin actions to full-length commit SHAs](https://docs.github.com/en/actions/reference/security/secure-use)
and to set explicit [least-privilege workflow permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).
