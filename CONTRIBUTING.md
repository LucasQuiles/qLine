# Contributing to qLine

Use qLine's canonical verification entrypoint for every change. Start with a
read-only prerequisite check, run focused checks while iterating, then run the
full gate before opening or updating a pull request:

```bash
python3 scripts/verify.py doctor
python3 scripts/verify.py run --check python-ast --check pytest
python3 scripts/verify.py run
```

Install the hash-locked development environment with
`python3 -m pip install --require-hashes -r requirements-dev.lock`. The shorter
`requirements-dev.txt` is the reviewed top-level input used to regenerate that lock.

The full check catalog and stable `QLV-*` taxonomy live in
[docs/VERIFICATION.md](docs/VERIFICATION.md). Do not replace the canonical gate
with an ad hoc subset in CI or release evidence.

## Troubleshooting

Ask the tool for its offline contract before guessing at a failure:

```bash
python3 scripts/verify.py schema --format json
python3 scripts/verify.py doctor --verbose
python3 scripts/verify.py run --format json --verbose
```

For child output below the 16 MiB process ceiling, choose a new private log
directory for each run:

```bash
python3 scripts/verify.py run --verbose --log-dir /tmp/qline-verify-$RANDOM
```

The verifier refuses a non-empty log directory so prior output cannot masquerade
as current evidence. Full logs may contain paths, environment details, or
session-derived fixture data. Review them locally and do not publish or upload
them without a privacy review.

Exit 0 is the only passing result. Exit 1 is a completed gate with actionable
findings. Exit 2 is blocked or inconclusive. Preserve stdout and stderr
separately and report the real exit status; a masked, skipped, timed-out, or
otherwise incomplete run is not a pass.

In GitHub Actions, open the failed `QLV-*` annotation and job summary first. If
the runner or dependency bootstrap is suspect, use GitHub's supported re-run
with debug logging control; do not bypass the canonical gate or publish its
private full-log directory.

If a change alters a command's filesystem, network, destructive, or idempotency
effects, update the registry metadata, [docs/VERIFICATION.md](docs/VERIFICATION.md),
and the associated contract tests in the same pull request.
