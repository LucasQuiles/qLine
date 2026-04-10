# Bead: B05
**Status:** pending
**Type:** implement
**Dependencies:** none
**Scope:** tests/test-statusline.sh
**Cynefin domain:** complicated
**Profile:** BUILD
**Complexity source:** accidental
**Security sensitive:** false
**Decision trace:** docs/sdlc/active/qline-remediation-001/beads/B05-obs-hook-tests-decision-trace.md
**Deterministic checks:** [test-suite-run]
**Turbulence:** {L0: 0, L1: 0, L2: 0, L2.5: 0, L2.75: 0}

## Objective
Fix 5 test failures in obs snapshot tests and hook integration test.

## Failures to Fix

### Group G: Obs Snapshot Tests (4 tests)
- T-obs-1: "snapshot appended" — snapshot file not created. Trace `_try_obs_snapshot` to understand why.
  - Test setup: OBS_ROOT="$OBS_TEST_ROOT", session_id in payload, package dir exists
  - Check: does `_try_obs_snapshot` use `resolve_package_root_env`? If so, the OBS_ROOT env should work. If it uses `resolve_package_root` directly, OBS_ROOT won't be honored.
  - Also check: QLINE_NO_COLLECT=1 — does this suppress snapshot writing?
- T-obs-3: "throttle skips duplicate" — throttle logic may have changed
- T-obs-4: "meaningful change bypasses throttle" — related to T-obs-3
- T-obs-6: "no snapshot without session_id" — snapshot written even without session_id

### Group J: Hook Integration (1 test)
- "hook integration": test tries to import from `~/.claude/hooks/obs-stop-cache.py` but hooks are at `$REPO_DIR/hooks/`
- **Fix:** Change the test's sys.path to use `$REPO_DIR/hooks/` instead of `~/.claude/hooks/`

## Input
- T-obs tests at lines ~1411-1470 area
- Hook integration at lines ~2390-2410 area  
- `_try_obs_snapshot` function at statusline.py:1943+
- `QLINE_NO_COLLECT` handling — search for it in statusline.py
- Test setup for obs tests (OBS_TEST_ROOT, OBS_PKG_ROOT vars)

## Output
- Fixed obs snapshot tests (may need code fix if QLINE_NO_COLLECT interferes)
- Fixed hook integration path
- All 5 tests passing
- Commit

## Evidence Required
Run `bash tests/test-statusline.sh --section obs` showing pass.
