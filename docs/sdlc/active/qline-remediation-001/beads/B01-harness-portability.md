# Bead: B01
**Status:** pending
**Type:** implement
**Dependencies:** none
**Scope:** tests/test-statusline.sh
**Cynefin domain:** clear
**Profile:** BUILD
**Complexity source:** accidental
**Security sensitive:** false
**Decision trace:** docs/sdlc/active/qline-remediation-001/beads/B01-harness-portability-decision-trace.md
**Deterministic checks:** [test-suite-run]
**Turbulence:** {L0: 0, L1: 0, L2: 0, L2.5: 0, L2.75: 0}

## Objective
Fix 14 test failures caused by bash 3.2 portability issues and macOS quirks.

## Failures to Fix

### Group A: Bash 3.2 Unicode (3 tests)
- R-02a, R-02b, R-02f: `$'\U000fXXXX'` 8-digit escapes don't work in bash 3.2
- **Fix:** Convert to Python-side assertions. Change from `assert_contains` with bash unicode to `run_py` with Python `assert '\U000fXXXX' in line` then `assert_equals ... "OK"`

### Group C: wc -l Whitespace (2 tests)
- R-13, L-02: macOS `wc -l` pads output with spaces: `"       1"` vs `"1"`
- L-01 also likely affected (check)
- **Fix:** Patch `assert_single_line` helper at line 107: add `| tr -d ' '` after `wc -l`

### Group D: mktemp --suffix (4 tests)
- CF-03a, CF-04a, CF-04b, CF-04c: `mktemp --suffix=.toml` may fail on some macOS
- **Fix:** Replace with `TMPTOML=$(mktemp).toml` or use Python tempfile inside run_py

## Input
- File: `tests/test-statusline.sh` (2448 lines)
- Helper functions at lines 107-168
- R-02 tests at lines ~490-502
- R-13 test at lines ~603-612
- CF-03/04 tests at lines ~650-691
- L-01/L-02 tests need to be found

## Output
- Modified `tests/test-statusline.sh` with all 14 tests passing
- No code changes to src/
- Commit with message describing portability fixes

## Evidence Required
Run `bash tests/test-statusline.sh --section renderer` and `--section config` showing relevant tests pass.
