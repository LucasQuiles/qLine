# Bead: B07
**Status:** pending
**Type:** implement
**Dependencies:** B01, B02, B03, B04, B05
**Scope:** hooks/obs_utils.py, src/statusline.py
**Cynefin domain:** clear
**Profile:** BUILD
**Complexity source:** accidental
**Security sensitive:** false
**Decision trace:** docs/sdlc/active/qline-remediation-001/beads/B07-overhead-report-shim-decision-trace.md
**Deterministic checks:** [test-suite-run]
**Turbulence:** {L0: 0, L1: 0, L2: 0, L2.5: 0, L2.75: 0}

## Objective
Two small dedup cleanups:
1. Wire `generate_overhead_report` through `extract_usage_full`
2. Remove statusline.py compatibility shim for `resolve_package_root_env`

## Task A: Wire generate_overhead_report

**Current:** `generate_overhead_report` at obs_utils.py:448-484 has inline usage extraction duplicating `extract_usage_full` (obs_utils.py:566-594).

**Change:** Replace the inline extraction loop with:
```python
usage, _, _, _ = extract_usage_full(entry)
if usage is not None:
    turns.append(usage)
```

This eliminates ~12 lines of duplicated message/toolUseResult branching.

## Task B: Remove statusline.py compatibility shim

**Check first:** Find where statusline.py has an inline fallback for `resolve_package_root_env`. If `_OBS_AVAILABLE` is False, the shim runs. Verify that obs_utils is always importable via the plugin symlink.

**If safe:** Remove the inline fallback and simplify to always using the imported function.

## Output
- obs_utils.py: `generate_overhead_report` uses `extract_usage_full` 
- statusline.py: shim removed (if safe)
- All tests pass
- Commit

## Evidence Required
Run forensics report test + full suite to verify no regression.
