#!/bin/bash
# Shell-first test harness for qLine statusline.py
# Follows the assertion style from ~/.claude/tests/test-hook-utils.sh
#
# All renderer/command tests run under NO_COLOR=1 for deterministic
# plain-text assertions. ANSI output is tested separately.
#
# Usage:
#   bash tests/test-statusline.sh                    # run all sections
#   bash tests/test-statusline.sh --section parser   # run one section
#   bash tests/test-statusline.sh --section normalizer
#   bash tests/test-statusline.sh --section renderer
#   bash tests/test-statusline.sh --section command
#   bash tests/test-statusline.sh --section config
#   bash tests/test-statusline.sh --section ansi
#   bash tests/test-statusline.sh --section layout
#   bash tests/test-statusline.sh --section collector
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SRC="$REPO_DIR/src/statusline.py"
FIXTURES="$SCRIPT_DIR/fixtures/statusline"

PASS=0
FAIL=0
TOTAL=0

# --- Assertion helpers ---

assert_equals() {
    local label="$1" actual="$2" expected="$3"
    TOTAL=$((TOTAL + 1))
    if [ "$actual" = "$expected" ]; then
        echo "  PASS: $label"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $label"
        echo "    expected: '$expected'"
        echo "    got:      '$actual'"
        FAIL=$((FAIL + 1))
    fi
}

assert_contains() {
    local label="$1" output="$2" expected="$3"
    TOTAL=$((TOTAL + 1))
    if printf '%s' "$output" | grep -Fq -- "$expected"; then
        echo "  PASS: $label"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $label (expected '$expected' in output)"
        FAIL=$((FAIL + 1))
    fi
}

assert_not_contains() {
    local label="$1" output="$2" unexpected="$3"
    TOTAL=$((TOTAL + 1))
    if printf '%s' "$output" | grep -Fq -- "$unexpected"; then
        echo "  FAIL: $label (unexpected '$unexpected' found in output)"
        FAIL=$((FAIL + 1))
    else
        echo "  PASS: $label"
        PASS=$((PASS + 1))
    fi
}

assert_empty() {
    local label="$1" output="$2"
    TOTAL=$((TOTAL + 1))
    if [ -z "$output" ]; then
        echo "  PASS: $label"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $label (expected empty, got: $(echo "$output" | head -1))"
        FAIL=$((FAIL + 1))
    fi
}

assert_exit_zero() {
    local label="$1" exit_code="$2"
    TOTAL=$((TOTAL + 1))
    if [ "$exit_code" = "0" ]; then
        echo "  PASS: $label"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $label (expected exit 0, got $exit_code)"
        FAIL=$((FAIL + 1))
    fi
}

assert_single_line() {
    local label="$1" output="$2"
    TOTAL=$((TOTAL + 1))
    if [ -z "$output" ]; then
        echo "  PASS: $label (empty output)"
        PASS=$((PASS + 1))
        return
    fi
    local line_count
    line_count=$(printf '%s\n' "$output" | wc -l)
    if [ "$line_count" = "1" ]; then
        echo "  PASS: $label"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $label (expected 1 line, got $line_count)"
        FAIL=$((FAIL + 1))
    fi
}

# Helper: run statusline with NO_COLOR and capture stdout/stderr/exit
run_statusline() {
    local input="$1"
    local tmpout tmpderr
    tmpout=$(mktemp)
    tmpderr=$(mktemp)
    printf '%s' "$input" | NO_COLOR=1 QLINE_NO_COLLECT=1 python3 "$SRC" >"$tmpout" 2>"$tmpderr"
    local exit_code=$?
    LAST_STDOUT=$(cat "$tmpout")
    LAST_STDERR=$(cat "$tmpderr")
    LAST_EXIT=$exit_code
    rm -f "$tmpout" "$tmpderr"
}

# Helper: run statusline WITH colors (no NO_COLOR)
run_statusline_color() {
    local input="$1"
    local tmpout tmpderr
    tmpout=$(mktemp)
    tmpderr=$(mktemp)
    printf '%s' "$input" | QLINE_NO_COLLECT=1 python3 "$SRC" >"$tmpout" 2>"$tmpderr"
    local exit_code=$?
    LAST_STDOUT=$(cat "$tmpout")
    LAST_STDERR=$(cat "$tmpderr")
    LAST_EXIT=$exit_code
    rm -f "$tmpout" "$tmpderr"
}

# Helper: run a Python snippet importing from statusline
run_py() {
    NO_COLOR=1 python3 -c "
import sys; sys.path.insert(0, '$REPO_DIR/src')
$1
" 2>&1
}

# Determine which sections to run
RUN_SECTION="${2:-all}"
if [ "${1:-}" = "--section" ] && [ -n "${2:-}" ]; then
    RUN_SECTION="$2"
fi

echo "=== qLine StatusLine Tests ==="
echo "Source: $SRC"
echo "Section: $RUN_SECTION"
echo ""

# ======================================================================
# SECTION: parser — bounded reader tests
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "parser" ]; then
echo "--- Parser / Reader Tests ---"

# P-01: Empty stdin returns None
OUT=$(run_py "
from statusline import read_stdin_bounded
import os
r, w = os.pipe()
os.close(w)
os.dup2(r, 0)
result = read_stdin_bounded()
print('NONE' if result is None else 'NOT_NONE')
")
assert_equals "P-01: empty stdin returns None" "$OUT" "NONE"

# P-02: Malformed JSON returns None
OUT=$(run_py "
from statusline import read_stdin_bounded
import os
r, w = os.pipe()
os.write(w, b'not json at all')
os.close(w)
os.dup2(r, 0)
result = read_stdin_bounded()
print('NONE' if result is None else 'NOT_NONE')
")
assert_equals "P-02: malformed JSON returns None" "$OUT" "NONE"

# P-03: Non-object JSON (array) returns None
OUT=$(run_py "
from statusline import read_stdin_bounded
import os
r, w = os.pipe()
os.write(w, b'[1, 2, 3]')
os.close(w)
os.dup2(r, 0)
result = read_stdin_bounded()
print('NONE' if result is None else 'NOT_NONE')
")
assert_equals "P-03: non-object JSON returns None" "$OUT" "NONE"

# P-04: Non-object JSON (string) returns None
OUT=$(run_py "
from statusline import read_stdin_bounded
import os
r, w = os.pipe()
os.write(w, b'\"hello\"')
os.close(w)
os.dup2(r, 0)
result = read_stdin_bounded()
print('NONE' if result is None else 'NOT_NONE')
")
assert_equals "P-04: non-object JSON (string) returns None" "$OUT" "NONE"

# P-05: Valid JSON object returns dict
OUT=$(run_py "
from statusline import read_stdin_bounded
import os
r, w = os.pipe()
os.write(w, b'{\"key\": \"value\"}')
os.close(w)
os.dup2(r, 0)
result = read_stdin_bounded()
print('DICT' if isinstance(result, dict) else 'NOT_DICT')
")
assert_equals "P-05: valid JSON object returns dict" "$OUT" "DICT"

# P-06: Byte cap enforcement
OUT=$(run_py "
from statusline import read_stdin_bounded, MAX_STDIN_BYTES
import os, tempfile
with tempfile.NamedTemporaryFile(delete=False) as f:
    fname = f.name
    f.write(b'{\"k\":\"' + b'A' * (MAX_STDIN_BYTES + 100) + b'\"}')
fd = os.open(fname, os.O_RDONLY)
os.dup2(fd, 0)
os.close(fd)
result = read_stdin_bounded()
os.unlink(fname)
print('NONE' if result is None else 'NOT_NONE')
")
assert_equals "P-06: oversize input returns None (truncated)" "$OUT" "NONE"

# P-07: Malformed bytes handled
OUT=$(run_py "
from statusline import read_stdin_bounded
import os
r, w = os.pipe()
os.write(w, b'{\"k\": \"val\xc0\xc1ue\"}')
os.close(w)
os.dup2(r, 0)
result = read_stdin_bounded()
if result is not None:
    print('DICT_WITH_REPLACEMENT')
else:
    print('NONE')
")
TOTAL=$((TOTAL + 1))
if [ "$OUT" = "DICT_WITH_REPLACEMENT" ] || [ "$OUT" = "NONE" ]; then
    echo "  PASS: P-07: malformed bytes handled without crash ($OUT)"
    PASS=$((PASS + 1))
else
    echo "  FAIL: P-07: malformed bytes caused unexpected result ($OUT)"
    FAIL=$((FAIL + 1))
fi

# P-08: Command exits 0 on empty stdin
run_statusline ""
assert_exit_zero "P-08: exit 0 on empty stdin" "$LAST_EXIT"
assert_empty "P-08b: no stdout on empty stdin" "$LAST_STDOUT"
assert_empty "P-08c: no stderr on empty stdin" "$LAST_STDERR"

# P-09: Command exits 0 on malformed JSON
run_statusline "not json"
assert_exit_zero "P-09: exit 0 on malformed JSON" "$LAST_EXIT"
assert_empty "P-09b: no stdout on malformed JSON" "$LAST_STDOUT"
assert_empty "P-09c: no stderr on malformed JSON" "$LAST_STDERR"

echo ""
fi

# ======================================================================
# SECTION: normalizer
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "normalizer" ]; then
echo "--- Normalizer Tests ---"

# N-01: Full payload
OUT=$(run_py "
from statusline import normalize
import json
payload = json.load(open('$FIXTURES/valid-full.json'))
state = normalize(payload)
print(state.get('model_name', ''))
print(state.get('dir_basename', ''))
print(state.get('version', ''))
print(state.get('output_style', ''))
print(state.get('cost_usd', ''))
print(state.get('duration_ms', ''))
")
assert_contains "N-01a: model_name extracted" "$OUT" "Opus"
assert_contains "N-01b: dir_basename extracted" "$OUT" "qLine"
assert_contains "N-01c: version extracted" "$OUT" "2.1.76"
assert_contains "N-01d: output_style extracted" "$OUT" "default"
assert_contains "N-01e: cost_usd extracted" "$OUT" "1.23456"
assert_contains "N-01f: duration_ms extracted" "$OUT" "45000"

# N-02: Minimal payload
OUT=$(run_py "
from statusline import normalize
import json
payload = json.load(open('$FIXTURES/valid-minimal.json'))
state = normalize(payload)
print(state.get('model_name', 'MISSING'))
print('DIR:' + state.get('dir_basename', 'NONE'))
print('COST:' + str(state.get('cost_usd', 'NONE')))
")
assert_contains "N-02a: model_name from minimal" "$OUT" "Opus"
assert_contains "N-02b: no dir in minimal" "$OUT" "DIR:NONE"
assert_contains "N-02c: no cost in minimal" "$OUT" "COST:NONE"

# N-03: cwd fallback
OUT=$(run_py "
from statusline import normalize
import json
payload = json.load(open('$FIXTURES/valid-no-workspace.json'))
state = normalize(payload)
print(state.get('dir_basename', 'MISSING'))
")
assert_equals "N-03: cwd fallback for dir" "$OUT" "myapp"

# N-04: context_window
OUT=$(run_py "
from statusline import normalize
import json
payload = json.load(open('$FIXTURES/valid-with-context-window.json'))
state = normalize(payload)
print(state.get('context_used', 'MISSING'))
print(state.get('context_total', 'MISSING'))
")
assert_contains "N-04a: context_used" "$OUT" "75000"
assert_contains "N-04b: context_total" "$OUT" "100000"

# N-05: Optional fields
OUT=$(run_py "
from statusline import normalize
import json
payload = json.load(open('$FIXTURES/valid-optional-fields.json'))
state = normalize(payload)
print('WT:' + str(state.get('is_worktree', 'MISSING')))
print('AGENT:' + state.get('agent_id', 'MISSING'))
print('ADDED:' + str(len(state.get('added_dirs', []))))
")
assert_contains "N-05a: worktree flag" "$OUT" "WT:True"
assert_contains "N-05b: agent_id" "$OUT" "AGENT:agent-xyz-123"
assert_contains "N-05c: added_dirs count" "$OUT" "ADDED:1"

# N-06: Wrong-type optionals ignored
OUT=$(run_py "
from statusline import normalize
import json
payload = json.load(open('$FIXTURES/wrong-type-optionals.json'))
state = normalize(payload)
print('COST:' + str(state.get('cost_usd', 'ABSENT')))
print('CTX:' + str(state.get('context_used', 'ABSENT')))
print('ADDED:' + str(state.get('added_dirs', 'ABSENT')))
print('MODEL:' + state.get('model_name', 'PRESENT'))
")
assert_contains "N-06a: wrong-type cost ignored" "$OUT" "COST:ABSENT"
assert_contains "N-06b: wrong-type context ignored" "$OUT" "CTX:ABSENT"
assert_contains "N-06c: wrong-type added_dirs ignored" "$OUT" "ADDED:ABSENT"
assert_contains "N-06d: model still extracted" "$OUT" "MODEL:Opus"

# N-07: Empty dict
OUT=$(run_py "
from statusline import normalize
state = normalize({})
print(len(state))
")
assert_equals "N-07: empty dict yields empty state" "$OUT" "0"

# N-08: Unknown fields ignored
OUT=$(run_py "
from statusline import normalize
state = normalize({'unknown_future_field': 42, 'model': {'display_name': 'Test'}})
print('UNKNOWN:' + str(state.get('unknown_future_field', 'ABSENT')))
print('MODEL:' + state.get('model_name', 'MISSING'))
")
assert_contains "N-08a: unknown field ignored" "$OUT" "UNKNOWN:ABSENT"
assert_contains "N-08b: known field extracted" "$OUT" "MODEL:Test"

# N-09: Token counts extracted
OUT=$(run_py "
from statusline import normalize
import json
payload = json.load(open('$FIXTURES/valid-with-tokens.json'))
state = normalize(payload)
print('IN:' + str(state.get('input_tokens', 'ABSENT')))
print('OUT:' + str(state.get('output_tokens', 'ABSENT')))
")
assert_contains "N-09a: input_tokens extracted" "$OUT" "IN:12345"
assert_contains "N-09b: output_tokens extracted" "$OUT" "OUT:4100"

# N-10: Zero tokens omitted
OUT=$(run_py "
from statusline import normalize
state = normalize({'context_window': {'used': 100, 'total': 1000, 'total_input_tokens': 0, 'total_output_tokens': 0}})
print('IN:' + str(state.get('input_tokens', 'ABSENT')))
")
assert_contains "N-10: zero tokens omitted" "$OUT" "IN:ABSENT"

# N-11: Token counts absent when fields missing
OUT=$(run_py "
from statusline import normalize
state = normalize({'context_window': {'used': 100, 'total': 1000}})
print('IN:' + str(state.get('input_tokens', 'ABSENT')))
")
assert_contains "N-11: tokens absent when fields missing" "$OUT" "IN:ABSENT"

echo ""
fi

# ======================================================================
# SECTION: renderer — under NO_COLOR for plain text assertions
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "renderer" ]; then
echo "--- Renderer Tests (NO_COLOR) ---"

# R-01: Empty state
OUT=$(run_py "
from statusline import render
print(repr(render({})))
")
assert_equals "R-01: empty state -> empty string" "$OUT" "''"

# R-02: Full state — module order with glyphs
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
state = {
    'model_name': 'Opus',
    'dir_basename': 'qLine',
    'context_used': 50000,
    'context_total': 100000,
    'input_tokens': 12345,
    'output_tokens': 4100,
    'cost_usd': 1.23,
    'duration_ms': 45000,
}
line = render(state, DEFAULT_THEME)
print(line)
")
# Glyphs are present but NO_COLOR strips ANSI
assert_contains "R-02a: model with glyph" "$OUT" $'\U000f06a9 Opus'
assert_contains "R-02b: dir with glyph" "$OUT" $'\U000f0770 qLine'
assert_contains "R-02c: bar present" "$OUT" "50%"
assert_contains "R-02d: tokens present" "$OUT" "12.3k"
assert_contains "R-02e: cost with glyph" "$OUT" '$ 1.23'
assert_contains "R-02f: duration with glyph" "$OUT" $'\U000f0954 45s'
assert_contains "R-02g: separator" "$OUT" "│"

# R-03: Missing modules omitted
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
state = {'model_name': 'Opus', 'cost_usd': 0.50}
line = render(state, DEFAULT_THEME)
# Should have model and cost but not dir/context/tokens/duration
print(line)
")
assert_contains "R-03a: model present" "$OUT" "Opus"
assert_contains "R-03b: cost present" "$OUT" '0.50'
assert_not_contains "R-03c: no bar" "$OUT" "░"

# R-04: Model-only
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
line = render({'model_name': 'Sonnet'}, DEFAULT_THEME)
print(line)
")
assert_contains "R-04: model-only has glyph" "$OUT" "Sonnet"
assert_not_contains "R-04b: no separator" "$OUT" "│"

# R-05: Context bar warn at new threshold (>=40%)
OUT=$(run_py "
from statusline import render_bar, DEFAULT_THEME
print(render_bar(45, DEFAULT_THEME))
")
assert_contains "R-05: warn suffix at 45%" "$OUT" "45%~"

# R-06: Context bar critical at new threshold (>=70%)
OUT=$(run_py "
from statusline import render_bar, DEFAULT_THEME
print(render_bar(90, DEFAULT_THEME))
")
assert_contains "R-06: critical suffix at 90%" "$OUT" "90%!"

# R-07: Context bar normal (<40%)
OUT=$(run_py "
from statusline import render_bar, DEFAULT_THEME
print(render_bar(30, DEFAULT_THEME))
")
assert_contains "R-07a: normal at 30%" "$OUT" "30%"
assert_not_contains "R-07b: no warn suffix" "$OUT" "~"
assert_not_contains "R-07c: no critical suffix" "$OUT" "!"

# R-08: Bar characters
OUT=$(run_py "
from statusline import render_bar, DEFAULT_THEME
bar = render_bar(50, DEFAULT_THEME)
print(bar)
")
assert_contains "R-08a: filled blocks" "$OUT" "█████"
assert_contains "R-08b: empty blocks" "$OUT" "░░░░░"

# R-09: Cost formatting
OUT=$(run_py "
from statusline import _format_cost
print(_format_cost(0.001))
print(_format_cost(5.50))
")
assert_contains "R-09a: small cost" "$OUT" '0.0010'
assert_contains "R-09b: normal cost" "$OUT" '5.50'

# R-10: Duration formatting
OUT=$(run_py "
from statusline import _format_duration
print(_format_duration(30000))
print(_format_duration(150000))
print(_format_duration(7200000))
print(_format_duration(5400000))
")
assert_contains "R-10a: seconds" "$OUT" "30s"
assert_contains "R-10b: minutes" "$OUT" "2m30s"
assert_contains "R-10c: hours" "$OUT" "2h"
assert_contains "R-10d: hours+min" "$OUT" "1h30m"

# R-11: Token abbreviation
OUT=$(run_py "
from statusline import _abbreviate_count
print(_abbreviate_count(456))
print(_abbreviate_count(1234))
print(_abbreviate_count(12345))
print(_abbreviate_count(1234567))
")
assert_equals "R-11a: raw count" "$(echo "$OUT" | sed -n '1p')" "456"
assert_equals "R-11b: 1.2k" "$(echo "$OUT" | sed -n '2p')" "1.2k"
assert_equals "R-11c: 12.3k" "$(echo "$OUT" | sed -n '3p')" "12.3k"
assert_equals "R-11d: 1.2M" "$(echo "$OUT" | sed -n '4p')" "1.2M"

# R-12: Token formatting
OUT=$(run_py "
from statusline import format_tokens, DEFAULT_THEME
print(format_tokens(12345, 4100, DEFAULT_THEME))
")
assert_contains "R-12a: input arrow" "$OUT" "↑12.3k"
assert_contains "R-12b: output arrow" "$OUT" "↓4.1k"

# R-13: Newline sanitization
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
state = {'model_name': 'Opus\nInjected'}
line = render(state, DEFAULT_THEME)
print(line)
")
# R-13: verify single line (newline check via line count, not grep)
assert_single_line "R-13: single line output" "$OUT"
assert_contains "R-13b: sanitized content" "$OUT" "Opus Injected"

echo ""
fi

# ======================================================================
# SECTION: config — TOML loading tests
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "config" ]; then
echo "--- Config Tests ---"

# CF-01: Missing config file returns defaults
OUT=$(run_py "
import os
os.environ['HOME'] = '/tmp/qline-test-no-config'
# Re-import to pick up new CONFIG_PATH
import importlib
import statusline
statusline.CONFIG_PATH = '/tmp/qline-test-no-config/.config/qline.toml'
theme = statusline.load_config()
print(theme['model']['color'])
print(theme['cost']['warn_threshold'])
")
assert_contains "CF-01a: default model color" "$OUT" "#d8dee9"
assert_contains "CF-01b: default cost warn" "$OUT" "2.0"

# CF-02: Malformed TOML returns defaults
TMPTOML=$(mktemp)
echo "this is not [valid toml" > "$TMPTOML"
OUT=$(run_py "
import statusline
statusline.CONFIG_PATH = '$TMPTOML'
theme = statusline.load_config()
print(theme['model']['color'])
")
rm -f "$TMPTOML"
assert_contains "CF-02: malformed TOML uses defaults" "$OUT" "#d8dee9"

# CF-03: Partial override merges correctly
TMPTOML=$(mktemp --suffix=.toml)
cat > "$TMPTOML" << 'TOML'
[model]
color = "#ff0000"
TOML
OUT=$(run_py "
import statusline
statusline.CONFIG_PATH = '$TMPTOML'
theme = statusline.load_config()
print('MODEL_COLOR:' + theme['model']['color'])
print('MODEL_BOLD:' + str(theme['model']['bold']))
print('COST_COLOR:' + theme['cost']['color'])
")
rm -f "$TMPTOML"
assert_contains "CF-03a: overridden model color" "$OUT" "MODEL_COLOR:#ff0000"
assert_contains "CF-03b: preserved model bold" "$OUT" "MODEL_BOLD:False"
assert_contains "CF-03c: untouched cost color" "$OUT" "COST_COLOR:#e0956a"

# CF-04: Full override
TMPTOML=$(mktemp --suffix=.toml)
cat > "$TMPTOML" << 'TOML'
[context_bar]
width = 20
warn_threshold = 50.0
critical_threshold = 80.0
color = "#00ff00"
warn_color = "#ffff00"
critical_color = "#ff0000"
TOML
OUT=$(run_py "
import statusline
statusline.CONFIG_PATH = '$TMPTOML'
theme = statusline.load_config()
print('WIDTH:' + str(theme['context_bar']['width']))
print('WARN:' + str(theme['context_bar']['warn_threshold']))
print('CRIT:' + str(theme['context_bar']['critical_threshold']))
")
rm -f "$TMPTOML"
assert_contains "CF-04a: overridden width" "$OUT" "WIDTH:20"
assert_contains "CF-04b: overridden warn" "$OUT" "WARN:50.0"
assert_contains "CF-04c: overridden critical" "$OUT" "CRIT:80.0"

echo ""
fi

# ======================================================================
# SECTION: ansi — verify ANSI output when NO_COLOR is NOT set
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "ansi" ]; then
echo "--- ANSI Output Tests ---"

# A-01: Color output contains ANSI escape codes
run_statusline_color "$(cat "$FIXTURES/valid-minimal.json")"
assert_exit_zero "A-01a: exit 0 with color" "$LAST_EXIT"
assert_contains "A-01b: ANSI escape present" "$LAST_STDOUT" $'\033['

# A-02: NO_COLOR suppresses ANSI
run_statusline "$(cat "$FIXTURES/valid-minimal.json")"
assert_not_contains "A-02: no ANSI under NO_COLOR" "$LAST_STDOUT" $'\033['

# A-03: Color output is still single line
run_statusline_color "$(cat "$FIXTURES/valid-full.json")"
assert_single_line "A-03: single line with color" "$LAST_STDOUT"
assert_empty "A-03b: no stderr with color" "$LAST_STDERR"

echo ""
fi

# ======================================================================
# SECTION: command — executable integration tests (NO_COLOR)
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "command" ]; then
echo "--- Command Integration Tests (NO_COLOR) ---"

# C-01: Full fixture
run_statusline "$(cat "$FIXTURES/valid-full.json")"
assert_exit_zero "C-01a: exit 0" "$LAST_EXIT"
assert_empty "C-01b: no stderr" "$LAST_STDERR"
assert_single_line "C-01c: single line" "$LAST_STDOUT"
assert_contains "C-01d: model" "$LAST_STDOUT" "Opus"
assert_contains "C-01e: dir" "$LAST_STDOUT" "qLine"
assert_contains "C-01f: cost" "$LAST_STDOUT" '1.23'
assert_contains "C-01g: duration" "$LAST_STDOUT" "45s"

# C-02: Minimal fixture
run_statusline "$(cat "$FIXTURES/valid-minimal.json")"
assert_exit_zero "C-02a: exit 0" "$LAST_EXIT"
assert_contains "C-02b: model" "$LAST_STDOUT" "Opus"

# C-03: Context window fixture (warn at new 40% threshold — 75% is warn)
run_statusline "$(cat "$FIXTURES/valid-with-context-window.json")"
assert_exit_zero "C-03a: exit 0" "$LAST_EXIT"
assert_contains "C-03b: bar present" "$LAST_STDOUT" "█"
assert_contains "C-03c: critical suffix (75% >= 70%)" "$LAST_STDOUT" "75%!"

# C-04: Critical context (90% >= 70%)
run_statusline "$(cat "$FIXTURES/valid-context-critical.json")"
assert_exit_zero "C-04a: exit 0" "$LAST_EXIT"
assert_contains "C-04b: critical suffix" "$LAST_STDOUT" "90%!"

# C-05: cwd fallback
run_statusline "$(cat "$FIXTURES/valid-no-workspace.json")"
assert_exit_zero "C-05a: exit 0" "$LAST_EXIT"
assert_contains "C-05b: cwd fallback" "$LAST_STDOUT" "myapp"

# C-06: Wrong-type optionals
run_statusline "$(cat "$FIXTURES/wrong-type-optionals.json")"
assert_exit_zero "C-06a: exit 0" "$LAST_EXIT"
assert_contains "C-06b: model rendered" "$LAST_STDOUT" "Opus"

# C-07: Empty JSON object
run_statusline "{}"
assert_exit_zero "C-07a: exit 0" "$LAST_EXIT"
assert_empty "C-07b: no stdout" "$LAST_STDOUT"

# C-08: JSON null
run_statusline "null"
assert_exit_zero "C-08a: exit 0" "$LAST_EXIT"
assert_empty "C-08b: no stdout" "$LAST_STDOUT"

# C-09: Tokens fixture
run_statusline "$(cat "$FIXTURES/valid-with-tokens.json")"
assert_exit_zero "C-09a: exit 0" "$LAST_EXIT"
assert_contains "C-09b: input tokens" "$LAST_STDOUT" "↑12.3k"
assert_contains "C-09c: output tokens" "$LAST_STDOUT" "↓4.1k"
assert_contains "C-09d: bar present" "$LAST_STDOUT" "50%"

# C-10: Real payload format (used_percentage + context_window_size)
run_statusline "$(cat "$FIXTURES/valid-real-payload.json")"
assert_exit_zero "C-10a: exit 0" "$LAST_EXIT"
assert_contains "C-10b: bar present" "$LAST_STDOUT" "15%"
assert_contains "C-10c: input tokens" "$LAST_STDOUT" "↑281k"
assert_contains "C-10d: output tokens" "$LAST_STDOUT" "↓141k"
assert_contains "C-10e: cost critical" "$LAST_STDOUT" '27.29'

# C-11: Optional fields don't crash
run_statusline "$(cat "$FIXTURES/valid-optional-fields.json")"
assert_exit_zero "C-11a: exit 0" "$LAST_EXIT"
assert_single_line "C-11b: single line" "$LAST_STDOUT"
assert_contains "C-11c: model" "$LAST_STDOUT" "Opus"

echo ""
fi

# ======================================================================
# SECTION: layout — multi-line and registry-driven rendering tests
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "layout" ]; then
echo "--- Layout Tests ---"

# L-01: No newline when line2 is empty (all line2 renderers return None)
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
state = {'model_name': 'Opus', 'cost_usd': 0.50}
line = render(state, DEFAULT_THEME)
print(line)
")
assert_single_line "L-01: no newline when line2 empty" "$OUT"
assert_contains "L-01b: model present" "$OUT" "Opus"

# L-02: Single-line mode (lines=1) works
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
import copy
theme = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_THEME.items()}
theme['layout'] = dict(DEFAULT_THEME['layout'])
theme['layout']['lines'] = 1
state = {'model_name': 'Opus', 'cost_usd': 0.50}
line = render(state, theme)
print(line)
")
assert_single_line "L-02: single-line mode" "$OUT"
assert_contains "L-02b: model present" "$OUT" "Opus"
assert_contains "L-02c: cost present" "$OUT" "0.50"

# L-03: lines=0 clamped to 1
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
theme = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_THEME.items()}
theme['layout'] = dict(DEFAULT_THEME['layout'])
theme['layout']['lines'] = 0
state = {'model_name': 'Opus'}
line = render(state, theme)
print(line)
")
assert_single_line "L-03: lines=0 clamped to 1" "$OUT"
assert_contains "L-03b: model present" "$OUT" "Opus"

# L-04: lines=5 clamped to 2
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
theme = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_THEME.items()}
theme['layout'] = dict(DEFAULT_THEME['layout'])
theme['layout']['lines'] = 5
state = {'model_name': 'Opus'}
line = render(state, theme)
# With lines=2 and empty line2, should still be single line
print(repr(line))
")
assert_not_contains "L-04: lines=5 clamped to 2 (no extra lines)" "$OUT" "\\n"

# L-05: Unknown module name silently ignored
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
theme = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_THEME.items()}
theme['layout'] = {'lines': 1, 'line1': ['model', 'nonexistent_module', 'cost'], 'line2': []}
state = {'model_name': 'Opus', 'cost_usd': 0.50}
line = render(state, theme)
print(line)
")
assert_contains "L-05a: model present" "$OUT" "Opus"
assert_contains "L-05b: cost present" "$OUT" "0.50"
assert_not_contains "L-05c: no error output" "$OUT" "Error"

# L-06: Empty layout arrays -> empty output
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
theme = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_THEME.items()}
theme['layout'] = {'lines': 1, 'line1': [], 'line2': []}
state = {'model_name': 'Opus', 'cost_usd': 0.50}
line = render(state, theme)
print(repr(line))
")
assert_equals "L-06: empty layout arrays -> empty" "$OUT" "''"

# L-07: Module moved between lines renders correctly
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
theme = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_THEME.items()}
theme['layout'] = {'lines': 1, 'line1': ['cost'], 'line2': ['model']}
state = {'model_name': 'Opus', 'cost_usd': 0.50}
line = render(state, theme)
print(line)
")
assert_contains "L-07a: cost present" "$OUT" "0.50"
assert_contains "L-07b: model present" "$OUT" "Opus"

# L-08: enabled=false hides module
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
theme = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_THEME.items()}
theme['model'] = dict(DEFAULT_THEME['model'])
theme['model']['enabled'] = False
theme['layout'] = {'lines': 1, 'line1': ['model', 'cost'], 'line2': []}
state = {'model_name': 'Opus', 'cost_usd': 0.50}
line = render(state, theme)
print(line)
")
assert_not_contains "L-08a: model hidden" "$OUT" "Opus"
assert_contains "L-08b: cost still present" "$OUT" "0.50"

# L-09: Non-array line1/line2 -> fallback to defaults
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
theme = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_THEME.items()}
theme['layout'] = {'lines': 1, 'line1': 'not_a_list', 'line2': 42}
state = {'model_name': 'Opus', 'cost_usd': 0.50}
line = render(state, theme)
print(line)
")
assert_contains "L-09a: model from defaults" "$OUT" "Opus"
assert_contains "L-09b: cost from defaults" "$OUT" "0.50"

# L-10: All modules disabled -> empty output
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
theme = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_THEME.items()}
for mod in ['model', 'dir', 'context_bar', 'tokens', 'cost', 'duration']:
    theme[mod] = dict(DEFAULT_THEME[mod])
    theme[mod]['enabled'] = False
theme['layout'] = {'lines': 1, 'line1': ['model', 'dir', 'context_bar', 'tokens', 'cost', 'duration'], 'line2': []}
state = {'model_name': 'Opus', 'cost_usd': 0.50, 'duration_ms': 1000}
line = render(state, theme)
print(repr(line))
")
assert_equals "L-10: all modules disabled -> empty" "$OUT" "''"

echo ""
fi

# ======================================================================
# SECTION: collector — system data collector tests
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "collector" ]; then
echo "--- Collector Tests ---"

# COL-01: CPU from valid loadavg mock file
MOCK_PROC=$(mktemp -d)
echo "2.50 1.20 0.80 1/234 5678" > "$MOCK_PROC/loadavg"
OUT=$(run_py "
import statusline
statusline.PROC_DIR = '$MOCK_PROC'
state = {}
statusline.collect_cpu(state)
val = state.get('cpu_percent', 'ABSENT')
if isinstance(val, int) and val >= 0:
    print('NUMBER')
else:
    print(val)
")
rm -rf "$MOCK_PROC"
assert_equals "COL-01: CPU from valid loadavg -> number" "$OUT" "NUMBER"

# COL-02: CPU from missing file
MOCK_PROC=$(mktemp -d)
OUT=$(run_py "
import statusline
statusline.PROC_DIR = '$MOCK_PROC'
state = {}
statusline.collect_cpu(state)
print(state.get('cpu_percent', 'ABSENT'))
")
rm -rf "$MOCK_PROC"
assert_equals "COL-02: CPU from missing file -> ABSENT" "$OUT" "ABSENT"

# COL-03: CPU from empty file
MOCK_PROC=$(mktemp -d)
echo -n "" > "$MOCK_PROC/loadavg"
OUT=$(run_py "
import statusline
statusline.PROC_DIR = '$MOCK_PROC'
state = {}
statusline.collect_cpu(state)
print(state.get('cpu_percent', 'ABSENT'))
")
rm -rf "$MOCK_PROC"
assert_equals "COL-03: CPU from empty file -> ABSENT" "$OUT" "ABSENT"

# COL-04: Memory from valid meminfo (MemAvailable present)
MOCK_PROC=$(mktemp -d)
cat > "$MOCK_PROC/meminfo" << 'MEMINFO'
MemTotal:       16384000 kB
MemFree:         1000000 kB
MemAvailable:    6000000 kB
Buffers:          500000 kB
Cached:          3000000 kB
MEMINFO
OUT=$(run_py "
import statusline
statusline.PROC_DIR = '$MOCK_PROC'
state = {}
statusline.collect_memory(state)
print(state.get('memory_percent', 'ABSENT'))
")
rm -rf "$MOCK_PROC"
# used = 16384000 - 6000000 = 10384000, pct = (10384000 * 100) // 16384000 = 63
assert_equals "COL-04: Memory from valid meminfo -> 63%" "$OUT" "63"

# COL-05: Memory missing MemAvailable -> fallback to MemFree+Buffers+Cached
MOCK_PROC=$(mktemp -d)
cat > "$MOCK_PROC/meminfo" << 'MEMINFO'
MemTotal:       16384000 kB
MemFree:         2000000 kB
Buffers:          500000 kB
Cached:          3000000 kB
MEMINFO
OUT=$(run_py "
import statusline
statusline.PROC_DIR = '$MOCK_PROC'
state = {}
statusline.collect_memory(state)
print(state.get('memory_percent', 'ABSENT'))
")
rm -rf "$MOCK_PROC"
# available = 2000000 + 500000 + 3000000 = 5500000
# used = 16384000 - 5500000 = 10884000, pct = (10884000 * 100) // 16384000 = 66
assert_equals "COL-05: Memory fallback -> 66%" "$OUT" "66"

# COL-06: Memory from missing file
MOCK_PROC=$(mktemp -d)
OUT=$(run_py "
import statusline
statusline.PROC_DIR = '$MOCK_PROC'
state = {}
statusline.collect_memory(state)
print(state.get('memory_percent', 'ABSENT'))
")
rm -rf "$MOCK_PROC"
assert_equals "COL-06: Memory missing file -> ABSENT" "$OUT" "ABSENT"

# COL-07: Disk from real statvfs -> percentage between 0 and 100
OUT=$(run_py "
import statusline
state = {}
statusline.collect_disk(state)
val = state.get('disk_percent', 'ABSENT')
if isinstance(val, int) and 0 <= val <= 100:
    print('VALID')
else:
    print('INVALID:' + str(val))
")
assert_equals "COL-07: Disk from real statvfs -> valid pct" "$OUT" "VALID"

# COL-08: Git in a repo
GIT_TMP=$(mktemp -d)
(cd "$GIT_TMP" && git init -q && git commit --allow-empty -m "init" -q)
OUT=$(run_py "
import os
os.chdir('$GIT_TMP')
import statusline
state = {}
statusline.collect_git(state)
print('branch:' + str(state.get('git_branch', 'ABSENT')))
print('sha:' + str(state.get('git_sha', 'ABSENT')))
print('dirty:' + str(state.get('git_dirty', 'ABSENT')))
")
rm -rf "$GIT_TMP"
assert_not_contains "COL-08a: git branch present" "$OUT" "branch:ABSENT"
assert_not_contains "COL-08b: git sha present" "$OUT" "sha:ABSENT"
assert_contains "COL-08c: git clean" "$OUT" "dirty:False"

# COL-09: Git dirty detection
GIT_TMP=$(mktemp -d)
(cd "$GIT_TMP" && git init -q && git commit --allow-empty -m "init" -q && echo "x" > dirty.txt)
OUT=$(run_py "
import os
os.chdir('$GIT_TMP')
import statusline
state = {}
statusline.collect_git(state)
print('dirty:' + str(state.get('git_dirty', 'ABSENT')))
")
rm -rf "$GIT_TMP"
assert_contains "COL-09: git dirty" "$OUT" "dirty:True"

# COL-10: Git not a repo
NOTGIT=$(mktemp -d)
OUT=$(run_py "
import os
os.chdir('$NOTGIT')
import statusline
state = {}
statusline.collect_git(state)
print('branch:' + str(state.get('git_branch', 'ABSENT')))
")
rm -rf "$NOTGIT"
assert_contains "COL-10: not a repo" "$OUT" "branch:ABSENT"

# COL-11: Tmux render format
OUT=$(run_py "
from statusline import render_tmux, DEFAULT_THEME
state = {'tmux_sessions': 3, 'tmux_panes': 12}
result = render_tmux(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_contains "COL-11: tmux format" "$OUT" "3s/12p"

# COL-12: Tmux zero sessions -> hidden
OUT=$(run_py "
from statusline import render_tmux, DEFAULT_THEME
state = {'tmux_sessions': 0}
result = render_tmux(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_equals "COL-12: tmux zero hidden" "$OUT" "NONE"

echo ""
fi

# ======================================================================
# Summary
# ======================================================================
echo "=== Results: $PASS/$TOTAL passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
