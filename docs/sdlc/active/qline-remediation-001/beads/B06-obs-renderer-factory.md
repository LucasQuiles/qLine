# Bead: B06
**Status:** pending
**Type:** implement
**Dependencies:** B01, B02, B03, B04, B05
**Scope:** src/statusline.py
**Cynefin domain:** complicated
**Profile:** BUILD
**Complexity source:** accidental
**Security sensitive:** false
**Decision trace:** docs/sdlc/active/qline-remediation-001/beads/B06-obs-renderer-factory-decision-trace.md
**Deterministic checks:** [test-suite-run]
**Turbulence:** {L0: 0, L1: 0, L2: 0, L2.5: 0, L2.75: 0}

## Objective
Replace 7 structurally identical `render_obs_*` functions with a data-driven factory pattern, following the existing `_render_system_metric` precedent.

## Current State
Lines 1582-1675 in statusline.py contain 7+2 renderers:

**Simple renderers (7, identical structure):**
- `render_obs_reads` — state key: `obs_reads`, glyph: `\U000f0447`
- `render_obs_writes` — state key: `obs_writes`, glyph: `\U000f064f`
- `render_obs_bash` — state key: `obs_bash`, glyph: `\U000f018d`
- `render_obs_subagents` — state key: `obs_subagents`, glyph: `\U000f0026`
- `render_obs_tasks` — state key: `obs_tasks`, glyph: `\U000f0318`
- `render_obs_compactions` — state key: `obs_compactions`, glyph: `\U000f0520`, prefix: `x`
- `render_obs_prompts` — state key: `obs_prompts`, glyph: `\U000f017a`

**Threshold renderers (2, need warn/crit support):**
- `render_obs_rereads` — state key: `obs_reread_count`, display: `obs_reread_pct`, thresholds
- `render_obs_failures` — state key: `obs_failures`, thresholds

## Approach
1. Create `_render_obs_counter(state, theme, state_key, theme_key, *, display_key=None, prefix="", fmt=None)` that handles both simple and threshold variants
2. Create `_OBS_REGISTRY` dict mapping module names to their config
3. Keep all existing function names as 2-line wrappers (they're layout config references)
4. Threshold variant: pass `warn_threshold`, `critical_threshold` to the factory

## Output
- ~60 lines removed, ~20 lines added (net -40)
- All existing obs tests still pass
- No behavioral change

## Evidence Required
Run full test suite, verify obs module output unchanged.
