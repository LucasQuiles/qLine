# Bead: B04
**Status:** pending
**Type:** implement
**Dependencies:** none
**Scope:** tests/test-statusline.sh
**Cynefin domain:** complicated
**Profile:** BUILD
**Complexity source:** accidental
**Security sensitive:** false
**Decision trace:** docs/sdlc/active/qline-remediation-001/beads/B04-context-bar-tests-decision-trace.md
**Deterministic checks:** [test-suite-run]
**Turbulence:** {L0: 0, L1: 0, L2: 0, L2.5: 0, L2.75: 0}

## Objective
Fix 10 test failures in context bar compound assertions and context overhead tests.

## Failures to Fix

### Group H: Context Bar Compound (3 tests)
- "compound critical+bust": expects `%!\U000f04bf` in result. The alert glyph is now prepended to pills (line 943), not appended after %. Verify actual output format and update assertions.
- "compound warn+bust": same pattern
- "compound normal+bust": same pattern

### Group I: Context Overhead / Color (7 tests)
- "cache busting not degraded": asserts `\U000f04bf` glyph present — check if this is a bash unicode issue or output format change
- "busting critical color": expects specific RGB `38;2;191;97;106` and darkened `38;2;124;63;68` — verify darkening factor. Code uses `_darken_hex(color, 0.55)` at line 905 but test expects 0.65 factor (`124/191 ≈ 0.65`). If factor changed to 0.55, update expected RGB.
- "config thresholds": calls `_try_phase2_transcript(state, {}, sc, cache_warn_rate=0.8, cache_critical_rate=0.3)` — verify this function signature still accepts these kwargs
- "per-segment coloring": expects darkened healthy `38;2;92;122;121` — verify against current `_darken_hex` factor
- "forensics report": calls `generate_overhead_report` from `obs_utils` — may need sys.path to include hooks/ dir
- "A-01b": already covered in B03 (skip here if fixed there)
- "phase2 anchor": calls `_read_transcript_tail` — verify return dict keys

## Input
- Compound tests at lines ~1670-1730
- Cache busting test at lines ~2010-2026
- Busting color test at lines ~2028-2048
- Config thresholds at lines ~2050-2080
- Per-segment coloring at lines ~2102-2118
- Forensics at lines ~2139-2175
- Phase2 anchor at lines ~1809-1845
- `_darken_hex` function in statusline.py (find line)
- `render_context_bar` alert glyph logic at statusline.py:826-968
- `_try_phase2_transcript` signature in context_overhead.py

## Output
- Updated test assertions matching current output format
- All 10 tests passing (or 9 if A-01b fixed in B03)
- Commit

## Evidence Required
Run context bar and overhead test sections showing pass.
