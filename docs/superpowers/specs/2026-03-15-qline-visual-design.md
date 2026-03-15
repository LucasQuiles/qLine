# qLine Visual Design Spec

## Summary

Upgrade the qLine status-line renderer from plain ASCII to a styled, TOML-configurable output with ANSI truecolor, Nerd Font glyphs, threshold-based color escalation, and a visual context progress bar.

## Decisions Made

- **Font:** UbuntuSansMono Nerd Font Mono 11 (user's terminal)
- **Palette:** Muted Ocean (Nord-adjacent)
- **Config:** TOML at `~/.config/qline.toml`, stdlib `tomllib`, all optional with embedded defaults
- **No emoji:** Nerd Font glyphs only
- **No network/git/keyring:** Deferred to a follow-up
- **Architecture:** Approach 2 — TOML-driven theming in `statusline.py`

## Module Layout

Fixed order, absent modules omitted, dim `│` separator:

```
 Opus │  qLine │  ████████░░ 80% │ ↑12.3k ↓4.1k │  $0.42 │  1m30s
```

Modules:
1. **model** — Claude model display name
2. **dir** — Basename of working directory
3. **context_bar** — Visual progress bar of context window usage
4. **tokens** — Input/output token counts (↑ in, ↓ out)
5. **cost** — Session cost in USD
6. **duration** — Session wall-clock time

## Glyphs

| Module | Glyph | Codepoint | Nerd Font Name |
|--------|-------|-----------|----------------|
| model | `` | U+F46A | nf-oct-hubot |
| dir | `` | U+F07C | nf-fa-folder_open |
| context_bar | `` | U+F200 | nf-fa-pie_chart |
| cost | `` | U+F0E7 | nf-fa-bolt |
| duration | `` | U+F017 | nf-fa-clock_o |

The tokens module has no prefix glyph. Directional arrows `↑` (U+2191) and `↓` (U+2193) are part of the formatted value, not a module prefix.

## Color Theme — Muted Ocean

| Element | Hex | Style | Notes |
|---------|-----|-------|-------|
| Model name | `#88c0d0` | bold | Primary accent, always bold |
| Directory | `#81a1c1` | normal | Secondary info, subdued |
| Context bar (normal) | `#a3be8c` | normal | Healthy (<40%) |
| Context bar (warn) | `#ebcb8b` | normal | Warning (>=40%) |
| Context bar (critical) | `#bf616a` | bold | Critical (>=70%) |
| Tokens | `#8fbcbb` | normal | Informational |
| Cost (normal) | `#d08770` | normal | Distinct from other modules |
| Cost (warn) | `#ebcb8b` | normal | Warning (>=$2.00) |
| Cost (critical) | `#bf616a` | bold | Critical (>=$5.00) |
| Duration | `#6e8898` | normal | Lowest priority, recedes |
| Separator │ | — | dim | ANSI SGR dim attribute |

## Progress Bar

- Bar width: 10 characters (configurable via `width`). This is bar-only width; the percentage suffix is appended outside the bar.
- Filled: `█` (U+2588 Full Block)
- Empty: `░` (U+2591 Light Shade)
- Percentage source: `context_window.used / context_window.total`, using integer floor division (matches existing behavior)
- Percentage appended after bar: `80%`
- Suffix: `~` at warn threshold, `!` at critical threshold
- This module **replaces** the old `_format_context()` text-only renderer (`ctx:75%~`). The old function is removed.

## Token Count Formatting

- Abbreviated: `12.3k`, `1.2M`, `456` (raw if <1000)
- Input prefix: `↑`, output prefix: `↓`
- Source fields (within `context_window` object): `total_input_tokens`, `total_output_tokens`
- These are runtime-added fields (version-sensitive), not in the original statusline docs
- Fallback: omit module if either field is absent or not a number
- Zero counts: omit module when both are 0

## Threshold Defaults

| Module | Warn | Critical |
|--------|------|----------|
| context_bar | 40% | 70% |
| cost | $2.00 | $5.00 |

These thresholds **replace** the existing `CONTEXT_WARN_PCT=70` and `CONTEXT_CRITICAL_PCT=85` constants. Existing renderer tests that assert at the old thresholds must be updated. Cost thresholds are new — cost escalation changes color only (no text suffix).

## TOML Config (`~/.config/qline.toml`)

All keys optional. Any failure during config read (missing file, malformed TOML, permission denied, symlink to nonexistent target, any `OSError` or `tomllib.TOMLDecodeError`) = use embedded defaults silently. Invalid hex color values = fall back to default color for that element.

**Merge semantics:** Shallow per-section merge. If a user provides `[context_bar]` with only `color`, all other `context_bar` keys (width, thresholds, etc.) retain their defaults. Top-level sections not present in the user file are entirely default.

**Bold at thresholds:** Bold is always applied at critical threshold regardless of TOML config. The `bold` key in TOML controls the module's normal-state boldness only.

```toml
[model]
glyph = " "
color = "#88c0d0"
bold = true

[dir]
glyph = " "
color = "#81a1c1"

[context_bar]
glyph = " "
color = "#a3be8c"
width = 10
warn_threshold = 40.0
warn_color = "#ebcb8b"
critical_threshold = 70.0
critical_color = "#bf616a"

[tokens]
color = "#8fbcbb"

[cost]
glyph = " "
color = "#d08770"
warn_threshold = 2.0
warn_color = "#ebcb8b"
critical_threshold = 5.0
critical_color = "#bf616a"

[duration]
glyph = " "
color = "#6e8898"

[separator]
char = "│"
dim = true
```

## Architecture Changes

### New in `statusline.py`

- `load_config()` — reads `~/.config/qline.toml` via `tomllib`, merges over `DEFAULT_THEME` dict. Returns defaults on any failure.
- `style(text, hex_color, bold=False)` — wraps text in ANSI truecolor escape sequences. Returns plain text if color is None.
- `render_bar(pct, width, theme)` — renders `████████░░` with threshold-aware coloring.
- `format_tokens(input_tokens, output_tokens, theme)` — formats `↑12.3k ↓4.1k` from context_window token fields.
- Updated `render()` — uses theme dict for glyphs, colors, separators. Calls `style()` per module.
- Updated `normalize()` — extracts `total_input_tokens` and `total_output_tokens` from context_window.

### Unchanged

- `read_stdin_bounded()` — no changes
- `main()` entrypoint — adds `load_config()` call before render
- Exit behavior — still exit 0 on all recoverable failures
- No changes to `hook_utils.py`

### Test Updates

- Existing parser tests: unchanged
- Existing normalizer tests: add token extraction tests
- Renderer tests: update expected output for new thresholds and bar format; test under `NO_COLOR=1` for deterministic plain-text assertions
- New tests: config loading (missing file, malformed, partial override, full override)
- New tests: bar rendering, token formatting, threshold color selection
- Command tests: pipe fixture JSON, verify ANSI output or plain output under `NO_COLOR=1`

### `NO_COLOR` Convention

Respect the `NO_COLOR` environment variable (https://no-color.org/). When set, emit plain ASCII output (current baseline behavior). This also makes testing deterministic without stripping ANSI codes.

## Constraints Preserved

- Single stdout line or empty output
- No stderr on normal execution
- Exit 0 on recoverable failures
- No network, keyring, shell, or git access
- One bounded stdin read
- Byte-capped input (512KB)
- 200ms read deadline

## Deferred

- Git branch display (`.git/HEAD` read)
- Usage limits (API + keyring + cache)
- Hook health badge
- `--explain` debug surface
- Multi-line layout
