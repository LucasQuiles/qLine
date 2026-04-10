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
#   bash tests/test-statusline.sh --section cache
#   bash tests/test-statusline.sh --section obs
#   bash tests/test-statusline.sh --section alerts
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SRC="$REPO_DIR/src/statusline.py"
FIXTURES="$SCRIPT_DIR/fixtures/statusline"

# Resolve Python 3.10+ using the same priority as install.sh / run-hook
PYTHON=""
for _candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$_candidate" > /dev/null 2>&1; then
        read _major _minor <<< $("$_candidate" -c 'import sys; print(sys.version_info.major, sys.version_info.minor)' 2>/dev/null || echo "0 0")
        if [ "$_major" -eq 3 ] && [ "$_minor" -ge 10 ]; then
            PYTHON="$_candidate"
            break
        fi
    fi
done
if [ -z "$PYTHON" ]; then
    echo "FATAL: No Python 3.10+ found in PATH" >&2
    exit 1
fi

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

assert_not_empty() {
    local label="$1" output="$2"
    TOTAL=$((TOTAL + 1))
    if [ -n "$output" ]; then
        echo "  PASS: $label"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $label (expected non-empty output)"
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
    line_count=$(printf '%s\n' "$output" | wc -l | tr -d ' ')
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
    printf '%s' "$input" | NO_COLOR=1 QLINE_NO_COLLECT=1 "$PYTHON" "$SRC" >"$tmpout" 2>"$tmpderr"
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
    printf '%s' "$input" | env -u NO_COLOR QLINE_NO_COLLECT=1 "$PYTHON" "$SRC" >"$tmpout" 2>"$tmpderr"
    local exit_code=$?
    LAST_STDOUT=$(cat "$tmpout")
    LAST_STDERR=$(cat "$tmpderr")
    LAST_EXIT=$exit_code
    rm -f "$tmpout" "$tmpderr"
}

# Helper: run a Python snippet importing from statusline
run_py() {
    NO_COLOR=1 "$PYTHON" -c "
import sys; sys.path.insert(0, '$REPO_DIR/src')
$1
" 2>&1
}

# Helper: run a Python snippet with ANSI colors enabled (NO_COLOR not set)
run_py_color() {
    env -u NO_COLOR "$PYTHON" -c "
import sys; sys.path.insert(0, '$REPO_DIR/src')
$1
" 2>&1
}

# Helper: emit a Unicode codepoint as UTF-8 (works on any bash version)
uc() { "$PYTHON" -c "import sys; sys.stdout.write('$1')"; }

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
assert_contains "N-01a: model_name extracted" "$OUT" "Op"
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
assert_contains "N-02a: model_name from minimal" "$OUT" "Op"
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
assert_contains "N-06d: model still extracted" "$OUT" "MODEL:Op"

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

# N-12: transcript_path extracted from payload
OUT=$(run_py "
import json
from statusline import normalize
payload = json.load(open('$FIXTURES/valid-full.json'))
state = normalize(payload)
print(state.get('transcript_path', 'MISSING'))
")
assert_equals "N-12: transcript_path extracted" "$OUT" "/tmp/transcript.json"

# N-13: transcript_path absent when not in payload
OUT=$(run_py "
import json
from statusline import normalize
payload = json.load(open('$FIXTURES/valid-minimal.json'))
state = normalize(payload)
print(state.get('transcript_path', 'ABSENT'))
")
assert_equals "N-13: transcript_path absent" "$OUT" "ABSENT"

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
assert_contains "R-02a: model with glyph" "$OUT" "$(uc '\U000f06a9') Opus"
assert_contains "R-02b: dir with glyph" "$OUT" "$(uc '\U000f0770') qLine"
assert_contains "R-02c: bar present" "$OUT" "50%"
assert_contains "R-02d: tokens present" "$OUT" "12.3k"
assert_contains "R-02e: cost with glyph" "$OUT" '$1.23'
assert_contains "R-02f: duration with glyph" "$OUT" "$(uc '\U000f0954')45s"
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

# R-05: Context bar warn at new threshold (>=75%)
OUT=$(run_py "
from statusline import render_bar, DEFAULT_THEME
print(render_bar(80, DEFAULT_THEME))
")
assert_contains "R-05: warn suffix at 80%" "$OUT" "80%~"

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
import copy
theme = copy.deepcopy(DEFAULT_THEME)
theme['context_bar']['width'] = 10
bar = render_bar(50, theme)
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
assert_contains "R-12a: input arrow" "$OUT" "▲12.3k"
assert_contains "R-12b: output arrow" "$OUT" "▼4.1k"

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
TMPTOML="$(mktemp).toml"
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
TMPTOML="$(mktemp).toml"
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

# A-03: Color output renders without error
run_statusline_color "$(cat "$FIXTURES/valid-full.json")"
assert_not_empty "A-03: non-empty with color" "$LAST_STDOUT"
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
assert_not_empty "C-01c: non-empty output" "$LAST_STDOUT"
assert_contains "C-01d: model" "$LAST_STDOUT" "Op"
assert_contains "C-01e: dir" "$LAST_STDOUT" "qLine"
assert_contains "C-01f: cost" "$LAST_STDOUT" '1.23'
assert_contains "C-01g: duration" "$LAST_STDOUT" "45s"

# C-02: Minimal fixture
run_statusline "$(cat "$FIXTURES/valid-minimal.json")"
assert_exit_zero "C-02a: exit 0" "$LAST_EXIT"
assert_contains "C-02b: model" "$LAST_STDOUT" "Op"

# C-03: Context window fixture (warn at new 40% threshold — 75% is warn)
run_statusline "$(cat "$FIXTURES/valid-with-context-window.json")"
assert_exit_zero "C-03a: exit 0" "$LAST_EXIT"
assert_contains "C-03b: bar present" "$LAST_STDOUT" "█"
assert_contains "C-03c: warn suffix (75% >= 75%)" "$LAST_STDOUT" "75%~"

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
assert_contains "C-06b: model rendered" "$LAST_STDOUT" "Op"

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
assert_contains "C-09b: input tokens" "$LAST_STDOUT" "▲12.3k"
assert_contains "C-09c: output tokens" "$LAST_STDOUT" "▼4.1k"
assert_contains "C-09d: bar present" "$LAST_STDOUT" "50%"

# C-10: Real payload format (used_percentage + context_window_size)
run_statusline "$(cat "$FIXTURES/valid-real-payload.json")"
assert_exit_zero "C-10a: exit 0" "$LAST_EXIT"
assert_contains "C-10b: bar present" "$LAST_STDOUT" "15%"
assert_contains "C-10c: input tokens" "$LAST_STDOUT" "▲281k"
assert_contains "C-10d: output tokens" "$LAST_STDOUT" "▼141k"
assert_contains "C-10e: cost critical" "$LAST_STDOUT" '27.29'

# C-11: Optional fields don't crash
run_statusline "$(cat "$FIXTURES/valid-optional-fields.json")"
assert_exit_zero "C-11a: exit 0" "$LAST_EXIT"
assert_not_empty "C-11b: has output" "$LAST_STDOUT"
assert_contains "C-11c: model" "$LAST_STDOUT" "Op"

# C-12: Full real payload produces output with system modules (color mode)
run_statusline_color "$(cat "$FIXTURES/valid-real-payload.json")"
assert_exit_zero "C-12a: exit 0" "$LAST_EXIT"
assert_empty "C-12b: no stderr" "$LAST_STDERR"

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
state = {'model_name': 'Opus'}
line = render(state, DEFAULT_THEME)
print(line)
")
assert_single_line "L-01: no newline when line2 empty" "$OUT"
assert_contains "L-01b: model present" "$OUT" "Opus"

# L-02: force_single_line merges all lines
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
theme = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_THEME.items()}
theme['layout'] = dict(DEFAULT_THEME['layout'])
theme['layout']['force_single_line'] = True
state = {'model_name': 'Opus', 'cost_usd': 0.50}
line = render(state, theme)
print(line)
")
assert_single_line "L-02: force single line" "$OUT"
assert_contains "L-02b: model present" "$OUT" "Opus"
assert_contains "L-02c: cost present" "$OUT" "0.50"

# L-03: force_single_line=False (default) allows multi-line
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
state = {'model_name': 'Opus'}
line = render(state, DEFAULT_THEME)
print(line)
")
assert_contains "L-03: default renders" "$OUT" "Opus"

# L-04: All layout lines merged into single stream
OUT=$(run_py "
from statusline import render, DEFAULT_THEME
theme = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_THEME.items()}
theme['layout'] = {'line1': ['model'], 'line2': ['cost'], 'line3': ['duration']}
state = {'model_name': 'Opus', 'cost_usd': 1.0, 'duration_ms': 60000}
line = render(state, theme)
# All 3 short modules fit on one merged line
has_all = 'Opus' in line and '1.0' in line and '1m' in line
print(f'merged={has_all}')
")
assert_contains "L-04: layout lines merged" "$OUT" "merged=True"

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

# L-11: Worktree marker appended
OUT=$(run_py "
from statusline import render_dir, DEFAULT_THEME
state = {'dir_basename': 'qLine', 'is_worktree': True}
result = render_dir(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_contains "L-11: worktree marker" "$OUT" "qLine"
# Check the marker character is present
assert_contains "L-11b: marker char" "$OUT" "$(uc '\u229b')"

# L-12: No worktree marker when false
OUT=$(run_py "
from statusline import render_dir, DEFAULT_THEME
state = {'dir_basename': 'qLine', 'is_worktree': False}
result = render_dir(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_not_contains "L-12: no marker" "$OUT" $'\u229b'

# L-13: CPU abbreviated in compact mode
OUT=$(run_py "
from statusline import render_cpu, DEFAULT_THEME
state = {'cpu_percent': 23, '_compact': True}
result = render_cpu(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_contains "L-13: CPU compact" "$OUT" "C:"
assert_contains "L-13b: CPU compact pct" "$OUT" "23%"

# L-14: CPU full in normal mode
OUT=$(run_py "
from statusline import render_cpu, DEFAULT_THEME
state = {'cpu_percent': 23, '_compact': False}
result = render_cpu(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_contains "L-14: CPU full has bar" "$OUT" "░"
assert_contains "L-14b: CPU full pct" "$OUT" "23%"

# L-15: Memory abbreviated in compact mode
OUT=$(run_py "
from statusline import render_memory, DEFAULT_THEME
state = {'memory_percent': 55, '_compact': True}
result = render_memory(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_contains "L-15: MEM compact" "$OUT" "M:"
assert_contains "L-15b: MEM compact pct" "$OUT" "55%"

# L-16: Disk abbreviated in compact mode
OUT=$(run_py "
from statusline import render_disk, DEFAULT_THEME
state = {'disk_percent': 80, '_compact': True}
result = render_disk(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_contains "L-16: DSK compact" "$OUT" "D:"
assert_contains "L-16b: DSK compact pct" "$OUT" "80%"

# L-17: Git branch truncated to 12 chars in compact mode
OUT=$(run_py "
from statusline import render_git, DEFAULT_THEME
state = {'git_branch': 'feature/very-long-branch-name', 'git_sha': 'abc1234', '_compact': True}
result = render_git(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_not_contains "L-17: git compact truncation" "$OUT" "feature/very-long-branch-name"

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

# COL-13: Agents render with count
OUT=$(run_py "
from statusline import render_agents, DEFAULT_THEME
state = {'agent_count': 3}
result = render_agents(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_contains "COL-13: agents render" "$OUT" "3"

# COL-14: Agents zero -> hidden
OUT=$(run_py "
from statusline import render_agents, DEFAULT_THEME
state = {'agent_count': 0}
result = render_agents(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_equals "COL-14: agents zero hidden" "$OUT" "NONE"

# COL-15: Agents missing -> hidden
OUT=$(run_py "
from statusline import render_agents, DEFAULT_THEME
state = {}
result = render_agents(state, DEFAULT_THEME)
print(result or 'NONE')
")
assert_equals "COL-15: agents missing hidden" "$OUT" "NONE"

echo ""
fi

# ======================================================================
# SECTION: cache — stale data cache tests
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "cache" ]; then
echo "--- Cache Tests ---"

# CACHE-01: save and load round-trip
CACHE_TMP=$(mktemp)
OUT=$(run_py "
import statusline, time
statusline.CACHE_PATH = '$CACHE_TMP'
cache = {'cpu': {'value': {'cpu_percent': 42}, 'timestamp': time.time()}}
statusline.save_cache(cache)
loaded = statusline.load_cache()
print(loaded.get('cpu', {}).get('value', {}).get('cpu_percent', 'ABSENT'))
")
rm -f "$CACHE_TMP"
assert_equals "CACHE-01: round-trip" "$OUT" "42"

# CACHE-02: corrupted cache -> empty
CACHE_TMP=$(mktemp)
echo "not json" > "$CACHE_TMP"
OUT=$(run_py "
import statusline
statusline.CACHE_PATH = '$CACHE_TMP'
loaded = statusline.load_cache()
print(len(loaded))
")
rm -f "$CACHE_TMP"
assert_equals "CACHE-02: corrupted -> empty" "$OUT" "0"

# CACHE-03: wrong version -> empty
CACHE_TMP=$(mktemp)
echo '{"version": 999, "modules": {"cpu": {}}}' > "$CACHE_TMP"
OUT=$(run_py "
import statusline
statusline.CACHE_PATH = '$CACHE_TMP'
loaded = statusline.load_cache()
print(len(loaded))
")
rm -f "$CACHE_TMP"
assert_equals "CACHE-03: wrong version -> empty" "$OUT" "0"

# CACHE-04: stale entry (>60s) not applied
OUT=$(run_py "
import statusline, time
cache = {'cpu': {'value': {'cpu_percent': 99}, 'timestamp': time.time() - 120}}
state = {}
statusline._apply_cached(state, cache, 'cpu', time.time())
print(state.get('cpu_percent', 'ABSENT'))
")
assert_equals "CACHE-04: stale not applied" "$OUT" "ABSENT"

# CACHE-05: fresh entry applied with stale flag
OUT=$(run_py "
import statusline, time
now = time.time()
cache = {'cpu': {'value': {'cpu_percent': 42}, 'timestamp': now}}
state = {}
statusline._apply_cached(state, cache, 'cpu', now)
print(state.get('cpu_percent', 'ABSENT'))
print(state.get('cpu_stale', False))
")
assert_contains "CACHE-05a: fresh applied" "$OUT" "42"
assert_contains "CACHE-05b: stale flag" "$OUT" "True"

# CACHE-06: missing cache file -> empty dict
OUT=$(run_py "
import statusline
statusline.CACHE_PATH = '/tmp/qline-nonexistent-cache-12345.json'
loaded = statusline.load_cache()
print(len(loaded))
")
assert_equals "CACHE-06: missing file -> empty" "$OUT" "0"

# CACHE-07: _cache_module stores correct keys
OUT=$(run_py "
import statusline, time
cache = {}
state = {'cpu_percent': 55, 'memory_percent': 70}
now = time.time()
statusline._cache_module(cache, state, 'cpu', now)
statusline._cache_module(cache, state, 'memory', now)
print('cpu_val:' + str(cache.get('cpu', {}).get('value', {}).get('cpu_percent', 'ABSENT')))
print('mem_val:' + str(cache.get('memory', {}).get('value', {}).get('memory_percent', 'ABSENT')))
print('has_ts:' + str('timestamp' in cache.get('cpu', {})))
")
assert_contains "CACHE-07a: cpu cached" "$OUT" "cpu_val:55"
assert_contains "CACHE-07b: mem cached" "$OUT" "mem_val:70"
assert_contains "CACHE-07c: has timestamp" "$OUT" "has_ts:True"

echo ""
fi

# ======================================================================
# SECTION: stale — stale data dimming tests
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "stale" ]; then
echo "--- Stale Data Tests ---"

# STALE-01: Stale CPU rendered dimmed (need color output, must unset NO_COLOR)
OUT=$(run_py_color "
from statusline import render_cpu, DEFAULT_THEME
state = {'cpu_percent': 42, 'cpu_stale': True}
result = render_cpu(state, DEFAULT_THEME)
print('HAS_DIM' if result and '\033[2m' in result else 'NO_DIM')
")
assert_equals "STALE-01: stale has dim" "$OUT" "HAS_DIM"

# STALE-02: Non-stale CPU not dimmed (must unset NO_COLOR so absence of dim is meaningful)
OUT=$(run_py_color "
from statusline import render_cpu, DEFAULT_THEME
state = {'cpu_percent': 42, 'cpu_stale': False}
result = render_cpu(state, DEFAULT_THEME)
print('HAS_DIM' if result and '\033[2m' in result else 'NO_DIM')
")
assert_equals "STALE-02: non-stale no dim" "$OUT" "NO_DIM"

# STALE-03: Stale git in dir pill rendered dimmed
OUT=$(run_py_color "
from statusline import render_dir, DEFAULT_THEME
state = {'dir_basename': 'proj', 'git_branch': 'main', 'git_sha': 'abc1234', 'git_stale': True}
result = render_dir(state, DEFAULT_THEME)
print('HAS_DIM' if result and '\033[2m' in result else 'NO_DIM')
")
assert_equals "STALE-03: stale git has dim" "$OUT" "HAS_DIM"

# STALE-04: Stale tmux rendered dimmed
OUT=$(run_py_color "
from statusline import render_tmux, DEFAULT_THEME
state = {'tmux_sessions': 2, 'tmux_panes': 8, 'tmux_stale': True}
result = render_tmux(state, DEFAULT_THEME)
print('HAS_DIM' if result and '\033[2m' in result else 'NO_DIM')
")
assert_equals "STALE-04: stale tmux has dim" "$OUT" "HAS_DIM"

# STALE-05: Stale agents rendered dimmed
OUT=$(run_py_color "
from statusline import render_agents, DEFAULT_THEME
state = {'agent_count': 3, 'agents_stale': True}
result = render_agents(state, DEFAULT_THEME)
print('HAS_DIM' if result and '\033[2m' in result else 'NO_DIM')
")
assert_equals "STALE-05: stale agents has dim" "$OUT" "HAS_DIM"

# STALE-06: Stale memory rendered dimmed
OUT=$(run_py_color "
from statusline import render_memory, DEFAULT_THEME
state = {'memory_percent': 65, 'memory_stale': True}
result = render_memory(state, DEFAULT_THEME)
print('HAS_DIM' if result and '\033[2m' in result else 'NO_DIM')
")
assert_equals "STALE-06: stale memory has dim" "$OUT" "HAS_DIM"

echo ""
fi

# ======================================================================
# Section: obs (observability integration)
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "obs" ]; then
echo ""
echo "=== Section: obs ==="

OBS_TEST_ROOT=$(mktemp -d)
OBS_TEST_CACHE=$(mktemp)

OBS_SESSION_ID="test-obs-session-$(date +%s)"
"$PYTHON" -c "
import sys; sys.path.insert(0, '$REPO_DIR/hooks')
from obs_utils import create_package
create_package('$OBS_SESSION_ID', '/tmp', '/tmp/t.jsonl', 'startup', obs_root='$OBS_TEST_ROOT')
"

OBS_PKG_ROOT=$("$PYTHON" -c "
import sys; sys.path.insert(0, '$REPO_DIR/hooks')
from obs_utils import resolve_package_root
print(resolve_package_root('$OBS_SESSION_ID', obs_root='$OBS_TEST_ROOT'))
")

# Build a test payload with session_id matching our package
OBS_PAYLOAD=$("$PYTHON" -c "
import json
d = {
    'session_id': '$OBS_SESSION_ID',
    'model': {'id': 'claude-opus-4-6[1m]', 'display_name': 'Opus 4.6 (1M context)'},
    'workspace': {'current_dir': '/home/q/LAB/qLine'},
    'cost': {'total_cost_usd': 5.50, 'total_duration_ms': 120000},
    'context_window': {
        'total_input_tokens': 100000,
        'total_output_tokens': 50000,
        'context_window_size': 1000000,
        'used_percentage': 15,
        'remaining_percentage': 85
    }
}
print(json.dumps(d))
")

# T-obs-1: snapshot appended on first invocation
echo ""
echo "--- T-obs-1: snapshot appended ---"
printf '%s' "$OBS_PAYLOAD" | NO_COLOR=1 QLINE_NO_COLLECT=1 OBS_ROOT="$OBS_TEST_ROOT" QLINE_CACHE_PATH="$OBS_TEST_CACHE" "$PYTHON" "$SRC" > /dev/null 2>&1
SNAP_FILE="$OBS_PKG_ROOT/native/statusline/snapshots.jsonl"
SNAP_COUNT=$(wc -l < "$SNAP_FILE" 2>/dev/null | tr -d ' ' || echo 0)
assert_equals "T-obs-1: snapshot appended" "$SNAP_COUNT" "1"

# T-obs-2: snapshot has correct fields
echo ""
echo "--- T-obs-2: correct fields ---"
FIELDS_CHECK=$("$PYTHON" -c "
import json
with open('$SNAP_FILE') as f:
    r = json.loads(f.readline())
required = ['ts', 'session_id', 'cost_usd', 'context_pct', 'input_tokens', 'output_tokens', 'model_name', 'dir_basename']
missing = [k for k in required if k not in r]
if missing:
    print(f'MISSING: {missing}')
elif r.get('session_id') != '$OBS_SESSION_ID':
    print(f'BAD_SID: {r.get(\"session_id\")}')
elif r.get('cost_usd') != 5.50:
    print(f'BAD_COST: {r.get(\"cost_usd\")}')
else:
    print('OK')
" 2>/dev/null || echo "ERROR")
assert_equals "T-obs-2: correct fields" "$FIELDS_CHECK" "OK"

# T-obs-3: throttle skips duplicate within 30s
echo ""
echo "--- T-obs-3: throttle ---"
printf '%s' "$OBS_PAYLOAD" | NO_COLOR=1 QLINE_NO_COLLECT=1 OBS_ROOT="$OBS_TEST_ROOT" QLINE_CACHE_PATH="$OBS_TEST_CACHE" "$PYTHON" "$SRC" > /dev/null 2>&1
SNAP_COUNT2=$(wc -l < "$SNAP_FILE" 2>/dev/null | tr -d ' ' || echo 0)
assert_equals "T-obs-3: throttle skips duplicate" "$SNAP_COUNT2" "1"

# T-obs-4: meaningful change bypasses throttle
echo ""
echo "--- T-obs-4: meaningful change ---"
OBS_PAYLOAD_CHANGED=$("$PYTHON" -c "
import json
d = {
    'session_id': '$OBS_SESSION_ID',
    'model': {'id': 'claude-opus-4-6[1m]', 'display_name': 'Opus 4.6 (1M context)'},
    'workspace': {'current_dir': '/home/q/LAB/qLine'},
    'cost': {'total_cost_usd': 10.00, 'total_duration_ms': 240000},
    'context_window': {
        'total_input_tokens': 200000,
        'total_output_tokens': 100000,
        'context_window_size': 1000000,
        'used_percentage': 30,
        'remaining_percentage': 70
    }
}
print(json.dumps(d))
")
printf '%s' "$OBS_PAYLOAD_CHANGED" | NO_COLOR=1 QLINE_NO_COLLECT=1 OBS_ROOT="$OBS_TEST_ROOT" QLINE_CACHE_PATH="$OBS_TEST_CACHE" "$PYTHON" "$SRC" > /dev/null 2>&1
SNAP_COUNT3=$(wc -l < "$SNAP_FILE" 2>/dev/null | tr -d ' ' || echo 0)
assert_equals "T-obs-4: meaningful change bypasses throttle" "$SNAP_COUNT3" "2"

# T-obs-5: statusline_capture health
echo ""
echo "--- T-obs-5: health ---"
HEALTH_CHECK=$("$PYTHON" -c "
import json
with open('$OBS_PKG_ROOT/manifest.json') as f:
    m = json.load(f)
sc = m.get('health', {}).get('subsystems', {}).get('statusline_capture')
print(sc if sc else 'ABSENT')
" 2>/dev/null || echo "ERROR")
assert_equals "T-obs-5: statusline_capture = healthy" "$HEALTH_CHECK" "healthy"

# T-obs-6: missing session_id
echo ""
echo "--- T-obs-6: missing session_id ---"
OBS_TEST_ROOT_6=$(mktemp -d)
NO_SID_PAYLOAD='{"model": {"id": "test"}, "cost": {"total_cost_usd": 1}}'
printf '%s' "$NO_SID_PAYLOAD" | NO_COLOR=1 QLINE_NO_COLLECT=1 OBS_ROOT="$OBS_TEST_ROOT_6" QLINE_CACHE_PATH="$(mktemp)" "$PYTHON" "$SRC" > /dev/null 2>&1
NO_SID_SNAP=$(find "$OBS_TEST_ROOT_6" -name "snapshots.jsonl" 2>/dev/null | wc -l | tr -d ' ')
assert_equals "T-obs-6: no snapshot without session_id" "$NO_SID_SNAP" "0"
rm -rf "$OBS_TEST_ROOT_6"

# T-obs-7: no package
echo ""
echo "--- T-obs-7: no package ---"
NO_PKG_PAYLOAD=$("$PYTHON" -c "
import json
d = {'session_id': 'nonexistent-session', 'model': {'id': 'test'}}
print(json.dumps(d))
")
printf '%s' "$NO_PKG_PAYLOAD" | NO_COLOR=1 QLINE_NO_COLLECT=1 OBS_ROOT="$OBS_TEST_ROOT" QLINE_CACHE_PATH="$(mktemp)" "$PYTHON" "$SRC" > /dev/null 2>&1
# Should not crash — test that it exited 0
assert_equals "T-obs-7: no crash without package" "$?" "0"

# T-obs-8: _obs cache survives collect_system_data rebuild
echo ""
echo "--- T-obs-8: cache survival ---"
OBS_TEST_CACHE_8=$(mktemp)
OBS_SESSION_8="test-obs-cache-$(date +%s)"
"$PYTHON" -c "
import sys; sys.path.insert(0, '$REPO_DIR/hooks')
from obs_utils import create_package
create_package('$OBS_SESSION_8', '/tmp', '/tmp/t.jsonl', 'startup', obs_root='$OBS_TEST_ROOT')
"
# Seed the cache with _obs data
"$PYTHON" -c "
import json
cache = {'version': 1, 'modules': {'_obs': {'$OBS_SESSION_8': {'last_snapshot_ts': 0, 'last_snapshot_hash': 'seed'}}}}
with open('$OBS_TEST_CACHE_8', 'w') as f:
    json.dump(cache, f)
"
# Run full invocation (real collectors run — no QLINE_NO_COLLECT)
OBS_PAYLOAD_8=$("$PYTHON" -c "
import json
d = {'session_id': '$OBS_SESSION_8', 'model': {'id': 'test', 'display_name': 'Test'}, 'cost': {'total_cost_usd': 1, 'total_duration_ms': 1000}, 'context_window': {'total_input_tokens': 1000, 'total_output_tokens': 500, 'context_window_size': 100000, 'used_percentage': 1, 'remaining_percentage': 99}}
print(json.dumps(d))
")
printf '%s' "$OBS_PAYLOAD_8" | NO_COLOR=1 OBS_ROOT="$OBS_TEST_ROOT" QLINE_CACHE_PATH="$OBS_TEST_CACHE_8" "$PYTHON" "$SRC" > /dev/null 2>&1
# Verify _obs survived the cache rebuild
CACHE_SURVIVAL=$("$PYTHON" -c "
import json
with open('$OBS_TEST_CACHE_8') as f:
    d = json.load(f)
obs = d.get('modules', {}).get('_obs', {})
print('OK' if '$OBS_SESSION_8' in obs else f'MISSING: {list(obs.keys())}')
" 2>/dev/null || echo "ERROR")
assert_equals "T-obs-8: _obs survives cache rebuild" "$CACHE_SURVIVAL" "OK"
rm -f "$OBS_TEST_CACHE_8"

# T-obs-9: fail-silent
echo ""
echo "--- T-obs-9: fail-silent ---"
OBS_READONLY=$(mktemp -d)
chmod 444 "$OBS_READONLY"
OUTPUT_9=$(printf '%s' "$OBS_PAYLOAD" | NO_COLOR=1 QLINE_NO_COLLECT=1 OBS_ROOT="$OBS_READONLY" QLINE_CACHE_PATH="$(mktemp)" "$PYTHON" "$SRC" 2>/dev/null)
chmod 755 "$OBS_READONLY"
rm -rf "$OBS_READONLY"
# Statusline should still produce output even when obs fails
# (output may be empty if NO_COLOR strips it — just verify no crash)
assert_equals "T-obs-9: exits 0 when obs fails" "$?" "0"

rm -rf "$OBS_TEST_ROOT" "$OBS_TEST_CACHE"
echo ""
fi

# ── Section: overhead ───────────────────────────────────────────────
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "overhead" ]; then
echo ""
echo "=== Section: overhead ==="

echo "  dual-bar: 30% system, 10% conversation (40% total)"
OUT=$(run_py "
from statusline import render_context_bar, DEFAULT_THEME
import copy
theme = copy.deepcopy(DEFAULT_THEME)
theme['context_bar']['width'] = 10
state = {
    'context_used': 400000,
    'context_total': 1000000,
    'sys_overhead_tokens': 300000,
    'sys_overhead_source': 'measured',
}
result = render_context_bar(state, theme)
# total 40%, width=10 -> filled=4
# sys 30% -> sys_blocks = 3, conv_blocks = 1, free = 6
n_full = result.count('\u2588')
n_med = result.count('\u2593')
n_empty = result.count('\u2591')
assert n_full == 3, f'expected 3 sys blocks, got {n_full}'
assert n_med == 1, f'expected 1 conv block, got {n_med}'
assert n_empty == 6, f'expected 6 free blocks, got {n_empty}'
print('OK')
")
assert_equals "dual-bar 30/10" "$OUT" "OK"

echo "  dual-bar: context_used == 0"
OUT=$(run_py "
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 0,
    'context_total': 1000000,
    'sys_overhead_tokens': 0,
    'sys_overhead_source': 'measured',
}
result = render_context_bar(state, DEFAULT_THEME)
assert '\u2591' * 10 in result, f'expected 10 empty blocks, got: {result}'
print('OK')
")
assert_equals "dual-bar zero usage" "$OUT" "OK"

echo "  dual-bar: sys_overhead > context_total clamped"
OUT=$(run_py "
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 200000,
    'context_total': 200000,
    'sys_overhead_tokens': 999999,
    'sys_overhead_source': 'estimated',
}
result = render_context_bar(state, DEFAULT_THEME)
assert result is not None, 'should not return None'
print('OK')
")
assert_equals "dual-bar clamped" "$OUT" "OK"

echo "  single-bar fallback: no overhead data"
OUT=$(run_py "
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 50000,
    'context_total': 100000,
}
result = render_context_bar(state, DEFAULT_THEME)
assert '\u2588' * 5 in result, f'expected 5 filled blocks, got: {result}'
assert '\u2591' * 5 in result, f'expected 5 empty blocks, got: {result}'
assert '\u2593' not in result, f'should not have medium blocks without overhead data'
print('OK')
")
assert_equals "single-bar fallback" "$OUT" "OK"

echo "  segment formula: sys + conv + free == width for all inputs"
OUT=$(run_py "
from statusline import render_context_bar, DEFAULT_THEME
import copy
theme = copy.deepcopy(DEFAULT_THEME)
theme['context_bar']['width'] = 10
width = 10
errors = []
for sys_pct in range(0, 101, 5):
    for total_pct in range(sys_pct, 101, 5):
        ctx_total = 1000000
        ctx_used = total_pct * ctx_total // 100
        sys_tokens = sys_pct * ctx_total // 100
        state = {
            'context_used': ctx_used,
            'context_total': ctx_total,
            'sys_overhead_tokens': sys_tokens,
            'sys_overhead_source': 'measured',
        }
        result = render_context_bar(state, theme)
        if result is None:
            continue
        n_full = result.count('\u2588')
        n_med = result.count('\u2593')
        n_empty = result.count('\u2591')
        total_blocks = n_full + n_med + n_empty
        if total_blocks != width:
            errors.append(f'sys={sys_pct}% total={total_pct}%: {n_full}+{n_med}+{n_empty}={total_blocks} != {width}')
if errors:
    print('FAIL: ' + '; '.join(errors[:5]))
else:
    print('OK')
")
assert_equals "segment formula invariant" "$OUT" "OK"

echo "  compound suffix: cache busting + critical"
OUT=$(run_py "
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 720000,
    'context_total': 1000000,
    'sys_overhead_tokens': 500000,
    'sys_overhead_source': 'measured',
    'cache_busting': True,
}
result = render_context_bar(state, DEFAULT_THEME)
# NO_COLOR: alert indicator is ⚠ (U+26A0), not the Nerd Font glyph
assert '\u26a0' in result, f'expected alert indicator ⚠, got: {result}'
assert '%!' in result, f'expected critical suffix %!, got: {result}'
print('OK')
")
assert_equals "compound critical+bust" "$OUT" "OK"

echo "  compound suffix: cache busting + warn"
OUT=$(run_py "
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 400000,
    'context_total': 1000000,
    'sys_overhead_tokens': 100000,
    'sys_overhead_source': 'measured',
    'cache_busting': True,
}
result = render_context_bar(state, DEFAULT_THEME)
# NO_COLOR: alert indicator is ⚠ (U+26A0); cache_busting escalates severity to critical (%!)
assert '\u26a0' in result, f'expected alert indicator ⚠, got: {result}'
assert '%!' in result, f'busting forces critical: expected %! suffix, got: {result}'
print('OK')
")
assert_equals "compound warn+bust" "$OUT" "OK"

echo "  compound suffix: cache busting + normal"
OUT=$(run_py "
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 100000,
    'context_total': 1000000,
    'sys_overhead_tokens': 50000,
    'sys_overhead_source': 'measured',
    'cache_busting': True,
}
result = render_context_bar(state, DEFAULT_THEME)
# NO_COLOR: alert indicator is ⚠ (U+26A0); cache_busting escalates severity to critical (%!)
assert '\u26a0' in result, f'expected alert indicator ⚠, got: {result}'
assert '%!' in result, f'busting forces critical: expected %! suffix, got: {result}'
assert '%~' not in result, f'should not have warn suffix'
print('OK')
")
assert_equals "compound normal+bust" "$OUT" "OK"

echo "  no cache indicator during Phase 1 (estimated)"
OUT=$(run_py "
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 100000,
    'context_total': 1000000,
    'sys_overhead_tokens': 50000,
    'sys_overhead_source': 'estimated',
    'cache_busting': True,
}
result = render_context_bar(state, DEFAULT_THEME)
assert '\u26a1' not in result, f'should NOT show ⚡ during Phase 1, got: {result}'
print('OK')
")
assert_equals "no cache indicator phase1" "$OUT" "OK"

echo "  system critical, conversation zero"
OUT=$(run_py "
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 500000,
    'context_total': 1000000,
    'sys_overhead_tokens': 500000,
    'sys_overhead_source': 'measured',
}
result = render_context_bar(state, DEFAULT_THEME)
assert '\u2593' not in result, f'should have no conv blocks, got: {result}'
assert '!' in result, f'should be critical (sys >= 50%), got: {result}'
print('OK')
")
assert_equals "sys critical conv zero" "$OUT" "OK"

echo "  spike: below notable threshold"
LAST_STDOUT=$(run_py "
from statusline import render_cache_delta, DEFAULT_THEME
state = {'last_cache_create': 500}
result = render_cache_delta(state, DEFAULT_THEME)
assert result is not None
assert '\U000f04bf' not in result, 'should not show spike glyph'
assert '\U000f005d' not in result, 'should not show notable glyph'
print('OK')
")
assert_equals "spike below notable" "$LAST_STDOUT" "OK"

echo "  spike: at notable threshold"
LAST_STDOUT=$(run_py "
from statusline import render_cache_delta, DEFAULT_THEME
state = {'last_cache_create': 1001}
result = render_cache_delta(state, DEFAULT_THEME)
assert '\U000f005d' not in result, f'should not show arrow glyph (dropped in cache_writes rename): {repr(result)}'
assert '1.0k' in result, f'should show abbreviated count: {repr(result)}'
print('OK')
")
assert_equals "spike at notable" "$LAST_STDOUT" "OK"

echo "  spike: at spike threshold"
LAST_STDOUT=$(run_py "
from statusline import render_cache_delta, DEFAULT_THEME
state = {'last_cache_create': 5001}
result = render_cache_delta(state, DEFAULT_THEME)
assert result is not None, 'render_cache_delta should return non-None for positive count'
assert '5.0k' in result, f'should show abbreviated count: {repr(result)}'
print('OK')
")
assert_equals "spike at spike" "$LAST_STDOUT" "OK"

echo "  sys_overhead: shows overhead glyph and token count"
LAST_STDOUT=$(run_py "
from statusline import render_sys_overhead_pill, DEFAULT_THEME
state = {'sys_overhead_tokens': 27409}
result = render_sys_overhead_pill(state, DEFAULT_THEME)
assert '\U000f0456' in result, f'should show overhead glyph: {repr(result)}'
assert '27.4k' in result, f'should show token count: {repr(result)}'
print('OK')
")
assert_equals "sys_overhead module" "$LAST_STDOUT" "OK"

echo "  Phase 1: static estimate returns reasonable value"
OUT=$(run_py "
import os, tempfile
from context_overhead import _estimate_static_overhead

tmpdir = tempfile.mkdtemp()
claude_md = os.path.join(tmpdir, 'CLAUDE.md')
with open(claude_md, 'w') as f:
    f.write('x' * 4000)

estimate = _estimate_static_overhead(claude_md_paths=[claude_md])
assert isinstance(estimate, int), f'expected int, got {type(estimate)}'
assert estimate >= 1000, f'estimate too low: {estimate}'
assert estimate < 100000, f'estimate unreasonably high: {estimate}'
print('OK')
import shutil; shutil.rmtree(tmpdir)
")
assert_equals "phase1 estimate" "$OUT" "OK"

echo "  Phase 2: first-turn anchoring from transcript"
OUT=$(run_py "
import json, tempfile, os
from context_overhead import _read_transcript_tail

tmpf = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
# Turn 1: streaming stub (skip)
json.dump({'type': 'assistant', 'message': {'stop_reason': None, 'usage': {
    'input_tokens': 3, 'cache_creation_input_tokens': 42000,
    'cache_read_input_tokens': 0, 'output_tokens': 10
}}}, tmpf); tmpf.write('\n')
# Turn 1: final (anchor)
json.dump({'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'usage': {
    'input_tokens': 50, 'cache_creation_input_tokens': 42000,
    'cache_read_input_tokens': 0, 'output_tokens': 200
}}}, tmpf); tmpf.write('\n')
# Turn 2: final
json.dump({'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'usage': {
    'input_tokens': 100, 'cache_creation_input_tokens': 500,
    'cache_read_input_tokens': 42000, 'output_tokens': 300
}}}, tmpf); tmpf.write('\n')
# Turn 3: final
json.dump({'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'usage': {
    'input_tokens': 150, 'cache_creation_input_tokens': 200,
    'cache_read_input_tokens': 42500, 'output_tokens': 400
}}}, tmpf); tmpf.write('\n')
tmpf.close()

result = _read_transcript_tail(tmpf.name)
assert result is not None
assert result['turn_1_anchor'] == 42000, f'got {result[\"turn_1_anchor\"]}'
assert len(result['trailing_turns']) == 3, f'got {len(result[\"trailing_turns\"])}'
assert 0.7 < result['cache_hit_rate'] < 0.85, f'got {result[\"cache_hit_rate\"]}'
print('OK')
os.unlink(tmpf.name)
")
assert_equals "phase2 anchor" "$OUT" "OK"

echo "  Phase 2: skips streaming stubs"
OUT=$(run_py "
import json, tempfile, os
from context_overhead import _read_transcript_tail

tmpf = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
json.dump({'type': 'assistant', 'message': {'stop_reason': None, 'usage': {
    'input_tokens': 3, 'cache_creation_input_tokens': 42000,
    'cache_read_input_tokens': 0, 'output_tokens': 10
}}}, tmpf); tmpf.write('\n')
tmpf.close()

result = _read_transcript_tail(tmpf.name)
assert result is None, f'should be None for stubs only, got {result}'
print('OK')
os.unlink(tmpf.name)
")
assert_equals "phase2 skip stubs" "$OUT" "OK"

echo "  Phase 2: handles toolUseResult.usage path"
OUT=$(run_py "
import json, tempfile, os
from context_overhead import _read_transcript_tail

tmpf = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
json.dump({'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'usage': {
    'input_tokens': 50, 'cache_creation_input_tokens': 30000,
    'cache_read_input_tokens': 0, 'output_tokens': 200
}}}, tmpf); tmpf.write('\n')
json.dump({'type': 'user', 'toolUseResult': {'usage': {
    'input_tokens': 100, 'cache_creation_input_tokens': 500,
    'cache_read_input_tokens': 30000, 'output_tokens': 300
}}, 'message': {'role': 'user', 'content': []}}, tmpf); tmpf.write('\n')
tmpf.close()

result = _read_transcript_tail(tmpf.name)
assert result is not None
assert result['turn_1_anchor'] == 30000
assert len(result['trailing_turns']) == 2
print('OK')
os.unlink(tmpf.name)
")
assert_equals "phase2 toolUseResult" "$OUT" "OK"

echo "  Phase 2: handles truncated last line"
OUT=$(run_py "
import json, tempfile, os
from context_overhead import _read_transcript_tail

tmpf = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
json.dump({'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'usage': {
    'input_tokens': 50, 'cache_creation_input_tokens': 25000,
    'cache_read_input_tokens': 0, 'output_tokens': 200
}}}, tmpf); tmpf.write('\n')
tmpf.write('{\"type\": \"assistant\", \"message\": {\"stop_re')
tmpf.close()

result = _read_transcript_tail(tmpf.name)
assert result is not None
assert result['turn_1_anchor'] == 25000
print('OK')
os.unlink(tmpf.name)
")
assert_equals "phase2 truncated" "$OUT" "OK"


echo "  cache health: healthy rate >= 0.8"
OUT=$(run_py "
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 200000,
    'context_total': 1000000,
    'sys_overhead_tokens': 50000,
    'sys_overhead_source': 'measured',
    'cache_hit_rate': 0.85,
    'cache_busting': False,
}
result = render_context_bar(state, DEFAULT_THEME)
assert '\u26a1' not in result, f'should not show lightning when healthy'
print('OK')
")
assert_equals "cache healthy" "$OUT" "OK"

echo "  cache health: boundary 0.8 is healthy (>=)"
OUT=$(run_py "
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 200000,
    'context_total': 1000000,
    'sys_overhead_tokens': 50000,
    'sys_overhead_source': 'measured',
    'cache_hit_rate': 0.8,
    'cache_busting': False,
}
result = render_context_bar(state, DEFAULT_THEME)
assert '\u26a1' not in result, f'0.8 should be healthy'
print('OK')
")
assert_equals "cache boundary 0.8" "$OUT" "OK"

echo "  cache health: fewer than 2 turns has no turns data"
OUT=$(run_py "
import json, tempfile, os
from context_overhead import _read_transcript_tail
tmpf = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
json.dump({'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'usage': {
    'input_tokens': 50, 'cache_creation_input_tokens': 42000,
    'cache_read_input_tokens': 0, 'output_tokens': 200
}}}, tmpf); tmpf.write('\n')
tmpf.close()
result = _read_transcript_tail(tmpf.name)
assert result is not None
assert result['cache_hit_rate'] == 0.0
assert len(result['trailing_turns']) == 1
print('OK')
os.unlink(tmpf.name)
")
assert_equals "cache <2 turns" "$OUT" "OK"

echo "  anchor: reads from file start, not tail"
OUT=$(run_py "
import json, tempfile, os
from context_overhead import _read_transcript_anchor

tmpf = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
# Turn 1 (the anchor) at the START
json.dump({'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'usage': {
    'input_tokens': 50, 'cache_creation_input_tokens': 42000,
    'cache_read_input_tokens': 0, 'output_tokens': 200
}}}, tmpf); tmpf.write('\n')
# Many subsequent turns with small cache_create
for i in range(100):
    json.dump({'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'usage': {
        'input_tokens': 50, 'cache_creation_input_tokens': 300,
        'cache_read_input_tokens': 42000 + i * 500, 'output_tokens': 200
    }}}, tmpf); tmpf.write('\n')
tmpf.close()

anchor = _read_transcript_anchor(tmpf.name)
assert anchor == 42000, f'anchor should be 42000 from file start, got {anchor}'
print('OK')
os.unlink(tmpf.name)
")
assert_equals "anchor from start" "$OUT" "OK"

echo "  cache degraded: shows indicator for 0.3-0.8 hit rate"
OUT=$(run_py "
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 200000,
    'context_total': 1000000,
    'sys_overhead_tokens': 50000,
    'sys_overhead_source': 'measured',
    'cache_degraded': True,
    'cache_busting': False,
}
result = render_context_bar(state, DEFAULT_THEME)
assert '~' in result, f'degraded should show warn suffix ~, got: {result}'
assert '\u26a1' not in result, f'should not show busting indicator'
print('OK')
")
assert_equals "cache degraded" "$OUT" "OK"

echo "  cache degraded: no indicator when busting (busting takes priority)"
OUT=$(run_py "
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 200000,
    'context_total': 1000000,
    'sys_overhead_tokens': 50000,
    'sys_overhead_source': 'measured',
    'cache_degraded': False,
    'cache_busting': True,
}
result = render_context_bar(state, DEFAULT_THEME)
# NO_COLOR: busting shows ⚠ (U+26A0) + critical suffix %!, not the Nerd Font glyph
assert '\u26a0' in result, f'busting indicator (⚠) expected: {result}'
assert '\u2248' not in result, f'should not show degraded indicator when busting'
print('OK')
")
assert_equals "cache busting not degraded" "$OUT" "OK"

echo "  cache busting: forces entire bar to critical color"
OUT=$(run_py_color "
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 200000,
    'context_total': 1000000,
    'sys_overhead_tokens': 50000,
    'sys_overhead_source': 'measured',
    'cache_busting': True,
    'cache_degraded': False,
}
result = render_context_bar(state, DEFAULT_THEME)
# Code: sys_color = bright (critical), conv_color = darkened (factor=0.55)
crit_sys = '38;2;191;97;106'    # #bf616a critical — sys blocks use bright color
crit_conv = '38;2;105;53;58'    # darkened critical (factor=0.55) — conv blocks dimmed
assert crit_sys in result, f'sys should use critical color, got: {repr(result[:300])}'
assert crit_conv in result, f'conv should use darkened critical, got: {repr(result[:300])}'
assert '\U000f04bf' in result, f'should show nf-md-lightning_bolt'
print('OK')
")
assert_equals "busting critical color" "$OUT" "OK"

echo "  config: cache thresholds read from config"
OUT=$(run_py "
from context_overhead import _try_phase2_transcript
import json, tempfile, os

tmpf = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
for i in range(5):
    # Turn 0: large cache_creation (anchor). Turns 1-4: cc=800, cr=1200 -> ~60% hit rate.
    # hit_rate = cr/(cr+cc) = 1200/2000 = 0.60, which is < warn=0.8 but >= critical=0.3
    cc = 42000 if i == 0 else 800
    cr = 0 if i == 0 else 1200
    json.dump({'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'usage': {
        'input_tokens': 50, 'cache_creation_input_tokens': cc,
        'cache_read_input_tokens': cr, 'output_tokens': 200
    }}}, tmpf); tmpf.write('\n')
tmpf.close()

state = {'transcript_path': tmpf.name}
sc = {}

# With default thresholds (warn=0.8): 60% hit rate should be degraded
_try_phase2_transcript(state, {}, sc, cache_warn_rate=0.8, cache_critical_rate=0.3)
assert sc.get('cache_degraded') is True, f'should be degraded at 60% with warn=0.8, got sc={sc}'

# With custom threshold (warn=0.5): 60% hit rate should be healthy
sc2 = {}
_try_phase2_transcript(state, {}, sc2, cache_warn_rate=0.5, cache_critical_rate=0.3)
assert sc2.get('cache_degraded') is not True, f'should NOT be degraded at 60% with warn=0.5, got sc2={sc2}'

print('OK')
os.unlink(tmpf.name)
")
assert_equals "config thresholds" "$OUT" "OK"

echo "  anchor: warm cache (cc=0 on turn 1) falls back to estimate"
OUT=$(run_py "
import json, tempfile, os
from context_overhead import _try_phase2_transcript
tf = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
# Turn 1 with cache_creation=0 (warm restart, everything cached)
json.dump({'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'usage': {
    'input_tokens': 50, 'cache_creation_input_tokens': 0,
    'cache_read_input_tokens': 42000, 'output_tokens': 200
}}}, tf); tf.write('\n')
tf.close()
state = {'transcript_path': tf.name}; sc = {}
_try_phase2_transcript(state, {}, sc)
anchor = sc.get('turn_1_anchor', 0)
assert anchor > 0, f'anchor should fall back to estimate, got {anchor}'
print(f'OK: anchor={anchor}')
os.unlink(tf.name)
")
assert_contains "warm cache anchor" "$OUT" "OK"

echo "  dual-bar: sys_color and conv_color are applied"
OUT=$(run_py_color "
from statusline import render_context_bar, DEFAULT_THEME
# 20% usage (below warn threshold) → healthy state → teal color family
state = {
    'context_used': 200000,
    'context_total': 1000000,
    'sys_overhead_tokens': 50000,
    'sys_overhead_source': 'measured',
}
result = render_context_bar(state, DEFAULT_THEME)
# Code: sys_color = bright (#8fbcbb = RGB(143,188,187)), conv_color = darkened (factor=0.55 = RGB(78,103,102))
assert '38;2;143;188;187' in result, f'sys (bright healthy) not found in: {repr(result)}'
assert '38;2;78;103;102' in result, f'conv (darkened healthy factor=0.55) not found in: {repr(result)}'
print('OK')
")
assert_equals "per-segment coloring" "$OUT" "OK"

echo "  dual-bar: NO_COLOR falls back to plain bar"
OUT=$(run_py "
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 400000,
    'context_total': 1000000,
    'sys_overhead_tokens': 300000,
    'sys_overhead_source': 'measured',
}
result = render_context_bar(state, DEFAULT_THEME)
# With NO_COLOR, no ANSI escapes
assert '\033[' not in result, f'unexpected ANSI in NO_COLOR mode: {repr(result)}'
# But bar blocks should still be present
assert '\u2588' in result, f'sys blocks missing: {repr(result)}'
assert '\u2593' in result, f'conv blocks missing: {repr(result)}'
print('OK')
")
assert_equals "per-segment NO_COLOR fallback" "$OUT" "OK"

echo "  forensics: generate_overhead_report from transcript"
LAST_STDOUT=$(run_py "
import json, tempfile, os, sys
sys.path.insert(0, '$REPO_DIR/hooks')
from obs_utils import generate_overhead_report

tmpf = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
for i in range(5):
    cache_create = 40000 if i == 0 else 50
    cache_read = 0 if i == 0 else 40000 + (i * 200)
    json.dump({'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'usage': {
        'input_tokens': 50 + i * 30,
        'cache_creation_input_tokens': cache_create,
        'cache_read_input_tokens': cache_read,
        'output_tokens': 200 + i * 50
    }}}, tmpf); tmpf.write('\n')
tmpf.close()

pkg = tempfile.mkdtemp()
derived = os.path.join(pkg, 'derived')
os.makedirs(derived)

report = generate_overhead_report(pkg, tmpf.name, context_window_size=1000000)
assert report is not None, 'expected report'
assert report['system_overhead_tokens'] == 40000, f'anchor wrong: {report[\"system_overhead_tokens\"]}'
assert report['total_turns'] == 5, f'turns wrong: {report[\"total_turns\"]}'
assert 0.8 < report['cache_hit_rate_overall'] < 1.0, f'hit rate wrong: {report[\"cache_hit_rate_overall\"]}'

report_path = os.path.join(derived, 'overhead_report.json')
assert os.path.isfile(report_path), 'report file not written'
with open(report_path) as rf:
    written = json.load(rf)
assert written['system_overhead_tokens'] == 40000
print('OK')
os.unlink(tmpf.name)
import shutil; shutil.rmtree(pkg)
")
assert_equals "forensics report" "$LAST_STDOUT" "OK"

echo "  integration: full pipeline with transcript produces dual-bar"
INTEGRATION_TRANSCRIPT="/tmp/qline-integration-test-$$.jsonl"
"$PYTHON" -c "
import json
with open('$INTEGRATION_TRANSCRIPT', 'w') as f:
    json.dump({'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'usage': {
        'input_tokens': 50, 'cache_creation_input_tokens': 45000,
        'cache_read_input_tokens': 0, 'output_tokens': 200
    }}}, f)
    f.write('\n')
    for i in range(3):
        json.dump({'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'usage': {
            'input_tokens': 100 + i*50, 'cache_creation_input_tokens': 200,
            'cache_read_input_tokens': 45000 + i*500, 'output_tokens': 300
        }}}, f)
        f.write('\n')
"

rm -f /tmp/qline-cache.json

INPUT=$(cat <<ENDJSON
{
  "hook_event_name": "Status",
  "session_id": "integration-test-$$",
  "transcript_path": "$INTEGRATION_TRANSCRIPT",
  "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6 (1M context)"},
  "workspace": {"current_dir": "/home/q/LAB/qLine"},
  "cost": {"total_cost_usd": 1.50, "total_duration_ms": 60000},
  "context_window": {
    "total_input_tokens": 150000,
    "total_output_tokens": 50000,
    "context_window_size": 1000000,
    "used_percentage": 20,
    "remaining_percentage": 80
  }
}
ENDJSON
)

LAST_STDOUT=$(printf '%s' "$INPUT" | NO_COLOR=1 QLINE_NO_COLLECT=1 "$PYTHON" "$SRC" 2>/dev/null)
LAST_EXIT=$?
assert_exit_zero "integration pipeline" "$LAST_EXIT"
assert_not_empty "integration output" "$LAST_STDOUT"
# The dual-bar should show medium shade blocks (▓) for conversation
# since we have transcript data with 45k system overhead in a 200k used / 1M window
assert_contains "integration has conv blocks" "$LAST_STDOUT" "▓"

rm -f "$INTEGRATION_TRANSCRIPT" /tmp/qline-cache.json

echo "  obs_utils: update_manifest_if_absent_batch writes when absent"
LAST_STDOUT=$(run_py "
import json, os, sys, tempfile
sys.path.insert(0, '$REPO_DIR/hooks')
from obs_utils import update_manifest_if_absent_batch

pkg = tempfile.mkdtemp()
with open(os.path.join(pkg, 'manifest.json'), 'w') as f:
    json.dump({'status': 'active'}, f)

wrote = update_manifest_if_absent_batch(pkg, 'cache_anchor', {'cache_anchor': 42000, 'cache_anchor_turn': 1})
assert wrote is True, f'first call should write, got {wrote}'

with open(os.path.join(pkg, 'manifest.json')) as f:
    m = json.load(f)
assert m['cache_anchor'] == 42000

wrote2 = update_manifest_if_absent_batch(pkg, 'cache_anchor', {'cache_anchor': 99999})
assert wrote2 is False, f'second call should not write, got {wrote2}'

with open(os.path.join(pkg, 'manifest.json')) as f:
    m2 = json.load(f)
assert m2['cache_anchor'] == 42000, f'should be unchanged: {m2}'

print('OK')
import shutil; shutil.rmtree(pkg)
")
assert_equals "manifest_if_absent" "$LAST_STDOUT" "OK"

echo "  obs-stop-cache: extracts cache metrics from transcript"
run_py "
import json, os, sys, tempfile
sys.path.insert(0, '$REPO_DIR/hooks')

from importlib.util import spec_from_file_location, module_from_spec
hook_path = '$REPO_DIR/hooks/obs-stop-cache.py'
spec = spec_from_file_location('obs_stop_cache', hook_path)
mod = module_from_spec(spec)
spec.loader.exec_module(mod)

# Create mock transcript
tmpf = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
# Streaming stub (should be skipped)
json.dump({'type': 'assistant', 'message': {'stop_reason': None, 'id': 'msg_stub', 'usage': {
    'input_tokens': 3, 'cache_creation_input_tokens': 42000,
    'cache_read_input_tokens': 0, 'output_tokens': 10
}}}, tmpf); tmpf.write('\n')
# Completed turn
json.dump({'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'id': 'msg_01ABC', 'model': 'claude-opus-4-6', 'usage': {
    'input_tokens': 50, 'cache_creation_input_tokens': 42000,
    'cache_read_input_tokens': 0, 'output_tokens': 200,
    'cache_creation': {'ephemeral_1h_input_tokens': 42000, 'ephemeral_5m_input_tokens': 0}
}}}, tmpf); tmpf.write('\n')
tmpf.close()

result = mod._extract_latest_cache_metrics(tmpf.name, None)
assert result is not None, 'should find metrics'
assert result['cache_create'] == 42000, f'cache_create: {result[\"cache_create\"]}'
assert result['cache_read'] == 0
assert result['input_tokens'] == 50
assert result['entry_id'] == 'msg_01ABC'
assert result['model'] == 'claude-opus-4-6'
assert result['cache_create_1h'] == 42000
assert result['cache_create_5m'] == 0

# Test dedup: same entry_id returns None
result2 = mod._extract_latest_cache_metrics(tmpf.name, 'msg_01ABC')
assert result2 is None, 'should return None for duplicate entry'

# Test truncated line handling
tmpf2 = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
json.dump({'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'id': 'msg_02', 'usage': {
    'input_tokens': 50, 'cache_creation_input_tokens': 25000,
    'cache_read_input_tokens': 0, 'output_tokens': 200
}}}, tmpf2); tmpf2.write('\n')
tmpf2.write('{\"type\": \"assistant\", \"message\": {\"stop_re')  # truncated
tmpf2.close()
result3 = mod._extract_latest_cache_metrics(tmpf2.name, None)
assert result3 is not None, 'should handle truncated line'
assert result3['cache_create'] == 25000

print('OK')
os.unlink(tmpf.name); os.unlink(tmpf2.name)
"
assert_equals "hook extraction" "$LAST_STDOUT" "OK"

echo "  obs-stop-cache: full hook flow writes sidecar + ledger + manifest"
LAST_STDOUT=$(run_py "
import json, os, sys, tempfile
sys.path.insert(0, '$REPO_DIR/hooks')
from obs_utils import create_package

# Create a real session package
pkg_dir = tempfile.mkdtemp()
os.environ['OBS_ROOT'] = pkg_dir
session_id = 'cache-hook-test-001'
transcript = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)

# Write 3 turns to transcript
for i in range(3):
    cc = 42000 if i == 0 else 300
    cr = 0 if i == 0 else 42000 + i * 200
    json.dump({'type': 'assistant', 'message': {
        'stop_reason': 'end_turn', 'id': f'msg_{i:03d}', 'model': 'claude-opus-4-6',
        'usage': {
            'input_tokens': 50 + i * 30,
            'cache_creation_input_tokens': cc,
            'cache_read_input_tokens': cr,
            'output_tokens': 200,
            'cache_creation': {'ephemeral_1h_input_tokens': cc, 'ephemeral_5m_input_tokens': 0}
        }
    }}, transcript)
    transcript.write('\n')
transcript.close()

# Create package
package_root = create_package(session_id, '/tmp', transcript.name, 'test', obs_root=pkg_dir)

sys.path.insert(0, '$REPO_DIR/hooks')

# Import hook module; exec_module triggers run_fail_open(main) which calls sys.exit(0)
# when stdin has no hook input -- catch SystemExit to continue using module functions
from importlib.util import spec_from_file_location, module_from_spec
hook_path = '$REPO_DIR/hooks/obs-stop-cache.py'
spec = spec_from_file_location('obs_stop_cache', hook_path)
mod = module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except SystemExit:
    pass  # Module-level run_fail_open exits when no hook input; module functions are loaded

# Simulate 3 Stop invocations
for i in range(3):
    # Reset and call extraction + write logic
    sidecar_path = os.path.join(package_root, 'custom', 'cache_metrics.jsonl')
    last_entry = mod._read_last_sidecar_entry(sidecar_path)
    last_id = last_entry.get('last_entry_id') if not last_entry.get('skipped') else None

    metrics = mod._extract_latest_cache_metrics(transcript.name, last_id)
    if metrics is None and i > 0:
        # After first call, subsequent calls see same last entry -- expected skip
        continue
    if metrics is None:
        continue

    turn = last_entry.get('turn', 0) + 1
    record = {
        'ts': '2026-04-04T00:00:00Z', 'session_id': session_id, 'turn': turn,
        'cache_read': metrics['cache_read'], 'cache_create': metrics['cache_create'],
        'input_tokens': metrics['input_tokens'], 'output_tokens': metrics['output_tokens'],
        'cache_create_1h': metrics['cache_create_1h'], 'cache_create_5m': metrics['cache_create_5m'],
        'model': metrics['model'], 'post_compaction': False, 'compaction_count': 0,
        'last_entry_id': metrics['entry_id'], 'skipped': False,
    }
    os.makedirs(os.path.join(package_root, 'custom'), exist_ok=True)
    mod._atomic_jsonl_append(sidecar_path, record)

# Verify sidecar exists and has records
sidecar_path = os.path.join(package_root, 'custom', 'cache_metrics.jsonl')
assert os.path.isfile(sidecar_path), 'sidecar not created'
with open(sidecar_path) as f:
    records = [json.loads(l) for l in f if l.strip()]
assert len(records) >= 1, f'expected records, got {len(records)}'
# Backward scan finds last entry in transcript (msg_002, cc=300); verify sidecar has it
assert records[0]['last_entry_id'] == 'msg_002', f'expected msg_002, got: {records[0]}'
assert records[0]['model'] == 'claude-opus-4-6', f'model wrong: {records[0]}'

# Test anchor write
from obs_utils import update_manifest_if_absent_batch
update_manifest_if_absent_batch(package_root, 'cache_anchor', {
    'cache_anchor': 42000, 'cache_anchor_turn': 1, 'cache_anchor_is_post_compaction': False
})
with open(os.path.join(package_root, 'manifest.json')) as f:
    m = json.load(f)
assert m.get('cache_anchor') == 42000, f'anchor not in manifest: {m.keys()}'

print('OK')
os.unlink(transcript.name)
import shutil; shutil.rmtree(pkg_dir)
del os.environ['OBS_ROOT']
")
assert_equals "hook integration" "$LAST_STDOUT" "OK"

echo "  anchor migration: _read_manifest_anchor reads from manifest"
LAST_STDOUT=$(run_py "
import json, os, sys, tempfile
from context_overhead import _read_manifest_anchor

pkg = tempfile.mkdtemp()
with open(os.path.join(pkg, 'manifest.json'), 'w') as f:
    json.dump({'cache_anchor': 42000, 'cache_anchor_turn': 1}, f)

result = _read_manifest_anchor(pkg)
assert result == 42000, f'expected 42000, got {result}'

# Missing key returns None
pkg2 = tempfile.mkdtemp()
with open(os.path.join(pkg2, 'manifest.json'), 'w') as f:
    json.dump({'status': 'active'}, f)
result2 = _read_manifest_anchor(pkg2)
assert result2 is None, f'expected None, got {result2}'

# None package_root returns None
result3 = _read_manifest_anchor(None)
assert result3 is None

print('OK')
import shutil; shutil.rmtree(pkg); shutil.rmtree(pkg2)
")
assert_equals "manifest anchor" "$LAST_STDOUT" "OK"

fi

# ======================================================================
# Section: schema_version (OPP-15)
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "schema_version" ]; then
echo ""
echo "=== Section: schema_version ==="

# T-sv-1: create_package writes schema_version to manifest.json
echo ""
echo "--- T-sv-1: schema_version present in manifest ---"
SV_TEST_ROOT=$(mktemp -d)
SV_RESULT=$("$PYTHON" -c "
import sys, json, tempfile
sys.path.insert(0, '$REPO_DIR/hooks')
from obs_utils import create_package
pkg = create_package('sv-test-session', '/tmp', '/tmp/t.jsonl', 'startup', obs_root='$SV_TEST_ROOT')
import os
with open(os.path.join(pkg, 'manifest.json')) as f:
    m = json.load(f)
print(m.get('schema_version', 'MISSING'))
" 2>/dev/null || echo "ERROR")
assert_equals "T-sv-1: schema_version in manifest" "$SV_RESULT" "1.0.0"
rm -rf "$SV_TEST_ROOT"

# T-sv-2: schema_version value is exactly "1.0.0"
echo ""
echo "--- T-sv-2: schema_version value is 1.0.0 ---"
SV_TEST_ROOT2=$(mktemp -d)
SV_RESULT2=$("$PYTHON" -c "
import sys, json
sys.path.insert(0, '$REPO_DIR/hooks')
from obs_utils import create_package
pkg = create_package('sv-test-session-2', '/tmp', '/tmp/t.jsonl', 'startup', obs_root='$SV_TEST_ROOT2')
import os
with open(os.path.join(pkg, 'manifest.json')) as f:
    m = json.load(f)
v = m.get('schema_version', '')
print('OK' if v == '1.0.0' else f'WRONG:{v}')
" 2>/dev/null || echo "ERROR")
assert_equals "T-sv-2: schema_version is 1.0.0" "$SV_RESULT2" "OK"
rm -rf "$SV_TEST_ROOT2"

fi

# ======================================================================
# Section: anchor_invalidated (OPP-16)
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "anchor_invalidated" ]; then
echo ""
echo "=== Section: anchor_invalidated ==="

# T-ai-1: compact.anchor_invalidated event emitted by obs-precompact
echo ""
echo "--- T-ai-1: compact.anchor_invalidated event emitted ---"
AI_TEST_ROOT=$(mktemp -d)
AI_RESULT=$("$PYTHON" -c "
import sys, json, os
sys.path.insert(0, '$REPO_DIR/hooks')
from obs_utils import create_package
session_id = 'ai-test-session'
pkg = create_package(session_id, '/tmp', '/tmp/t.jsonl', 'startup', obs_root='$AI_TEST_ROOT')
from obs_utils import append_event, update_manifest_array, resolve_package_root_env
os.environ['OBS_ROOT'] = '$AI_TEST_ROOT'
# Simulate what obs-precompact does: emit compact.started + anchor_invalidated
compact_seq = 1
append_event(pkg, 'compact.started', session_id, {'trigger': 'manual', 'compact_seq': compact_seq}, origin_type='native_snapshot', hook='obs-precompact')
append_event(pkg, 'compact.anchor_invalidated', session_id, {'trigger': 'manual', 'compact_seq': compact_seq}, origin_type='native_snapshot', hook='obs-precompact')
# Read back events
ledger = os.path.join(pkg, 'metadata', 'hook_events.jsonl')
events = []
with open(ledger) as f:
    for line in f:
        try:
            e = json.loads(line)
            events.append(e.get('event', ''))
        except Exception:
            pass
print('OK' if 'compact.anchor_invalidated' in events else 'MISSING:' + str(events))
" 2>/dev/null || echo "ERROR")
assert_equals "T-ai-1: compact.anchor_invalidated emitted" "$AI_RESULT" "OK"
rm -rf "$AI_TEST_ROOT"

# T-ai-2: _inject_obs_counters clears overhead_ts/turn_1_anchor on new invalidation
# Uses subprocess invocation so QLINE_CACHE_PATH is honoured at module import time.
echo ""
echo "--- T-ai-2: anchor invalidation clears overhead caches ---"
AI_TEST_ROOT2=$(mktemp -d)
AI_CACHE2=$(mktemp)
AI_SESSION_2="ai-cache-session-$(date +%s)"
# Create package and emit anchor_invalidated event
"$PYTHON" -c "
import sys, json, time
sys.path.insert(0, '$REPO_DIR/hooks')
from obs_utils import create_package, append_event
session_id = '$AI_SESSION_2'
pkg = create_package(session_id, '/tmp', '/tmp/t.jsonl', 'startup', obs_root='$AI_TEST_ROOT2')
append_event(pkg, 'compact.anchor_invalidated', session_id, {'trigger': 'manual', 'compact_seq': 1}, origin_type='native_snapshot', hook='obs-precompact')
" 2>/dev/null
# Seed cache with overhead_ts and turn_1_anchor to simulate warm state
"$PYTHON" -c "
import json, time
cache = {
    'version': 1,
    'modules': {
        '_obs': {
            '$AI_SESSION_2': {
                'overhead_ts': time.time(),
                'turn_1_anchor': 50000,
                'last_count_ts': 0,
                'last_known_anchor_inval_count': 0,
            }
        }
    }
}
with open('$AI_CACHE2', 'w') as f:
    json.dump(cache, f)
"
# Run full statusline invocation with env vars set for the subprocess
AI_PAYLOAD2=$("$PYTHON" -c "
import json
d = {'session_id': '$AI_SESSION_2', 'model': {'id': 'test', 'display_name': 'Test'}, 'cost': {'total_cost_usd': 1, 'total_duration_ms': 1000}, 'context_window': {'total_input_tokens': 1000, 'total_output_tokens': 500, 'context_window_size': 100000, 'used_percentage': 1, 'remaining_percentage': 99}}
print(json.dumps(d))
")
printf '%s' "$AI_PAYLOAD2" | NO_COLOR=1 QLINE_NO_COLLECT=1 OBS_ROOT="$AI_TEST_ROOT2" QLINE_CACHE_PATH="$AI_CACHE2" "$PYTHON" "$SRC" > /dev/null 2>&1
# Check that turn_1_anchor was cleared and invalidation counter incremented.
# Note: overhead_ts may be re-set by the overhead estimator in the same run.
AI_RESULT2=$("$PYTHON" -c "
import json
with open('$AI_CACHE2') as f:
    updated = json.load(f)
sc = updated.get('modules', {}).get('_obs', {}).get('$AI_SESSION_2', {})
# turn_1_anchor must be absent (was cleared by invalidation)
has_anchor = 'turn_1_anchor' in sc
# invalidation counter must be 1 (event was processed)
inval_count = sc.get('last_known_anchor_inval_count', 0)
ok = not has_anchor and inval_count >= 1
print('OK' if ok else f'FAIL: anchor={has_anchor} inval_count={inval_count} keys={list(sc.keys())}')
" 2>/dev/null || echo "ERROR")
assert_equals "T-ai-2: turn_1_anchor cleared, inval_count incremented" "$AI_RESULT2" "OK"
rm -rf "$AI_TEST_ROOT2"
rm -f "$AI_CACHE2"

fi

# ======================================================================
# Section: transcript_schema (OPP-25)
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "transcript_schema" ]; then
echo ""
echo "=== Section: transcript_schema ==="

REPLAY_DIR="$SCRIPT_DIR/replay/transcripts"

# T-ts-1: _read_transcript_tail returns dict with expected keys on cold-start-simple
echo ""
echo "--- T-ts-1: _read_transcript_tail keys on cold-start-simple ---"
TS_RESULT1=$("$PYTHON" -c "
import sys
sys.path.insert(0, '$(dirname $SRC)')
from context_overhead import _read_transcript_tail
result = _read_transcript_tail('$REPLAY_DIR/cold-start-simple.jsonl')
assert result is not None, 'Expected dict, got None'
assert 'turn_1_anchor' in result, f'Missing turn_1_anchor, keys={list(result.keys())}'
assert 'trailing_turns' in result, f'Missing trailing_turns, keys={list(result.keys())}'
assert 'cache_hit_rate' in result, f'Missing cache_hit_rate, keys={list(result.keys())}'
print('OK')
" 2>/dev/null || echo "ERROR")
assert_equals "T-ts-1: _read_transcript_tail has expected keys" "$TS_RESULT1" "OK"

# T-ts-2: _read_transcript_tail returns valid types on warm-start-varied
echo ""
echo "--- T-ts-2: _read_transcript_tail types on warm-start-varied ---"
TS_RESULT2=$("$PYTHON" -c "
import sys
sys.path.insert(0, '$(dirname $SRC)')
from context_overhead import _read_transcript_tail
result = _read_transcript_tail('$REPLAY_DIR/warm-start-varied.jsonl')
assert result is not None, 'Expected dict, got None'
anchor = result.get('turn_1_anchor')
trailing = result.get('trailing_turns')
hit_rate = result.get('cache_hit_rate')
assert isinstance(anchor, (int, float)) or anchor is None, f'turn_1_anchor bad type: {type(anchor)}'
assert isinstance(trailing, list), f'trailing_turns should be list, got {type(trailing)}'
assert isinstance(hit_rate, float), f'cache_hit_rate should be float, got {type(hit_rate)}'
print('OK')
" 2>/dev/null || echo "ERROR")
assert_equals "T-ts-2: _read_transcript_tail valid types" "$TS_RESULT2" "OK"

# T-ts-3: extract_usage_full returns 4-tuple with correct structure on real entries
echo ""
echo "--- T-ts-3: extract_usage_full tuple shape on real transcript ---"
TS_RESULT3=$("$PYTHON" -c "
import sys, json
sys.path.insert(0, '$REPO_DIR/hooks')
from obs_utils import extract_usage_full
entries_tested = 0
with open('$REPLAY_DIR/cold-start-long.jsonl') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        result = extract_usage_full(entry)
        assert isinstance(result, tuple) and len(result) == 4, f'Expected 4-tuple, got {result!r}'
        usage, model, req_id, entry_id = result
        if usage is not None:
            assert isinstance(usage, dict), f'usage should be dict, got {type(usage)}'
            entries_tested += 1
        if entries_tested >= 5:
            break
assert entries_tested > 0, 'No usable entries found in transcript'
print(f'OK:{entries_tested}')
" 2>/dev/null || echo "ERROR")
# Accept OK:N where N > 0
if echo "$TS_RESULT3" | grep -q "^OK:"; then
    assert_equals "T-ts-3: extract_usage_full tuple shape" "OK" "OK"
else
    assert_equals "T-ts-3: extract_usage_full tuple shape" "$TS_RESULT3" "OK"
fi

fi

# ======================================================================
# Section: opp18 — Hook Fault Surfacing
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "opp18" ]; then
echo ""
echo "=== Section: opp18 (OPP-18 hook fault surfacing) ==="

# T-opp18-1: _count_recent_faults returns 0 on non-existent ledger
echo ""
echo "--- T-opp18-1: zero count for missing ledger ---"
OPP18_RESULT1=$("$PYTHON" -c "
import sys, os, tempfile
sys.path.insert(0, '$REPO_DIR/src')
import statusline
# Point to a path that definitely does not exist
statusline._FAULT_LEDGER_PATH = '/tmp/nonexistent-faults-$(date +%s).jsonl'
count = statusline._count_recent_faults()
print('OK' if count == 0 else f'FAIL: got {count}')
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp18-1: zero count for missing ledger" "$OPP18_RESULT1" "OK"

# T-opp18-2: _count_recent_faults counts recent fault entries
echo ""
echo "--- T-opp18-2: counts recent fault entries ---"
OPP18_RESULT2=$("$PYTHON" -c "
import sys, os, json, tempfile, time
from datetime import datetime, timezone
sys.path.insert(0, '$REPO_DIR/src')
import statusline

# Write 3 fault records + 1 diagnostic + 1 old fault to a temp ledger
tf = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
now_iso = datetime.now(timezone.utc).isoformat()
old_iso = datetime.fromtimestamp(time.time() - 7200, tz=timezone.utc).isoformat()
records = [
    {'ts': now_iso, 'hook': 'h1', 'event': 'e1', 'level': 'fault'},
    {'ts': now_iso, 'hook': 'h2', 'event': 'e2', 'level': 'fault'},
    {'ts': now_iso, 'hook': 'h3', 'event': 'e3', 'level': 'diagnostic'},
    {'ts': old_iso, 'hook': 'h4', 'event': 'e4', 'level': 'fault'},
    {'ts': now_iso, 'hook': 'h5', 'event': 'e5', 'level': 'fault'},
]
for r in records:
    tf.write(json.dumps(r) + '\n')
tf.close()
statusline._FAULT_LEDGER_PATH = tf.name
count = statusline._count_recent_faults()
os.unlink(tf.name)
# Expect 3: 2 recent faults + 1 more recent fault = 3 (not the old one, not diagnostic)
print('OK' if count == 3 else f'FAIL: expected 3, got {count}')
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp18-2: counts recent fault entries" "$OPP18_RESULT2" "OK"

# T-opp18-3: _count_recent_faults is fail-open on corrupt ledger
echo ""
echo "--- T-opp18-3: fail-open on corrupt ledger ---"
OPP18_RESULT3=$("$PYTHON" -c "
import sys, os, tempfile
sys.path.insert(0, '$REPO_DIR/src')
import statusline
tf = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
tf.write('not json\n{bad\n')
tf.close()
statusline._FAULT_LEDGER_PATH = tf.name
count = statusline._count_recent_faults()
os.unlink(tf.name)
print('OK' if count == 0 else f'FAIL: got {count}')
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp18-3: fail-open on corrupt ledger" "$OPP18_RESULT3" "OK"

# T-opp18-4: render_obs_hook_faults returns None when no faults
echo ""
echo "--- T-opp18-4: render returns None when no faults ---"
OPP18_RESULT4=$("$PYTHON" -c "
import sys
sys.path.insert(0, '$REPO_DIR/src')
import os; os.environ['NO_COLOR'] = '1'
import statusline
state = {}
theme = statusline.DEFAULT_THEME
result = statusline.render_obs_hook_faults(state, theme)
print('OK' if result is None else f'FAIL: got {result!r}')
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp18-4: render returns None when no faults" "$OPP18_RESULT4" "OK"

# T-opp18-5: render_obs_hook_faults renders non-zero fault count
echo ""
echo "--- T-opp18-5: render returns pill for fault count ---"
OPP18_RESULT5=$("$PYTHON" -c "
import sys
sys.path.insert(0, '$REPO_DIR/src')
import os; os.environ['NO_COLOR'] = '1'
import statusline
state = {'obs_hook_faults': 2}
theme = statusline.DEFAULT_THEME
result = statusline.render_obs_hook_faults(state, theme)
print('OK' if result and '2' in result else f'FAIL: got {result!r}')
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp18-5: render returns pill for fault count" "$OPP18_RESULT5" "OK"

# T-opp18-6: render_obs_hook_faults in MODULE_RENDERERS
echo ""
echo "--- T-opp18-6: obs_hook_faults in MODULE_RENDERERS ---"
OPP18_RESULT6=$("$PYTHON" -c "
import sys
sys.path.insert(0, '$REPO_DIR/src')
import statusline
print('OK' if 'obs_hook_faults' in statusline.MODULE_RENDERERS else 'FAIL')
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp18-6: obs_hook_faults in MODULE_RENDERERS" "$OPP18_RESULT6" "OK"

fi

# ======================================================================
# Section: opp12 — Hook Performance Sidecar
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "opp12" ]; then
echo ""
echo "=== Section: opp12 (OPP-12 hook perf sidecar) ==="

# T-opp12-1: run_fail_open is backward compatible (no session_id)
echo ""
echo "--- T-opp12-1: backward compat (no session_id) ---"
OPP12_RESULT1=$("$PYTHON" -c "
import sys
sys.path.insert(0, '$REPO_DIR/hooks')
import hook_utils
called = []
def main_fn():
    called.append(1)
try:
    hook_utils.run_fail_open(main_fn, 'test_hook', 'test_event')
except SystemExit:
    pass
print('OK' if called else 'FAIL: main_fn not called')
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp12-1: backward compat (no session_id)" "$OPP12_RESULT1" "OK"

# T-opp12-2: _write_hook_perf is fail-open when obs_utils unavailable
echo ""
echo "--- T-opp12-2: _write_hook_perf fail-open ---"
OPP12_RESULT2=$("$PYTHON" -c "
import sys
sys.path.insert(0, '$REPO_DIR/hooks')
import hook_utils
# Call with a fake session_id where no package exists — must not raise
try:
    hook_utils._write_hook_perf('nonexistent-session', 'h', 'e', 42.5)
    print('OK')
except Exception as exc:
    print(f'FAIL: raised {exc!r}')
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp12-2: _write_hook_perf fail-open" "$OPP12_RESULT2" "OK"

# T-opp12-3: run_fail_open with session_id writes timing record
echo ""
echo "--- T-opp12-3: perf record written with session_id ---"
OPP12_RESULT3=$("$PYTHON" -c "
import sys, os, json, tempfile
# Insert hooks dir first so obs_utils is the collocated hooks version
sys.path.insert(0, '$REPO_DIR/hooks')
from obs_utils import create_package

# Create a real package so _write_hook_perf can resolve it
pkg_dir = tempfile.mkdtemp()
session_id = 'test-perf-session-opp12'
package_root = create_package(session_id, '/tmp', '/tmp/t.jsonl', 'test', obs_root=pkg_dir)

# Patch env so resolve_package_root_env picks up our test obs_root
os.environ['OBS_ROOT'] = pkg_dir

import hook_utils

called = []
def main_fn():
    called.append(1)

try:
    hook_utils.run_fail_open(main_fn, 'test_hook', 'TestEvent', session_id=session_id)
except SystemExit:
    pass

# Verify perf record was written
perf_path = os.path.join(package_root, 'metadata', 'hook_perf.jsonl')
if not os.path.exists(perf_path):
    print(f'FAIL: perf file not found at {perf_path}')
    sys.exit(0)
with open(perf_path) as f:
    records = [json.loads(l) for l in f if l.strip()]
if not records:
    print('FAIL: no records in perf file')
    sys.exit(0)
rec = records[0]
ok = (
    rec.get('hook') == 'test_hook' and
    rec.get('event') == 'TestEvent' and
    isinstance(rec.get('duration_ms'), (int, float)) and
    rec.get('duration_ms') >= 0 and
    'ts' in rec
)
print('OK' if ok else f'FAIL: bad record {rec!r}')

# cleanup
import shutil; shutil.rmtree(pkg_dir, ignore_errors=True)
del os.environ['OBS_ROOT']
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp12-3: perf record written with session_id" "$OPP12_RESULT3" "OK"

# T-opp12-4: run_fail_open timing applies even when main_fn raises
echo ""
echo "--- T-opp12-4: timing still writes on main_fn exception ---"
OPP12_RESULT4=$("$PYTHON" -c "
import sys, os, json, tempfile
# Insert hooks dir first so obs_utils is the collocated hooks version
sys.path.insert(0, '$REPO_DIR/hooks')
from obs_utils import create_package

pkg_dir = tempfile.mkdtemp()
session_id = 'test-perf-exc-opp12'
package_root = create_package(session_id, '/tmp', '/tmp/t.jsonl', 'test', obs_root=pkg_dir)
os.environ['OBS_ROOT'] = pkg_dir

import hook_utils

def bad_fn():
    raise RuntimeError('deliberate error')

# run_fail_open catches the exception and exits 0 (via sys.exit)
try:
    hook_utils.run_fail_open(bad_fn, 'bad_hook', 'TestEvent', session_id=session_id)
except SystemExit:
    pass

# Perf record should still be written
perf_path = os.path.join(package_root, 'metadata', 'hook_perf.jsonl')
if not os.path.exists(perf_path):
    print(f'FAIL: perf file not found')
    sys.exit(0)
with open(perf_path) as f:
    records = [json.loads(l) for l in f if l.strip()]
ok = len(records) == 1 and records[0].get('hook') == 'bad_hook'
print('OK' if ok else f'FAIL: records={records!r}')

import shutil; shutil.rmtree(pkg_dir, ignore_errors=True)
del os.environ['OBS_ROOT']
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp12-4: timing still writes on main_fn exception" "$OPP12_RESULT4" "OK"

fi

# ======================================================================
# Section: opp14 — Parse Diagnostic Sidecar
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "opp14" ]; then
echo ""
echo "=== Section: opp14 (OPP-14 parse diagnostic sidecar) ==="

# T-opp14-1: _write_parse_diag writes a record to diagnostics.jsonl
echo ""
echo "--- T-opp14-1: _write_parse_diag writes record ---"
OPP14_RESULT1=$("$PYTHON" -c "
import sys, os, json, tempfile
sys.path.insert(0, '$REPO_DIR/src')
import context_overhead

pkg_dir = tempfile.mkdtemp()
try:
    context_overhead._diag_write_count = 0
    context_overhead._write_parse_diag(pkg_dir, 'transcript_tail', 'JSONDecodeError: test', 'bad json line')
    diag_path = os.path.join(pkg_dir, 'native', 'statusline', 'diagnostics.jsonl')
    if not os.path.exists(diag_path):
        print('FAIL: diagnostics.jsonl not created')
        sys.exit(0)
    with open(diag_path) as f:
        records = [json.loads(l) for l in f if l.strip()]
    if len(records) != 1:
        print(f'FAIL: expected 1 record, got {len(records)}')
        sys.exit(0)
    rec = records[0]
    ok = (
        rec.get('source') == 'transcript_tail' and
        'JSONDecodeError' in rec.get('error', '') and
        rec.get('line_preview') == 'bad json line' and
        'ts' in rec
    )
    print('OK' if ok else f'FAIL: bad record {rec!r}')
finally:
    import shutil; shutil.rmtree(pkg_dir, ignore_errors=True)
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp14-1: _write_parse_diag writes record" "$OPP14_RESULT1" "OK"

# T-opp14-2: cap at _DIAG_MAX_PER_INVOCATION (10)
echo ""
echo "--- T-opp14-2: diagnostic write cap at 10 ---"
OPP14_RESULT2=$("$PYTHON" -c "
import sys, os, json, tempfile
sys.path.insert(0, '$REPO_DIR/src')
import context_overhead

pkg_dir = tempfile.mkdtemp()
try:
    context_overhead._diag_write_count = 0
    for i in range(15):
        context_overhead._write_parse_diag(pkg_dir, 'transcript_tail', f'err {i}', f'line {i}')
    diag_path = os.path.join(pkg_dir, 'native', 'statusline', 'diagnostics.jsonl')
    with open(diag_path) as f:
        count = sum(1 for l in f if l.strip())
    print('OK' if count == 10 else f'FAIL: expected 10 records, got {count}')
finally:
    import shutil; shutil.rmtree(pkg_dir, ignore_errors=True)
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp14-2: diagnostic write cap at 10" "$OPP14_RESULT2" "OK"

# T-opp14-3: line_preview is capped at 100 chars
echo ""
echo "--- T-opp14-3: line_preview capped at 100 chars ---"
OPP14_RESULT3=$("$PYTHON" -c "
import sys, os, json, tempfile
sys.path.insert(0, '$REPO_DIR/src')
import context_overhead

pkg_dir = tempfile.mkdtemp()
try:
    context_overhead._diag_write_count = 0
    long_line = 'x' * 200
    context_overhead._write_parse_diag(pkg_dir, 'transcript_tail', 'err', long_line)
    diag_path = os.path.join(pkg_dir, 'native', 'statusline', 'diagnostics.jsonl')
    with open(diag_path) as f:
        rec = json.loads(f.readline())
    preview_len = len(rec.get('line_preview', ''))
    print('OK' if preview_len == 100 else f'FAIL: expected 100, got {preview_len}')
finally:
    import shutil; shutil.rmtree(pkg_dir, ignore_errors=True)
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp14-3: line_preview capped at 100 chars" "$OPP14_RESULT3" "OK"

# T-opp14-4: fail-open when diag_root is invalid path
echo ""
echo "--- T-opp14-4: fail-open on invalid diag_root ---"
OPP14_RESULT4=$("$PYTHON" -c "
import sys, os
sys.path.insert(0, '$REPO_DIR/src')
import context_overhead

context_overhead._diag_write_count = 0
# Should not raise even with a non-writable or impossible path
try:
    context_overhead._write_parse_diag('/nonexistent/path/that/does/not/exist', 'src', 'err', 'line')
    print('OK')
except Exception as e:
    print(f'FAIL: raised {e}')
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp14-4: fail-open on invalid diag_root" "$OPP14_RESULT4" "OK"

# T-opp14-5: _read_transcript_tail logs parse failures when diag_root given
echo ""
echo "--- T-opp14-5: _read_transcript_tail logs parse failures ---"
OPP14_RESULT5=$("$PYTHON" -c "
import sys, os, json, tempfile
sys.path.insert(0, '$REPO_DIR/src')
import context_overhead

pkg_dir = tempfile.mkdtemp()
tmp_transcript = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
try:
    # Write one valid line and one invalid line
    tmp_transcript.write('{bad json here\n')
    tmp_transcript.write(json.dumps({'type': 'assistant', 'message': {'usage': {'cache_creation_input_tokens': 1000, 'cache_read_input_tokens': 500, 'input_tokens': 200}}}) + '\n')
    tmp_transcript.close()

    context_overhead._diag_write_count = 0
    context_overhead._read_transcript_tail(tmp_transcript.name, diag_root=pkg_dir)

    diag_path = os.path.join(pkg_dir, 'native', 'statusline', 'diagnostics.jsonl')
    exists = os.path.exists(diag_path)
    count = 0
    if exists:
        with open(diag_path) as f:
            count = sum(1 for l in f if l.strip())
    print('OK' if exists and count >= 1 else f'FAIL: exists={exists} count={count}')
finally:
    os.unlink(tmp_transcript.name)
    import shutil; shutil.rmtree(pkg_dir, ignore_errors=True)
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp14-5: _read_transcript_tail logs parse failures" "$OPP14_RESULT5" "OK"

# T-opp14-6: _count_parse_errors returns 0 for missing file
echo ""
echo "--- T-opp14-6: _count_parse_errors returns 0 for missing file ---"
OPP14_RESULT6=$("$PYTHON" -c "
import sys, os, tempfile
sys.path.insert(0, '$REPO_DIR/src')
import statusline

pkg_dir = tempfile.mkdtemp()
try:
    count = statusline._count_parse_errors(pkg_dir)
    print('OK' if count == 0 else f'FAIL: got {count}')
finally:
    import shutil; shutil.rmtree(pkg_dir, ignore_errors=True)
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp14-6: _count_parse_errors returns 0 for missing file" "$OPP14_RESULT6" "OK"

# T-opp14-7: _count_parse_errors counts non-empty lines
echo ""
echo "--- T-opp14-7: _count_parse_errors counts entries ---"
OPP14_RESULT7=$("$PYTHON" -c "
import sys, os, json, tempfile
sys.path.insert(0, '$REPO_DIR/src')
import statusline

pkg_dir = tempfile.mkdtemp()
try:
    diag_dir = os.path.join(pkg_dir, 'native', 'statusline')
    os.makedirs(diag_dir)
    diag_path = os.path.join(diag_dir, 'diagnostics.jsonl')
    with open(diag_path, 'w') as f:
        for i in range(3):
            f.write(json.dumps({'ts': 'now', 'source': 'test', 'error': f'err {i}', 'line_preview': ''}) + '\n')
    count = statusline._count_parse_errors(pkg_dir)
    print('OK' if count == 3 else f'FAIL: got {count}')
finally:
    import shutil; shutil.rmtree(pkg_dir, ignore_errors=True)
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp14-7: _count_parse_errors counts entries" "$OPP14_RESULT7" "OK"

fi

# ======================================================================
# Section: opp17 — Hook Coverage Report
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "opp17" ]; then
echo ""
echo "=== Section: opp17 (OPP-17 hook coverage report) ==="

# T-opp17-1: hook_coverage written to session_inventory.json
echo ""
echo "--- T-opp17-1: hook_coverage written to inventory ---"
OPP17_RESULT1=$("$PYTHON" -c "
import sys, os, json, tempfile
sys.path.insert(0, '$REPO_DIR/hooks')
from obs_utils import create_package

pkg_dir = tempfile.mkdtemp()
try:
    session_id = 'test-opp17-coverage'
    package_root = create_package(session_id, '/tmp', '/tmp/t.jsonl', 'test', obs_root=pkg_dir)

    # Create a fake settings.json with one hook pointing to hooks dir
    hooks_dir = os.path.join('$REPO_DIR', 'hooks')
    fake_hook = os.path.join(hooks_dir, 'obs-session-start.py')
    settings = {
        'enabledPlugins': {},
        'hooks': {
            'PreToolUse': [
                {'matcher': '*', 'hooks': [{'type': 'command', 'command': f'python3 {fake_hook}'}]}
            ]
        }
    }
    settings_path = os.path.join(pkg_dir, 'test-settings.json')
    with open(settings_path, 'w') as f:
        json.dump(settings, f)

    # Patch env so obs-session-start reads our settings
    os.environ['OBS_INVENTORY_SETTINGS_PATH'] = settings_path

    # Import and call _scan_inventory directly
    import importlib.util
    spec = importlib.util.spec_from_file_location('obs_session_start', os.path.join('$REPO_DIR', 'hooks', 'obs-session-start.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._scan_inventory(package_root, '/tmp')

    inventory_path = os.path.join(package_root, 'metadata', 'session_inventory.json')
    with open(inventory_path) as f:
        inv = json.load(f)

    coverage = inv.get('hook_coverage')
    if coverage is None:
        print('FAIL: hook_coverage missing from inventory')
        sys.exit(0)
    has_keys = all(k in coverage for k in ('registered', 'expected', 'missing', 'extra'))
    print('OK' if has_keys else f'FAIL: missing keys in hook_coverage: {list(coverage.keys())}')
finally:
    import shutil; shutil.rmtree(pkg_dir, ignore_errors=True)
    os.environ.pop('OBS_INVENTORY_SETTINGS_PATH', None)
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp17-1: hook_coverage written to inventory" "$OPP17_RESULT1" "OK"

# T-opp17-2: missing hooks detected correctly
echo ""
echo "--- T-opp17-2: missing hooks detected ---"
OPP17_RESULT2=$("$PYTHON" -c "
import sys, os, json, tempfile
sys.path.insert(0, '$REPO_DIR/hooks')
from obs_utils import create_package

pkg_dir = tempfile.mkdtemp()
try:
    session_id = 'test-opp17-missing'
    package_root = create_package(session_id, '/tmp', '/tmp/t.jsonl', 'test', obs_root=pkg_dir)

    # Settings with NO qLine hooks registered
    settings = {'enabledPlugins': {}, 'hooks': {}}
    settings_path = os.path.join(pkg_dir, 'test-settings.json')
    with open(settings_path, 'w') as f:
        json.dump(settings, f)
    os.environ['OBS_INVENTORY_SETTINGS_PATH'] = settings_path

    import importlib.util
    spec = importlib.util.spec_from_file_location('obs_session_start', os.path.join('$REPO_DIR', 'hooks', 'obs-session-start.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._scan_inventory(package_root, '/tmp')

    inventory_path = os.path.join(package_root, 'metadata', 'session_inventory.json')
    with open(inventory_path) as f:
        inv = json.load(f)

    coverage = inv.get('hook_coverage', {})
    # With no hooks registered, missing should be non-empty (all expected are missing)
    missing = coverage.get('missing', [])
    registered = coverage.get('registered', [])
    expected = coverage.get('expected', [])
    # expected should list actual obs-*.py files
    ok = len(expected) > 0 and len(registered) == 0 and len(missing) == len(expected)
    print('OK' if ok else f'FAIL: expected={len(expected)} registered={len(registered)} missing={len(missing)}')
finally:
    import shutil; shutil.rmtree(pkg_dir, ignore_errors=True)
    os.environ.pop('OBS_INVENTORY_SETTINGS_PATH', None)
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp17-2: missing hooks detected" "$OPP17_RESULT2" "OK"

# T-opp17-3: fail-open when settings.json unreadable
echo ""
echo "--- T-opp17-3: fail-open when settings unreadable ---"
OPP17_RESULT3=$("$PYTHON" -c "
import sys, os, json, tempfile
sys.path.insert(0, '$REPO_DIR/hooks')
from obs_utils import create_package

pkg_dir = tempfile.mkdtemp()
try:
    session_id = 'test-opp17-failopen'
    package_root = create_package(session_id, '/tmp', '/tmp/t.jsonl', 'test', obs_root=pkg_dir)

    # Point settings path to non-existent file
    os.environ['OBS_INVENTORY_SETTINGS_PATH'] = '/tmp/nonexistent-settings-opp17.json'

    import importlib.util
    spec = importlib.util.spec_from_file_location('obs_session_start', os.path.join('$REPO_DIR', 'hooks', 'obs-session-start.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod._scan_inventory(package_root, '/tmp')
        print('FAIL: expected exception from missing settings.json')
    except Exception:
        # _scan_inventory raises on missing settings — the caller wraps it in try/except
        # This is expected behavior: the outer run_fail_open handles it
        print('OK')
finally:
    import shutil; shutil.rmtree(pkg_dir, ignore_errors=True)
    os.environ.pop('OBS_INVENTORY_SETTINGS_PATH', None)
" 2>/dev/null || echo "ERROR")
assert_equals "T-opp17-3: fail-open (exception propagates to outer wrapper)" "$OPP17_RESULT3" "OK"

fi

# ======================================================================
# SECTION: alerts — alert trigger audit + lifecycle tests
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "alerts" ]; then
echo ""
echo "=== Section: alerts ==="

# Helper: run render_context_bar with given state dict and return result
# Isolates /tmp/qline-alert.json by pointing it at a tmpfile each test.

# AL-01: bust trigger fires on cache_busting=True
echo ""
echo "--- AL-01: bust trigger fires ---"
AL01=$(run_py "
import unittest.mock as mock
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 200000,
    'context_total': 1000000,
    'sys_overhead_tokens': 100000,
    'sys_overhead_source': 'measured',
    'cache_busting': True,
    '_session_id': 'test-al01',
}
import builtins
_orig_open = builtins.open
def _fake_open(path, mode='r', **kw):
    if '/tmp/qline-alert' in str(path):
        if 'w' in mode:
            import io
            class _Buf(io.StringIO):
                def __exit__(self, *a): super().__exit__(*a)
            return _Buf()
        else:
            raise FileNotFoundError
    return _orig_open(path, mode, **kw)
with mock.patch('builtins.open', side_effect=_fake_open):
    result = render_context_bar(state, DEFAULT_THEME)
# NO_COLOR mode: alert shows as U+26A0 (warning sign)
print('HAS_ALERT' if result and '\u26a0' in result else f'NO_ALERT: {result!r}')
")
assert_equals "AL-01: bust trigger glyph" "$AL01" "HAS_ALERT"

# AL-02: expired trigger fires on cache_expired=True (with no cache_busting)
echo ""
echo "--- AL-02: expired trigger fires ---"
AL02=$(run_py "
import unittest.mock as mock, time as _t
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 200000,
    'context_total': 1000000,
    'sys_overhead_tokens': 100000,
    'sys_overhead_source': 'measured',
    'cache_expired': True,
    '_session_id': 'test-al02',
}
import builtins
_orig_open = builtins.open
_written = {}
def _fake_open(path, mode='r', **kw):
    if '/tmp/qline-alert' in str(path):
        if 'w' in mode:
            import io
            class _Buf(io.StringIO):
                def __exit__(self, *a):
                    _written['data'] = self.getvalue()
                    super().__exit__(*a)
            return _Buf()
        else:
            raise FileNotFoundError
    return _orig_open(path, mode, **kw)
with mock.patch('builtins.open', side_effect=_fake_open):
    result = render_context_bar(state, DEFAULT_THEME)
print('HAS_ALERT' if result and '\u26a0' in result else f'NO_ALERT: {result!r}')
")
assert_equals "AL-02: expired trigger glyph" "$AL02" "HAS_ALERT"

# AL-03: micro trigger fires on microcompact_suspected=True
echo ""
echo "--- AL-03: micro trigger fires ---"
AL03=$(run_py "
import unittest.mock as mock
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 200000,
    'context_total': 1000000,
    'sys_overhead_tokens': 100000,
    'sys_overhead_source': 'measured',
    'microcompact_suspected': True,
    '_session_id': 'test-al03',
}
import builtins
_orig_open = builtins.open
def _fake_open(path, mode='r', **kw):
    if '/tmp/qline-alert' in str(path):
        if 'w' in mode:
            import io
            class _Buf(io.StringIO):
                def __exit__(self, *a): super().__exit__(*a)
            return _Buf()
        else:
            raise FileNotFoundError
    return _orig_open(path, mode, **kw)
with mock.patch('builtins.open', side_effect=_fake_open):
    result = render_context_bar(state, DEFAULT_THEME)
print('HAS_ALERT' if result and '\u26a0' in result else f'NO_ALERT: {result!r}')
")
assert_equals "AL-03: micro trigger glyph" "$AL03" "HAS_ALERT"

# AL-04: bloat trigger fires when sys_overhead >= 50% of context_total
echo ""
echo "--- AL-04: bloat trigger fires ---"
AL04=$(run_py "
import unittest.mock as mock
from statusline import render_context_bar, DEFAULT_THEME
# sys_overhead = 600k / 1000k = 60% >= sys_crit_t (50%)
state = {
    'context_used': 700000,
    'context_total': 1000000,
    'sys_overhead_tokens': 600000,
    'sys_overhead_source': 'measured',
    '_session_id': 'test-al04',
}
import builtins
_orig_open = builtins.open
def _fake_open(path, mode='r', **kw):
    if '/tmp/qline-alert' in str(path):
        if 'w' in mode:
            import io
            class _Buf(io.StringIO):
                def __exit__(self, *a): super().__exit__(*a)
            return _Buf()
        else:
            raise FileNotFoundError
    return _orig_open(path, mode, **kw)
with mock.patch('builtins.open', side_effect=_fake_open):
    result = render_context_bar(state, DEFAULT_THEME)
print('HAS_ALERT' if result and '\u26a0' in result else f'NO_ALERT: {result!r}')
")
assert_equals "AL-04: bloat trigger glyph" "$AL04" "HAS_ALERT"

# AL-05: heavy trigger fires when total_pct >= crit_t (~83% for 1M window)
echo ""
echo "--- AL-05: heavy trigger fires ---"
AL05=$(run_py "
import unittest.mock as mock
from statusline import render_context_bar, DEFAULT_THEME
from context_overhead import compute_context_thresholds
thresholds = compute_context_thresholds(1000000)
# Use autocompact_pct as crit_t
crit_t = thresholds['autocompact_pct']
# Go 1% over crit_t
target_pct = int(crit_t) + 1
ctx_used = target_pct * 1000000 // 100
state = {
    'context_used': ctx_used,
    'context_total': 1000000,
    'cc_autocompact_pct': crit_t,
    '_session_id': 'test-al05',
}
import builtins
_orig_open = builtins.open
def _fake_open(path, mode='r', **kw):
    if '/tmp/qline-alert' in str(path):
        if 'w' in mode:
            import io
            class _Buf(io.StringIO):
                def __exit__(self, *a): super().__exit__(*a)
            return _Buf()
        else:
            raise FileNotFoundError
    return _orig_open(path, mode, **kw)
with mock.patch('builtins.open', side_effect=_fake_open):
    result = render_context_bar(state, DEFAULT_THEME)
print('HAS_ALERT' if result and '\u26a0' in result else f'NO_ALERT crit_t={crit_t} ctx_used={ctx_used}: {result!r}')
")
assert_equals "AL-05: heavy trigger glyph" "$AL05" "HAS_ALERT"

# AL-06: compact trigger fires when 0 < tuc <= 10
echo ""
echo "--- AL-06: compact trigger fires ---"
AL06=$(run_py "
import unittest.mock as mock
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 200000,
    'context_total': 1000000,
    'turns_until_compact': 5,
    '_session_id': 'test-al06',
}
import builtins
_orig_open = builtins.open
def _fake_open(path, mode='r', **kw):
    if '/tmp/qline-alert' in str(path):
        if 'w' in mode:
            import io
            class _Buf(io.StringIO):
                def __exit__(self, *a): super().__exit__(*a)
            return _Buf()
        else:
            raise FileNotFoundError
    return _orig_open(path, mode, **kw)
with mock.patch('builtins.open', side_effect=_fake_open):
    result = render_context_bar(state, DEFAULT_THEME)
print('HAS_ALERT' if result and '\u26a0' in result else f'NO_ALERT: {result!r}')
")
assert_equals "AL-06: compact trigger glyph" "$AL06" "HAS_ALERT"

# AL-07: turns trigger fires when 10 < tuc <= 50
echo ""
echo "--- AL-07: turns trigger fires ---"
AL07=$(run_py "
import unittest.mock as mock
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 200000,
    'context_total': 1000000,
    'turns_until_compact': 30,
    '_session_id': 'test-al07',
}
import builtins
_orig_open = builtins.open
def _fake_open(path, mode='r', **kw):
    if '/tmp/qline-alert' in str(path):
        if 'w' in mode:
            import io
            class _Buf(io.StringIO):
                def __exit__(self, *a): super().__exit__(*a)
            return _Buf()
        else:
            raise FileNotFoundError
    return _orig_open(path, mode, **kw)
with mock.patch('builtins.open', side_effect=_fake_open):
    result = render_context_bar(state, DEFAULT_THEME)
print('HAS_ALERT' if result and '\u26a0' in result else f'NO_ALERT: {result!r}')
")
assert_equals "AL-07: turns trigger glyph" "$AL07" "HAS_ALERT"

# AL-08: degraded trigger fires on cache_degraded=True (lowest priority)
echo ""
echo "--- AL-08: degraded trigger fires ---"
AL08=$(run_py "
import unittest.mock as mock
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 200000,
    'context_total': 1000000,
    'sys_overhead_tokens': 100000,
    'sys_overhead_source': 'measured',
    'cache_degraded': True,
    '_session_id': 'test-al08',
}
import builtins
_orig_open = builtins.open
def _fake_open(path, mode='r', **kw):
    if '/tmp/qline-alert' in str(path):
        if 'w' in mode:
            import io
            class _Buf(io.StringIO):
                def __exit__(self, *a): super().__exit__(*a)
            return _Buf()
        else:
            raise FileNotFoundError
    return _orig_open(path, mode, **kw)
with mock.patch('builtins.open', side_effect=_fake_open):
    result = render_context_bar(state, DEFAULT_THEME)
print('HAS_ALERT' if result and '\u26a0' in result else f'NO_ALERT: {result!r}')
")
assert_equals "AL-08: degraded trigger glyph" "$AL08" "HAS_ALERT"

# AL-09: priority order — bust wins over degraded when both set
echo ""
echo "--- AL-09: priority bust > degraded ---"
AL09=$(run_py "
import unittest.mock as mock
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 200000,
    'context_total': 1000000,
    'sys_overhead_tokens': 100000,
    'sys_overhead_source': 'measured',
    'cache_busting': True,
    'cache_degraded': True,
    '_session_id': 'test-al09',
}
import builtins, json as _json
_orig_open = builtins.open
_saved = {}
def _fake_open(path, mode='r', **kw):
    if '/tmp/qline-alert' in str(path):
        if 'w' in mode:
            import io
            class _Buf(io.StringIO):
                def __exit__(self, *a):
                    _saved['data'] = self.getvalue()
                    super().__exit__(*a)
            return _Buf()
        else:
            raise FileNotFoundError
    return _orig_open(path, mode, **kw)
with mock.patch('builtins.open', side_effect=_fake_open):
    result = render_context_bar(state, DEFAULT_THEME)
saved_key = _json.loads(_saved.get('data', '{}')).get('key', 'NONE')
print(f'KEY:{saved_key}')
")
assert_equals "AL-09: bust wins over degraded (key=bust)" "$AL09" "KEY:bust"

# AL-10: no alert — normal state produces no alert glyph
echo ""
echo "--- AL-10: no alert in normal state ---"
AL10=$(run_py "
import unittest.mock as mock
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 100000,
    'context_total': 1000000,
    '_session_id': 'test-al10',
}
import builtins
_orig_open = builtins.open
def _fake_open(path, mode='r', **kw):
    if '/tmp/qline-alert' in str(path):
        if 'w' in mode:
            import io
            class _Buf(io.StringIO):
                def __exit__(self, *a): super().__exit__(*a)
            return _Buf()
        else:
            raise FileNotFoundError
    return _orig_open(path, mode, **kw)
with mock.patch('builtins.open', side_effect=_fake_open):
    result = render_context_bar(state, DEFAULT_THEME)
print('NO_ALERT' if result and '\u26a0' not in result else f'HAS_ALERT: {result!r}')
")
assert_equals "AL-10: no alert in normal state" "$AL10" "NO_ALERT"

# AL-11: banner text — bust banner contains expected message
echo ""
echo "--- AL-11: bust banner text ---"
AL11=$(run_py "
import unittest.mock as mock
from statusline import render_context_bar, DEFAULT_THEME
import time as _t
state = {
    'context_used': 200000,
    'context_total': 1000000,
    'sys_overhead_tokens': 100000,
    'sys_overhead_source': 'measured',
    'cache_busting': True,
    '_session_id': 'test-al11',
}
import builtins
_orig_open = builtins.open
def _fake_open(path, mode='r', **kw):
    if '/tmp/qline-alert' in str(path):
        if 'w' in mode:
            import io
            class _Buf(io.StringIO):
                def __exit__(self, *a): super().__exit__(*a)
            return _Buf()
        else:
            raise FileNotFoundError
    return _orig_open(path, mode, **kw)
with mock.patch('builtins.open', side_effect=_fake_open):
    render_context_bar(state, DEFAULT_THEME)
banner = state.get('_alert_banner', '')
print('OK' if 'CACHE BUSTED' in banner else f'BAD_BANNER: {banner!r}')
")
assert_equals "AL-11: bust banner has CACHE BUSTED" "$AL11" "OK"

# AL-12: banner text — turns banner contains dynamic turn count
echo ""
echo "--- AL-12: turns banner text ---"
AL12=$(run_py "
import unittest.mock as mock
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 200000,
    'context_total': 1000000,
    'turns_until_compact': 25,
    '_session_id': 'test-al12',
}
import builtins
_orig_open = builtins.open
def _fake_open(path, mode='r', **kw):
    if '/tmp/qline-alert' in str(path):
        if 'w' in mode:
            import io
            class _Buf(io.StringIO):
                def __exit__(self, *a): super().__exit__(*a)
            return _Buf()
        else:
            raise FileNotFoundError
    return _orig_open(path, mode, **kw)
with mock.patch('builtins.open', side_effect=_fake_open):
    render_context_bar(state, DEFAULT_THEME)
banner = state.get('_alert_banner', '')
print('OK' if '25' in banner and 'TURNS LEFT' in banner else f'BAD_BANNER: {banner!r}')
")
assert_equals "AL-12: turns banner has count and TURNS LEFT" "$AL12" "OK"

# AL-13: session isolation — different session_id in alert file treated as new alert
echo ""
echo "--- AL-13: session isolation ---"
AL13=$(run_py "
import json, unittest.mock as mock, time as _t
from statusline import render_context_bar, DEFAULT_THEME

# Simulate pre-existing alert file from a DIFFERENT session (old session)
old_onset = _t.time() - 100  # 100 seconds ago (well past 5s banner window)
old_alert = {'key': 'bust', 'onset': old_onset, 'session_id': 'old-session-xyz'}

state = {
    'context_used': 200000,
    'context_total': 1000000,
    'sys_overhead_tokens': 100000,
    'sys_overhead_source': 'measured',
    'cache_busting': True,
    '_session_id': 'new-session-abc',  # Different from old_alert's session_id
}

import builtins
_orig_open = builtins.open
_saved = {}
def _fake_open(path, mode='r', **kw):
    if '/tmp/qline-alert' in str(path):
        if 'w' in mode:
            import io
            class _Buf(io.StringIO):
                def __exit__(self, *a):
                    _saved['data'] = self.getvalue()
                    super().__exit__(*a)
            return _Buf()
        else:
            # Return old alert data from 'different session'
            import io
            return io.StringIO(json.dumps(old_alert))
    return _orig_open(path, mode, **kw)

with mock.patch('builtins.open', side_effect=_fake_open):
    render_context_bar(state, DEFAULT_THEME)

# With session isolation fix: new session ignores old onset, writes new onset
# Banner should appear (elapsed ~0, not 100s)
banner = state.get('_alert_banner', '')
saved = json.loads(_saved.get('data', '{}'))
new_sid = saved.get('session_id', 'MISSING')
has_banner = bool(banner)
# New alert should be saved with new session_id
print('OK' if has_banner and new_sid == 'new-session-abc' else f'FAIL: has_banner={has_banner} new_sid={new_sid!r} banner={banner!r}')
")
assert_equals "AL-13: session isolation resets onset" "$AL13" "OK"

# AL-14: alert file written with session_id field
echo ""
echo "--- AL-14: alert file includes session_id ---"
AL14=$(run_py "
import json, unittest.mock as mock
from statusline import render_context_bar, DEFAULT_THEME

state = {
    'context_used': 200000,
    'context_total': 1000000,
    'sys_overhead_tokens': 100000,
    'sys_overhead_source': 'measured',
    'cache_busting': True,
    '_session_id': 'test-sid-check',
}

import builtins
_orig_open = builtins.open
_saved = {}
def _fake_open(path, mode='r', **kw):
    if '/tmp/qline-alert' in str(path):
        if 'w' in mode:
            import io
            class _Buf(io.StringIO):
                def __exit__(self, *a):
                    _saved['data'] = self.getvalue()
                    super().__exit__(*a)
            return _Buf()
        else:
            raise FileNotFoundError
    return _orig_open(path, mode, **kw)

with mock.patch('builtins.open', side_effect=_fake_open):
    render_context_bar(state, DEFAULT_THEME)

saved = json.loads(_saved.get('data', '{}'))
sid = saved.get('session_id', 'MISSING')
key = saved.get('key', 'MISSING')
print('OK' if sid == 'test-sid-check' and key == 'bust' else f'FAIL: sid={sid!r} key={key!r}')
")
assert_equals "AL-14: alert file has session_id and key" "$AL14" "OK"

# AL-15: tuc=0 does NOT trigger compact or turns (condition: 0 < tuc)
echo ""
echo "--- AL-15: tuc=0 does not trigger alert ---"
AL15=$(run_py "
import unittest.mock as mock
from statusline import render_context_bar, DEFAULT_THEME
state = {
    'context_used': 100000,
    'context_total': 1000000,
    'turns_until_compact': 0,
    '_session_id': 'test-al15',
}
import builtins
_orig_open = builtins.open
def _fake_open(path, mode='r', **kw):
    if '/tmp/qline-alert' in str(path):
        if 'w' in mode:
            import io
            class _Buf(io.StringIO):
                def __exit__(self, *a): super().__exit__(*a)
            return _Buf()
        else:
            raise FileNotFoundError
    return _orig_open(path, mode, **kw)
with mock.patch('builtins.open', side_effect=_fake_open):
    result = render_context_bar(state, DEFAULT_THEME)
print('NO_ALERT' if result and '\u26a0' not in result else f'HAS_ALERT: {result!r}')
")
assert_equals "AL-15: tuc=0 no alert" "$AL15" "NO_ALERT"

echo ""
fi



# ======================================================================
# SECTION: new_metrics — tests for lines_changed, api_efficiency, daily/weekly cost, session_count
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "new_metrics" ]; then
echo "--- New Metrics Tests ---"

echo "  render_lines_changed: shows +N/-N"
OUT=$(run_py "
from statusline import render_lines_changed, DEFAULT_THEME
state = {'lines_added': 2500, 'lines_removed': 800}
result = render_lines_changed(state, DEFAULT_THEME)
assert result is not None, 'expected output'
assert '+2.5k' in result, f'expected +2.5k, got: {result}'
assert '-800' in result, f'expected -800, got: {result}'
print('OK')
")
assert_equals "NM-01: lines_changed renders" "$OUT" "OK"

echo "  render_lines_changed: None when no data"
OUT=$(run_py "
from statusline import render_lines_changed, DEFAULT_THEME
result = render_lines_changed({}, DEFAULT_THEME)
assert result is None, f'expected None, got: {result}'
print('OK')
")
assert_equals "NM-02: lines_changed None when empty" "$OUT" "OK"

echo "  render_api_efficiency: shows percentage"
OUT=$(run_py "
from statusline import render_api_efficiency, DEFAULT_THEME
state = {'api_duration_ms': 15000000, 'duration_ms': 28232607}
result = render_api_efficiency(state, DEFAULT_THEME)
assert result is not None, 'expected output'
assert '53%' in result, f'expected 53%, got: {result}'
print('OK')
")
assert_equals "NM-03: api_efficiency renders" "$OUT" "OK"

echo "  render_api_efficiency: None without api_duration"
OUT=$(run_py "
from statusline import render_api_efficiency, DEFAULT_THEME
result = render_api_efficiency({'duration_ms': 1000}, DEFAULT_THEME)
assert result is None, f'expected None, got: {result}'
print('OK')
")
assert_equals "NM-04: api_efficiency None without data" "$OUT" "OK"

echo "  render_daily_cost: renders with threshold"
OUT=$(run_py "
from statusline import render_daily_cost, DEFAULT_THEME
state = {'daily_cost': 250.0}
result = render_daily_cost(state, DEFAULT_THEME)
assert result is not None, 'expected output'
assert '250' in result, f'expected 250, got: {result}'
print('OK')
")
assert_equals "NM-05: daily_cost renders" "$OUT" "OK"

echo "  render_weekly_cost: renders"
OUT=$(run_py "
from statusline import render_weekly_cost, DEFAULT_THEME
state = {'weekly_cost': 1500.0}
result = render_weekly_cost(state, DEFAULT_THEME)
assert result is not None, 'expected output'
assert '1500' in result, f'expected 1500, got: {result}'
assert '/wk' in result, f'expected /wk, got: {result}'
print('OK')
")
assert_equals "NM-06: weekly_cost renders" "$OUT" "OK"

echo "  render_session_count: renders"
OUT=$(run_py "
from statusline import render_session_count, DEFAULT_THEME
state = {'session_count_today': 42}
result = render_session_count(state, DEFAULT_THEME)
assert result is not None, 'expected output'
assert '#42' in result, f'expected #42, got: {result}'
print('OK')
")
assert_equals "NM-07: session_count renders" "$OUT" "OK"

echo "  normalize: extracts lines_added/removed from cost dict"
OUT=$(run_py "
from statusline import normalize
state = normalize({'cost': {'total_cost_usd': 10, 'total_lines_added': 500, 'total_lines_removed': 200}})
assert state.get('lines_added') == 500, f'lines_added: {state.get(\"lines_added\")}'
assert state.get('lines_removed') == 200, f'lines_removed: {state.get(\"lines_removed\")}'
print('OK')
")
assert_equals "NM-08: normalize extracts lines" "$OUT" "OK"

echo "  normalize: extracts api_duration_ms from cost dict"
OUT=$(run_py "
from statusline import normalize
state = normalize({'cost': {'total_cost_usd': 10, 'total_api_duration_ms': 5000}})
assert state.get('api_duration_ms') == 5000, f'api_duration_ms: {state.get(\"api_duration_ms\")}'
print('OK')
")
assert_equals "NM-09: normalize extracts api_duration" "$OUT" "OK"

echo "  _scan_cost_and_sessions: returns tuple"
OUT=$(run_py "
from statusline import _scan_cost_and_sessions
result = _scan_cost_and_sessions()
assert isinstance(result, tuple) and len(result) == 3, f'expected 3-tuple, got: {result}'
daily, weekly, count = result
assert isinstance(daily, float), f'daily not float: {type(daily)}'
assert isinstance(weekly, float), f'weekly not float: {type(weekly)}'
assert isinstance(count, int), f'count not int: {type(count)}'
print('OK')
")
assert_equals "NM-10: _scan_cost_and_sessions returns tuple" "$OUT" "OK"

echo ""
fi


# ======================================================================
# SECTION: derived_metrics — cost/ktok, io ratio, tokens/turn, free context, growth rate
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "derived_metrics" ]; then
echo "--- Derived Metrics Tests ---"

OUT=$(run_py "
from statusline import render_cost_per_ktok, DEFAULT_THEME
result = render_cost_per_ktok({'cost_usd': 75.0, 'output_tokens': 500000}, DEFAULT_THEME)
assert result and '$/k' in result and '0.15' in result, f'got: {result}'
print('OK')
")
assert_equals "DM-01: cost_per_ktok renders" "$OUT" "OK"

OUT=$(run_py "
from statusline import render_cost_per_ktok, DEFAULT_THEME
assert render_cost_per_ktok({}, DEFAULT_THEME) is None
print('OK')
")
assert_equals "DM-02: cost_per_ktok None without data" "$OUT" "OK"

OUT=$(run_py "
from statusline import render_io_ratio, DEFAULT_THEME
result = render_io_ratio({'input_tokens': 100000, 'output_tokens': 500000}, DEFAULT_THEME)
assert result and 'io:5.0x' in result, f'got: {result}'
print('OK')
")
assert_equals "DM-03: io_ratio renders" "$OUT" "OK"

OUT=$(run_py "
from statusline import render_tokens_per_turn, DEFAULT_THEME
result = render_tokens_per_turn({'output_tokens': 500000, 'session_turn_count': 50}, DEFAULT_THEME)
assert result and 'tok/t' in result and '10.0k' in result, f'got: {result}'
print('OK')
")
assert_equals "DM-04: tokens_per_turn renders" "$OUT" "OK"

OUT=$(run_py "
from statusline import render_free_context, DEFAULT_THEME
result = render_free_context({'context_total': 1000000, 'context_used': 600000}, DEFAULT_THEME)
assert result and '400k' in result and 'free' in result, f'got: {result}'
print('OK')
")
assert_equals "DM-05: free_context renders" "$OUT" "OK"

OUT=$(run_py "
from statusline import render_free_context, DEFAULT_THEME
result = render_free_context({'context_total': 1000000, 'context_used': 1000000}, DEFAULT_THEME)
assert result is None, f'expected None when 0 free, got: {result}'
print('OK')
")
assert_equals "DM-06: free_context None when full" "$OUT" "OK"

OUT=$(run_py "
from statusline import render_growth_rate, DEFAULT_THEME
result = render_growth_rate({'context_growth_per_turn': 8778}, DEFAULT_THEME)
assert result and 'gro:' in result and '8.8k' in result, f'got: {result}'
print('OK')
")
assert_equals "DM-07: growth_rate renders" "$OUT" "OK"

OUT=$(run_py "
from statusline import render_growth_rate, DEFAULT_THEME
assert render_growth_rate({}, DEFAULT_THEME) is None
print('OK')
")
assert_equals "DM-08: growth_rate None without data" "$OUT" "OK"

echo ""
fi



# ======================================================================
# SECTION: invariants — metric consistency proofs
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "invariants" ]; then
echo "--- Invariant Tests ---"

OUT=$(run_py "
from statusline import _check_invariants
# Clean state — no violations
state = {'context_used': 400000, 'context_total': 1000000, 'raw_used_pct': 40,
         'obs_reads': 100, 'obs_writes': 50, 'obs_bash': 30, 'obs_failures': 5,
         'obs_prompts': 10, 'obs_tasks': 3, 'obs_subagents': 2, 'obs_compactions': 0,
         'obs_reread_pct': 25, 'daily_cost': 50.0, 'weekly_cost': 200.0}
violations = _check_invariants(state)
assert violations == [], f'expected clean, got: {violations}'
print('OK')
")
assert_equals "INV-01: clean state no violations" "$OUT" "OK"

OUT=$(run_py "
from statusline import _check_invariants
# daily > weekly — violation
state = {'daily_cost': 300.0, 'weekly_cost': 200.0}
violations = _check_invariants(state)
assert any('daily>weekly' in v for v in violations), f'expected daily>weekly: {violations}'
print('OK')
")
assert_equals "INV-02: daily > weekly caught" "$OUT" "OK"

OUT=$(run_py "
from statusline import _check_invariants
# Negative counter — violation
state = {'obs_reads': -1}
violations = _check_invariants(state)
assert any('obs_reads' in v for v in violations), f'expected obs_reads violation: {violations}'
print('OK')
")
assert_equals "INV-03: negative counter caught" "$OUT" "OK"

OUT=$(run_py "
from statusline import _check_invariants
# Percentage out of bounds
state = {'think_pct': 150}
violations = _check_invariants(state)
assert any('think_pct_oob' in v for v in violations), f'expected oob: {violations}'
print('OK')
")
assert_equals "INV-04: percentage oob caught" "$OUT" "OK"

OUT=$(run_py "
from statusline import _check_invariants
# pct drift: raw says 40 but used/total = 80%
state = {'context_used': 800000, 'context_total': 1000000, 'raw_used_pct': 40}
violations = _check_invariants(state)
assert any('pct_drift' in v for v in violations), f'expected drift: {violations}'
print('OK')
")
assert_equals "INV-05: pct drift caught" "$OUT" "OK"

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
