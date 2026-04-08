# Bead: B02
**Status:** pending
**Type:** implement
**Dependencies:** none
**Scope:** tests/test-statusline.sh
**Cynefin domain:** clear
**Profile:** BUILD
**Complexity source:** accidental
**Security sensitive:** false
**Decision trace:** docs/sdlc/active/qline-remediation-001/beads/B02-glyph-legacy-tests-decision-trace.md
**Deterministic checks:** [test-suite-run]
**Turbulence:** {L0: 0, L1: 0, L2: 0, L2.5: 0, L2.75: 0}

## Objective
Fix 6 test failures caused by glyph changes in layout redesign and legacy stub tests.

## Failures to Fix

### Group B: Glyph Drift (3 tests)
- R-12a: expects `↑12.3k` but `format_tokens` now uses `▲` (U+25B2). Fix: change `↑` to `▲`
- R-12b: expects `↓4.1k` but now uses `▼` (U+25BC). Fix: change `↓` to `▼`
- L-11b: expects `\u229b` (⊛) worktree marker. Verify current glyph and update.

### Group E: Legacy Stub Tests (3 tests)
- "spike at spike": calls `render_cache_delta()` which is a legacy stub returning None. Redirect to `render_cache_pill` or write new test for current API.
- "sys_overhead module": calls `render_sys_overhead()` which is a legacy stub returning None. Redirect to `render_sys_overhead_pill`.
- "phase2 anchor": calls `_read_transcript_tail()`. Check if return format changed or if the function was renamed.

## Input
- R-12 tests at line ~596-601
- L-11b at line ~1306 area (search for L-11b)
- Legacy stub tests at lines ~1769-1845
- Current functions: `render_cache_pill` (line ~1002), `render_sys_overhead_pill` (line ~986), `_read_transcript_tail` (context_overhead.py:288)

## Output
- Modified test expectations matching current API
- All 6 tests passing
- Commit

## Evidence Required
Run affected test sections showing pass.
