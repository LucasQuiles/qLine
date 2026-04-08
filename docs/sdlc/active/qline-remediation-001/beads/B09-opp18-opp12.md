# Bead: B09
**Status:** pending
**Type:** implement
**Dependencies:** B06, B07
**Scope:** hooks/hook_utils.py, src/statusline.py, tests/test-statusline.sh
**Cynefin domain:** complicated
**Profile:** BUILD
**Complexity source:** essential
**Security sensitive:** false
**Decision trace:** docs/sdlc/active/qline-remediation-001/beads/B09-opp18-opp12-decision-trace.md
**Deterministic checks:** [test-suite-run]
**Turbulence:** {L0: 0, L1: 0, L2: 0, L2.5: 0, L2.75: 0}

## Objective
Implement 2 Tier 1 observability backlog items.

## OPP-18: Hook Fault Surfacing in Statusline
- Read `~/.claude/logs/lifecycle-hook-faults.jsonl` (path: `hook_utils._LEDGER_PATH`)
- Count faults from last 60 minutes (scan backward from EOF, fast line scan)
- Expose as `obs_hook_faults` in state dict
- Add to obs module renderers (new `render_obs_hook_faults` or extend existing)
- Cache with same TTL as other obs modules (5s after A-prime fix)
- Add test: write a fault record, verify count in state

## OPP-12: Hook Performance Sidecar
- Instrument `hook_utils.run_fail_open()` with `time.monotonic()` timing
- Write timing record to `metadata/hook_perf.jsonl` in session package
- Add optional `session_id` kwarg to `run_fail_open` (non-breaking, default None)
- When session_id provided: resolve package root, write `{"ts": ..., "hook": ..., "event": ..., "duration_ms": ...}` 
- Don't block on write failure (fail-open contract)
- Add test: mock session with perf write, verify timing record

**Migration note:** Adding session_id kwarg is backward-compatible. Existing callers don't need changes immediately. New/updated hooks can opt in.

## Output
- hook_utils.py: run_fail_open with timing + perf sidecar write
- statusline.py: fault count scanner + renderer
- Tests for both
- Commit

## Evidence Required
Run new + existing tests.
