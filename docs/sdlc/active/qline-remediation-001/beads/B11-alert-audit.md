# Bead: B11
**Status:** pending
**Type:** implement
**Dependencies:** B01, B02, B03, B04, B05
**Scope:** src/statusline.py, src/context_overhead.py, tests/test-statusline.sh
**Cynefin domain:** complicated
**Profile:** BUILD
**Complexity source:** essential
**Security sensitive:** false
**Decision trace:** docs/sdlc/active/qline-remediation-001/beads/B11-alert-audit-decision-trace.md
**Deterministic checks:** [test-suite-run]
**Turbulence:** {L0: 0, L1: 0, L2: 0, L2.5: 0, L2.75: 0}

## Objective
Audit all 8 alert triggers for accuracy and add comprehensive tests.

## Audit Scope

For each trigger at statusline.py:826-900, verify:

1. **bust** (`cache_busting == True`): Verify `_try_phase2_transcript` sets this correctly post-AG-01 fix. Check the busting detection formula: does `cache_creation > cache_read` on consecutive turns correctly detect busting?

2. **expired** (`cache_expired == True`): Verify idle timeout detection. Where is this set? Trace from context_overhead.py.

3. **micro** (`microcompact_suspected == True`): Verify heuristic `drop_ratio < 0.5 and abs_drop > 5000`. Is this set in context_overhead.py? Are thresholds reasonable? Does it fire during normal operation (false positives)?

4. **bloat** (`raw_sys_pct >= sys_crit_t`): Verify `sys_crit_t` is correctly computed. Should represent system overhead > 50% of total context.

5. **heavy** (`total_pct >= crit_t`): Verify `crit_t` uses corrected thresholds from AG-02. Check `compute_context_thresholds()`.

6. **compact** (`tuc <= 10`): Trace `turns_until_compact` calculation. How is `avg_growth` computed? What's the trailing window? Is there divide-by-zero protection?

7. **turns** (`tuc <= 50`): Same as compact, different threshold.

8. **degraded** (`cache_degraded == True`): Verify degradation detection with corrected cache hit rate formula.

## Fixes to Apply

- Fix `/tmp/qline-alert.json` lifecycle: include `session_id`, ignore stale entries from different sessions
- Add cleanup: delete alert file on session end or when alert clears
- Fix any trigger threshold issues discovered during audit

## Tests to Add

New "alerts" section in test harness:
- Each trigger fires correctly with synthetic state
- Priority order: bust overrides all others
- No-alert state clears file
- Session_id mismatch ignored
- Banner timeout behavior (5s onset)

## Output
- Written audit findings per trigger (in bead notes)
- Code fixes for any issues found
- /tmp/qline-alert.json lifecycle improvement
- ~15 new alert-specific tests
- Commit

## Evidence Required
Audit notes + all new tests passing.
