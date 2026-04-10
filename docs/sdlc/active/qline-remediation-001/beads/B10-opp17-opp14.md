# Bead: B10
**Status:** pending
**Type:** implement
**Dependencies:** B06, B07
**Scope:** hooks/obs-session-start.py, src/context_overhead.py, src/statusline.py, tests/test-statusline.sh
**Cynefin domain:** complicated
**Profile:** BUILD
**Complexity source:** essential
**Security sensitive:** false
**Decision trace:** docs/sdlc/active/qline-remediation-001/beads/B10-opp17-opp14-decision-trace.md
**Deterministic checks:** [test-suite-run]
**Turbulence:** {L0: 0, L1: 0, L2: 0, L2.5: 0, L2.75: 0}

## Objective
Implement 2 Tier 1 observability backlog items.

## OPP-17: Hook Coverage Report
- In `hooks/obs-session-start.py` `_scan_inventory()`:
  - Read `~/.claude/settings.json` → extract all hook script paths
  - Compare against known qLine hook list (enumerate hooks/*.py matching obs-*.py pattern)
  - Write coverage section to `session_inventory.json`: `{"hook_coverage": {"registered": [...], "expected": [...], "missing": [...], "extra": [...]}}`
- Add test: mock settings.json with partial hooks, verify coverage report

## OPP-14: Parse Diagnostic Sidecar
- In `src/context_overhead.py`:
  - When `_read_transcript_tail()` encounters malformed JSONL, write to `native/statusline/diagnostics.jsonl`
  - When `_read_transcript_anchor()` encounters malformed JSONL, same
  - Use atomic append pattern (same as obs_utils._atomic_jsonl_append)
  - Record: `{"ts": ..., "source": "transcript_tail|transcript_anchor", "error": ..., "line_preview": ...}`
- In `src/statusline.py`:
  - Expose diagnostic count as optional `obs_parse_errors` state key
  - Only count from current session (bounded by package_root scope)
- Add tests: feed malformed JSONL, verify diagnostic written

## Output
- obs-session-start.py: hook coverage section in inventory
- context_overhead.py: diagnostic logging on parse failure
- statusline.py: optional parse error count
- Tests for both
- Commit

## Evidence Required
Run new + existing tests.
