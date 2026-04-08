# Bead: B08
**Status:** pending
**Type:** implement
**Dependencies:** B06, B07
**Scope:** hooks/obs_utils.py, hooks/obs-precompact.py, src/statusline.py, tests/test-statusline.sh
**Cynefin domain:** complicated
**Profile:** BUILD
**Complexity source:** essential
**Security sensitive:** false
**Decision trace:** docs/sdlc/active/qline-remediation-001/beads/B08-opp15-opp16-opp25-decision-trace.md
**Deterministic checks:** [test-suite-run]
**Turbulence:** {L0: 0, L1: 0, L2: 0, L2.5: 0, L2.75: 0}

## Objective
Implement 3 related Tier 1 backlog items.

## OPP-15: Package Schema Version in Manifest
- Add `"schema_version": "1.0.0"` to initial manifest in `create_package()` (obs_utils.py ~line 160 area)
- One-line addition to the manifest dict
- Add test: verify create_package output contains schema_version

## OPP-16: Compaction Anchor Invalidation Event
- In `hooks/obs-precompact.py` `main()`: after existing compaction handling, emit `compact.anchor_invalidated` event via `append_event()`
- In `src/statusline.py` `_inject_obs_counters()`: detect compaction count increase from session cache, clear `overhead_ts` and `turn_1_anchor` from session cache when compaction detected
- Add test: simulate compaction, verify event emitted and cache cleared

## OPP-25: Transcript Schema Validation in Tests
- Add new test section in `tests/test-statusline.sh`
- Select 3 representative replay files from `tests/replay/`
- Run `_read_transcript_tail`, `_read_transcript_anchor`, and `extract_usage_full` against them
- Verify field presence/types in returned data

## Output
- 3 OPP items implemented with tests
- All existing + new tests pass
- Commit

## Evidence Required
Run new tests + full suite.
