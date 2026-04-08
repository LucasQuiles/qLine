# Bead: B03
**Status:** pending
**Type:** implement
**Dependencies:** none
**Scope:** tests/test-statusline.sh, src/statusline.py
**Cynefin domain:** clear
**Profile:** BUILD
**Complexity source:** accidental
**Security sensitive:** false
**Decision trace:** docs/sdlc/active/qline-remediation-001/beads/B03-stale-ansi-tests-decision-trace.md
**Deterministic checks:** [test-suite-run]
**Turbulence:** {L0: 0, L1: 0, L2: 0, L2.5: 0, L2.75: 0}

## Objective
Fix 6 test failures related to stale data dimming and ANSI color output.

## Failures to Fix

### Group F: Stale Dimming (5 tests)
- STALE-01: `render_cpu` with `cpu_stale=True` — expects `\033[2m` in output
- STALE-03: `render_dir` with stale git
- STALE-04: `render_tmux` stale
- STALE-05: `render_agents` stale
- STALE-06: `render_memory` stale

**Root cause investigation needed:**
1. Tests use `python3 -c` directly (not `run_py`), so NO_COLOR should be unset
2. Check if `_render_system_metric()` (~line 1415) passes `dim=is_stale` to `_pill()`
3. Check if `render_dir` supports stale dimming
4. If `_render_system_metric` doesn't support dim, ADD dim support (code fix)
5. If tests are running under NO_COLOR for another reason, fix the test invocation

### ANSI Test (1 test)
- A-01b: `run_statusline_color` should produce ANSI escapes, but test fails
- Check: does `statusline.py main()` check `sys.stdout.isatty()`? If so, piping to file would suppress ANSI even without NO_COLOR
- Fix: either force color output via env var, or change the test to use `run_py_color` with direct function call

## Input
- STALE tests at lines ~1306-1370
- A-01b at line ~705
- `_render_system_metric` at statusline.py ~1415
- `_pill` function at statusline.py ~630
- `style_dim` function in statusline.py (find it)
- NO_COLOR variable initialization in statusline.py

## Output
- Fix code if `_render_system_metric` missing dim support
- Fix tests if invocation environment is wrong
- All 6 tests passing
- Commit

## Evidence Required
Run `bash tests/test-statusline.sh --section stale` and `--section ansi` showing pass.
