#!/bin/bash
# Shell-first test harness for qLine statusline.py
# Follows the assertion style from ~/.claude/tests/test-hook-utils.sh
#
# Usage:
#   bash tests/test-statusline.sh                    # run all sections
#   bash tests/test-statusline.sh --section parser   # run one section
#   bash tests/test-statusline.sh --section normalizer
#   bash tests/test-statusline.sh --section renderer
#   bash tests/test-statusline.sh --section command
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
        echo "  FAIL: $label (expected '$expected', got '$actual')"
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
    local line_count
    if [ -z "$output" ]; then
        # empty output is acceptable (zero lines)
        echo "  PASS: $label (empty output)"
        PASS=$((PASS + 1))
        return
    fi
    line_count=$(printf '%s\n' "$output" | wc -l)
    if [ "$line_count" = "1" ]; then
        echo "  PASS: $label"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $label (expected 1 line, got $line_count)"
        FAIL=$((FAIL + 1))
    fi
}

# Helper: run statusline as a Python module and capture stdout/stderr/exit
run_statusline() {
    local input="$1"
    local tmpout tmpderr
    tmpout=$(mktemp)
    tmpderr=$(mktemp)
    printf '%s' "$input" | python3 "$SRC" >"$tmpout" 2>"$tmpderr"
    local exit_code=$?
    LAST_STDOUT=$(cat "$tmpout")
    LAST_STDERR=$(cat "$tmpderr")
    LAST_EXIT=$exit_code
    rm -f "$tmpout" "$tmpderr"
}

# Helper: run a Python snippet importing from statusline
run_py() {
    python3 -c "
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
os.close(w)  # EOF immediately
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

# P-06: Byte cap enforcement — input over MAX_STDIN_BYTES is truncated
# Use a tempfile to avoid pipe blocking on large writes
OUT=$(run_py "
from statusline import read_stdin_bounded, MAX_STDIN_BYTES
import os, tempfile
# Write oversize data to a tempfile, redirect stdin from it
with tempfile.NamedTemporaryFile(delete=False) as f:
    fname = f.name
    f.write(b'{\"k\":\"' + b'A' * (MAX_STDIN_BYTES + 100) + b'\"}')
fd = os.open(fname, os.O_RDONLY)
os.dup2(fd, 0)
os.close(fd)
result = read_stdin_bounded()
os.unlink(fname)
# Truncated JSON should fail to parse
print('NONE' if result is None else 'NOT_NONE')
")
assert_equals "P-06: oversize input returns None (truncated)" "$OUT" "NONE"

# P-07: Malformed bytes (invalid UTF-8) handled with replacement
OUT=$(run_py "
from statusline import read_stdin_bounded
import os
r, w = os.pipe()
# Invalid UTF-8 byte sequences inside otherwise valid JSON structure
os.write(w, b'{\"k\": \"val\xc0\xc1ue\"}')
os.close(w)
os.dup2(r, 0)
result = read_stdin_bounded()
if result is not None:
    print('DICT_WITH_REPLACEMENT')
else:
    print('NONE')
")
# Either None or dict is acceptable — the key is no crash
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
# SECTION: normalizer — payload normalization tests
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "normalizer" ]; then
echo "--- Normalizer Tests ---"

# N-01: Full payload normalizes all documented fields
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

# N-02: Minimal payload — only model
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

# N-03: Fallback from workspace.current_dir to cwd
OUT=$(run_py "
from statusline import normalize
import json
payload = json.load(open('$FIXTURES/valid-no-workspace.json'))
state = normalize(payload)
print(state.get('dir_basename', 'MISSING'))
")
assert_equals "N-03: cwd fallback for dir" "$OUT" "myapp"

# N-04: context_window normalization
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

# N-05: Optional fields preserved when present
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

# N-06: Wrong-type optionals are silently ignored
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

# N-07: Empty dict payload
OUT=$(run_py "
from statusline import normalize
state = normalize({})
print(len(state))
")
assert_equals "N-07: empty dict yields empty state" "$OUT" "0"

# N-08: Unknown future fields are ignored
OUT=$(run_py "
from statusline import normalize
state = normalize({'unknown_future_field': 42, 'model': {'display_name': 'Test'}})
print('UNKNOWN:' + str(state.get('unknown_future_field', 'ABSENT')))
print('MODEL:' + state.get('model_name', 'MISSING'))
")
assert_contains "N-08a: unknown field ignored" "$OUT" "UNKNOWN:ABSENT"
assert_contains "N-08b: known field extracted" "$OUT" "MODEL:Test"

echo ""
fi

# ======================================================================
# SECTION: renderer — rendering contract and content tests
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "renderer" ]; then
echo "--- Renderer Tests ---"

# R-01: Empty state produces empty output
OUT=$(run_py "
from statusline import render
print(repr(render({})))
")
assert_equals "R-01: empty state -> empty string" "$OUT" "''"

# R-02: Full state — exact module order: model | dir | context | cost | duration
OUT=$(run_py "
from statusline import render
state = {
    'model_name': 'Opus',
    'dir_basename': 'qLine',
    'context_used': 50000,
    'context_total': 100000,
    'cost_usd': 1.23,
    'duration_ms': 45000,
}
print(render(state))
")
assert_equals "R-02: full module order" "$OUT" "Opus | qLine | ctx:50% | \$1.23 | 45s"

# R-03: Missing modules are omitted, not blank
OUT=$(run_py "
from statusline import render
state = {'model_name': 'Opus', 'cost_usd': 0.50}
print(render(state))
")
assert_equals "R-03: missing modules omitted" "$OUT" "Opus | \$0.50"

# R-04: Model-only render
OUT=$(run_py "
from statusline import render
print(render({'model_name': 'Sonnet'}))
")
assert_equals "R-04: model-only" "$OUT" "Sonnet"

# R-05: Context warning threshold (70-84%)
OUT=$(run_py "
from statusline import render
state = {'context_used': 75000, 'context_total': 100000}
print(render(state))
")
assert_equals "R-05: context warning" "$OUT" "ctx:75%~"

# R-06: Context critical threshold (>=85%)
OUT=$(run_py "
from statusline import render
state = {'context_used': 90000, 'context_total': 100000}
print(render(state))
")
assert_equals "R-06: context critical" "$OUT" "ctx:90%!"

# R-07: Context neutral (<70%)
OUT=$(run_py "
from statusline import render
state = {'context_used': 30000, 'context_total': 100000}
print(render(state))
")
assert_equals "R-07: context neutral" "$OUT" "ctx:30%"

# R-08: Newline in model name is sanitized
OUT=$(run_py "
from statusline import render
state = {'model_name': 'Opus\nInjected'}
line = render(state)
print(line)
")
assert_equals "R-08: newline sanitized" "$OUT" "Opus Injected"
assert_single_line "R-08b: single line output" "$OUT"

# R-09: Cost formatting — small amounts
OUT=$(run_py "
from statusline import render
state = {'cost_usd': 0.001}
print(render(state))
")
assert_equals "R-09: small cost precision" "$OUT" "\$0.0010"

# R-10: Cost formatting — normal amounts
OUT=$(run_py "
from statusline import render
state = {'cost_usd': 5.50}
print(render(state))
")
assert_equals "R-10: normal cost" "$OUT" "\$5.50"

# R-11: Duration formatting — seconds
OUT=$(run_py "
from statusline import render
state = {'duration_ms': 30000}
print(render(state))
")
assert_equals "R-11: duration seconds" "$OUT" "30s"

# R-12: Duration formatting — minutes
OUT=$(run_py "
from statusline import render
state = {'duration_ms': 150000}
print(render(state))
")
assert_equals "R-12: duration minutes" "$OUT" "2m30s"

# R-13: Duration formatting — hours
OUT=$(run_py "
from statusline import render
state = {'duration_ms': 7200000}
print(render(state))
")
assert_equals "R-13: duration hours" "$OUT" "2h"

# R-14: Duration formatting — hours and minutes
OUT=$(run_py "
from statusline import render
state = {'duration_ms': 5400000}
print(render(state))
")
assert_equals "R-14: duration hours+min" "$OUT" "1h30m"

# R-15: ASCII-safe separator — no non-ASCII characters in output
OUT=$(run_py "
from statusline import render
state = {'model_name': 'Opus', 'dir_basename': 'test', 'cost_usd': 1.00}
line = render(state)
# Check all chars are ASCII
all_ascii = all(ord(c) < 128 for c in line)
print('ASCII' if all_ascii else 'NON_ASCII')
")
assert_equals "R-15: output is ASCII-safe" "$OUT" "ASCII"

# R-16: Tab in fragment is sanitized
OUT=$(run_py "
from statusline import render
state = {'model_name': 'Opus\tExtra'}
line = render(state)
print(repr(line))
")
assert_contains "R-16: tab sanitized" "$OUT" "Opus Extra"

echo ""
fi

# ======================================================================
# SECTION: command — executable-level integration tests
# ======================================================================
if [ "$RUN_SECTION" = "all" ] || [ "$RUN_SECTION" = "command" ]; then
echo "--- Command Integration Tests ---"

# C-01: Full fixture -> exact output
run_statusline "$(cat "$FIXTURES/valid-full.json")"
assert_exit_zero "C-01a: exit 0 on full fixture" "$LAST_EXIT"
assert_empty "C-01b: no stderr" "$LAST_STDERR"
assert_single_line "C-01c: single line output" "$LAST_STDOUT"
assert_equals "C-01d: full output" "$LAST_STDOUT" "Opus | qLine | \$1.23 | 45s"

# C-02: Minimal fixture -> model only
run_statusline "$(cat "$FIXTURES/valid-minimal.json")"
assert_exit_zero "C-02a: exit 0 on minimal" "$LAST_EXIT"
assert_empty "C-02b: no stderr" "$LAST_STDERR"
assert_equals "C-02c: minimal output" "$LAST_STDOUT" "Opus"

# C-03: Context window fixture -> context module present
run_statusline "$(cat "$FIXTURES/valid-with-context-window.json")"
assert_exit_zero "C-03a: exit 0" "$LAST_EXIT"
assert_empty "C-03b: no stderr" "$LAST_STDERR"
assert_equals "C-03c: context window output" "$LAST_STDOUT" "Opus | qLine | ctx:75%~ | \$0.50 | 2m"

# C-04: Critical context fixture
run_statusline "$(cat "$FIXTURES/valid-context-critical.json")"
assert_exit_zero "C-04a: exit 0" "$LAST_EXIT"
assert_equals "C-04c: critical context" "$LAST_STDOUT" "Opus | qLine | ctx:90%! | \$2.00 | 5m"

# C-05: No workspace, fall back to cwd
run_statusline "$(cat "$FIXTURES/valid-no-workspace.json")"
assert_exit_zero "C-05a: exit 0" "$LAST_EXIT"
assert_equals "C-05c: cwd fallback" "$LAST_STDOUT" "Opus | myapp | \$0.10 | 5s"

# C-06: Wrong-type optionals -> still renders model
run_statusline "$(cat "$FIXTURES/wrong-type-optionals.json")"
assert_exit_zero "C-06a: exit 0" "$LAST_EXIT"
assert_equals "C-06b: renders despite wrong types" "$LAST_STDOUT" "Opus | qLine"

# C-07: Empty JSON object -> no output
run_statusline "{}"
assert_exit_zero "C-07a: exit 0 on empty object" "$LAST_EXIT"
assert_empty "C-07b: no stdout on empty object" "$LAST_STDOUT"
assert_empty "C-07c: no stderr on empty object" "$LAST_STDERR"

# C-08: JSON null -> no output
run_statusline "null"
assert_exit_zero "C-08a: exit 0 on null" "$LAST_EXIT"
assert_empty "C-08b: no stdout on null" "$LAST_STDOUT"
assert_empty "C-08c: no stderr on null" "$LAST_STDERR"

# C-09: JSON number -> no output
run_statusline "42"
assert_exit_zero "C-09a: exit 0 on number" "$LAST_EXIT"
assert_empty "C-09b: no stdout on number" "$LAST_STDOUT"

# C-10: Optional fields fixture — verifies optional fields don't crash
run_statusline "$(cat "$FIXTURES/valid-optional-fields.json")"
assert_exit_zero "C-10a: exit 0 with optionals" "$LAST_EXIT"
assert_empty "C-10b: no stderr" "$LAST_STDERR"
assert_single_line "C-10c: single line" "$LAST_STDOUT"
assert_contains "C-10d: model in output" "$LAST_STDOUT" "Opus"
assert_contains "C-10e: ctx in output" "$LAST_STDOUT" "ctx:50%"

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
