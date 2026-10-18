#!/bin/bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
INSTALLER="$ROOT/scripts/install-core-guarded.sh"
bash "$ROOT/tests/test-throttle.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

sha256() { shasum -a 256 "$1" | awk '{print $1}'; }

FRESH_ROOT="$TMP/fresh-root"
FRESH_INSTALLER="$FRESH_ROOT/scripts/install-core-guarded.sh"
FRESH_DEST="$TMP/fresh-dest"
FRESH_BACKUP="$TMP/fresh-backup"
mkdir -p "$FRESH_ROOT/scripts" "$FRESH_ROOT/src" "$FRESH_DEST"
cp "$INSTALLER" "$FRESH_INSTALLER"
cp "$ROOT/src/statusline-throttle.zsh" "$FRESH_ROOT/src/statusline-throttle.zsh"
cp "$ROOT/src/statusline.py" "$FRESH_ROOT/src/statusline.py"
cp "$ROOT/src/context_overhead.py" "$FRESH_ROOT/src/context_overhead.py"
chmod 755 "$FRESH_INSTALLER"
chmod 644 "$FRESH_ROOT/src/statusline-throttle.zsh" "$FRESH_ROOT/src/statusline.py" "$FRESH_ROOT/src/context_overhead.py"
test "$(stat -f '%Lp' "$FRESH_ROOT/src/statusline-throttle.zsh")" = 644
test "$(stat -f '%Lp' "$FRESH_ROOT/src/statusline.py")" = 644
"$FRESH_INSTALLER" \
  --dest "$FRESH_DEST" \
  --backup-dir "$FRESH_BACKUP" \
  --expect-status absent \
  --expect-full absent \
  --expect-context absent \
  --status-source throttle
test "$(sha256 "$FRESH_DEST/statusline.py")" = "$(sha256 "$FRESH_ROOT/src/statusline-throttle.zsh")"
test "$(sha256 "$FRESH_DEST/statusline_full.py")" = "$(sha256 "$FRESH_ROOT/src/statusline.py")"
test -x "$FRESH_DEST/statusline.py"
test -x "$FRESH_DEST/statusline_full.py"

DEST="$TMP/dest"
BACKUP="$TMP/backup"
mkdir -p "$DEST"
printf '%s\n' '#!/old/python' 'old statusline' > "$DEST/statusline.py"
printf '%s\n' 'old context' > "$DEST/context_overhead.py"
chmod 755 "$DEST/statusline.py"
chmod 644 "$DEST/context_overhead.py"
STATUS_BEFORE=$(sha256 "$DEST/statusline.py")
CONTEXT_BEFORE=$(sha256 "$DEST/context_overhead.py")
# The production renderer is deliberately non-executable in the repository.
# A migration must still make the installed renderer runnable by the throttle.
test "$(stat -f '%Lp' "$ROOT/src/statusline.py")" = 644

"$INSTALLER" \
  --dest "$DEST" \
  --backup-dir "$BACKUP" \
  --expect-status "$STATUS_BEFORE" \
  --expect-full absent \
  --expect-context "$CONTEXT_BEFORE"

test "$(sha256 "$DEST/statusline.py")" = "$(sha256 "$ROOT/src/statusline-throttle.zsh")"
test "$(sha256 "$DEST/statusline_full.py")" = "$(sha256 "$ROOT/src/statusline.py")"
test "$(sha256 "$DEST/context_overhead.py")" = "$(sha256 "$ROOT/src/context_overhead.py")"
test "$(sha256 "$BACKUP/statusline.py")" = "$STATUS_BEFORE"
test "$(sha256 "$BACKUP/context_overhead.py")" = "$CONTEXT_BEFORE"
test "$(stat -f '%Lp' "$DEST/statusline.py")" = 755
test -x "$DEST/statusline.py"
test -x "$DEST/statusline_full.py"
test "$(stat -f '%Lp' "$DEST/context_overhead.py")" = 644
test "$(stat -f '%Lp' "$BACKUP/statusline.py")" = 755
test "$(stat -f '%Lp' "$BACKUP/context_overhead.py")" = 644

FALLBACK_DEST="$TMP/fallback"
FALLBACK_BACKUP="$TMP/fallback-backup"
mkdir -p "$FALLBACK_DEST"
printf '%s\n' 'old fallback status' > "$FALLBACK_DEST/statusline.py"
printf '%s\n' 'old fallback context' > "$FALLBACK_DEST/context_overhead.py"
FALLBACK_STATUS=$(sha256 "$FALLBACK_DEST/statusline.py")
FALLBACK_CONTEXT=$(sha256 "$FALLBACK_DEST/context_overhead.py")
"$INSTALLER" \
  --dest "$FALLBACK_DEST" \
  --backup-dir "$FALLBACK_BACKUP" \
  --expect-status "$FALLBACK_STATUS" \
  --expect-full absent \
  --expect-context "$FALLBACK_CONTEXT" \
  --status-source full
test "$(sha256 "$FALLBACK_DEST/statusline.py")" = "$(sha256 "$ROOT/src/statusline.py")"
test "$(sha256 "$FALLBACK_DEST/statusline_full.py")" = "$(sha256 "$ROOT/src/statusline.py")"
test -x "$FALLBACK_DEST/statusline.py"
test -x "$FALLBACK_DEST/statusline_full.py"

REFUSE_DEST="$TMP/refuse"
REFUSE_BACKUP="$TMP/refuse-backup"
mkdir -p "$REFUSE_DEST"
printf '%s\n' 'changed statusline' > "$REFUSE_DEST/statusline.py"
printf '%s\n' 'changed context' > "$REFUSE_DEST/context_overhead.py"
REFUSE_STATUS=$(sha256 "$REFUSE_DEST/statusline.py")
REFUSE_CONTEXT=$(sha256 "$REFUSE_DEST/context_overhead.py")

if "$INSTALLER" \
  --dest "$REFUSE_DEST" \
  --backup-dir "$REFUSE_BACKUP" \
  --expect-status 0000000000000000000000000000000000000000000000000000000000000000 \
  --expect-full absent \
  --expect-context "$REFUSE_CONTEXT" 2>"$TMP/refusal.stderr"; then
  echo "expected digest mismatch refusal" >&2
  exit 1
fi

grep -q "deployed source digest changed" "$TMP/refusal.stderr"

test "$(sha256 "$REFUSE_DEST/statusline.py")" = "$REFUSE_STATUS"
test "$(sha256 "$REFUSE_DEST/context_overhead.py")" = "$REFUSE_CONTEXT"
test ! -e "$REFUSE_BACKUP"

REINSTALL_BACKUP="$TMP/reinstall-backup"
REINSTALL_STATUS_MODE=$(stat -f '%Lp' "$DEST/statusline.py")
REINSTALL_FULL_MODE=$(stat -f '%Lp' "$DEST/statusline_full.py")
REINSTALL_CONTEXT_MODE=$(stat -f '%Lp' "$DEST/context_overhead.py")
"$INSTALLER" \
  --dest "$DEST" \
  --backup-dir "$REINSTALL_BACKUP" \
  --expect-status "$(sha256 "$DEST/statusline.py")" \
  --expect-full "$(sha256 "$DEST/statusline_full.py")" \
  --expect-context "$(sha256 "$DEST/context_overhead.py")"
test -f "$REINSTALL_BACKUP/statusline.py"
test -f "$REINSTALL_BACKUP/statusline_full.py"
test -f "$REINSTALL_BACKUP/context_overhead.py"
test "$(stat -f '%Lp' "$REINSTALL_BACKUP/statusline.py")" = "$REINSTALL_STATUS_MODE"
test "$(stat -f '%Lp' "$REINSTALL_BACKUP/statusline_full.py")" = "$REINSTALL_FULL_MODE"
test "$(stat -f '%Lp' "$REINSTALL_BACKUP/context_overhead.py")" = "$REINSTALL_CONTEXT_MODE"

MAIN_HOME="$TMP/main-home"
MAIN_DEST="$MAIN_HOME/.claude"
mkdir -p "$MAIN_DEST"
printf '%s\n' '#!/old/python' 'old statusline' > "$MAIN_DEST/statusline.py"
printf '%s\n' 'old context' > "$MAIN_DEST/context_overhead.py"
printf '%s\n' '{"refreshInterval":10,"statusLine":{"type":"command","command":"old"},"keep":true}' > "$MAIN_DEST/settings.json"
HOME="$MAIN_HOME" "$ROOT/install.sh" --no-obs > "$TMP/main-install.log"
test "$(sha256 "$MAIN_DEST/statusline.py")" = "$(sha256 "$ROOT/src/statusline-throttle.zsh")"
test "$(sha256 "$MAIN_DEST/statusline_full.py")" = "$(sha256 "$ROOT/src/statusline.py")"
test -x "$MAIN_DEST/statusline.py"
test -x "$MAIN_DEST/statusline_full.py"
test "$(jq -r '.refreshInterval' "$MAIN_DEST/settings.json")" = 10
test "$(jq -r '.statusLine.command' "$MAIN_DEST/settings.json")" = old
HOME="$MAIN_HOME" "$ROOT/install.sh" --no-obs >> "$TMP/main-install.log"
test "$(jq -r '.refreshInterval' "$MAIN_DEST/settings.json")" = 10

ADAPT_HOME="$TMP/adapt-home"
ADAPT_DEST="$ADAPT_HOME/.claude"
ADAPT_BIN="$TMP/adapt-bin"
mkdir -p "$ADAPT_DEST" "$ADAPT_BIN"
printf '%s\n' 'old adapt status' > "$ADAPT_DEST/statusline.py"
printf '%s\n' 'old adapt context' > "$ADAPT_DEST/context_overhead.py"
printf '%s\n' '{"statusLine":{"type":"command","command":"old"}}' > "$ADAPT_DEST/settings.json"
printf '%s\n' '#!/bin/sh' 'printf "3 10\\n"' > "$ADAPT_BIN/python3.13"
printf '%s\n' '#!/bin/sh' 'printf "9\\n"' > "$ADAPT_BIN/python3"
chmod 755 "$ADAPT_BIN/python3.13" "$ADAPT_BIN/python3"
PATH="$ADAPT_BIN:$PATH" HOME="$ADAPT_HOME" "$ROOT/install.sh" --no-obs --status-source full > "$TMP/adapt-install.log"
test "$(head -n 1 "$ADAPT_DEST/statusline.py")" = "#!$ADAPT_BIN/python3.13"
test "$(head -n 1 "$ADAPT_DEST/statusline_full.py")" = "#!$ADAPT_BIN/python3.13"

ROLLBACK_DEST="$TMP/rollback"
ROLLBACK_BACKUP="$TMP/rollback-backup"
mkdir -p "$ROLLBACK_DEST" "$TMP/fake-bin"
printf '%s\n' 'old status' > "$ROLLBACK_DEST/statusline.py"
printf '%s\n' 'old context' > "$ROLLBACK_DEST/context_overhead.py"
chmod 640 "$ROLLBACK_DEST/statusline.py"
chmod 604 "$ROLLBACK_DEST/context_overhead.py"
ROLLBACK_STATUS=$(sha256 "$ROLLBACK_DEST/statusline.py")
ROLLBACK_CONTEXT=$(sha256 "$ROLLBACK_DEST/context_overhead.py")
ROLLBACK_STATUS_MODE=$(stat -f '%Lp' "$ROLLBACK_DEST/statusline.py")
ROLLBACK_CONTEXT_MODE=$(stat -f '%Lp' "$ROLLBACK_DEST/context_overhead.py")
# shellcheck disable=SC2016 # The wrapper must expand these values when it runs.
printf '%s\n' \
  '#!/bin/bash' \
  'if [ "${!#}" = "$QLINE_FAIL_DEST" ] && [ ! -e "$QLINE_FAIL_ONCE" ]; then' \
  '  : > "$QLINE_FAIL_ONCE"' \
  '  exit 1' \
  'fi' \
  'exec "$QLINE_REAL_MV" "$@"' > "$TMP/fake-bin/mv"
chmod 755 "$TMP/fake-bin/mv"
REAL_MV=$(command -v mv)
if PATH="$TMP/fake-bin:$PATH" QLINE_REAL_MV="$REAL_MV" QLINE_FAIL_DEST="$ROLLBACK_DEST/context_overhead.py" QLINE_FAIL_ONCE="$TMP/mv-failed" "$INSTALLER" \
  --dest "$ROLLBACK_DEST" \
  --backup-dir "$ROLLBACK_BACKUP" \
  --expect-status "$ROLLBACK_STATUS" \
  --expect-full absent \
  --expect-context "$ROLLBACK_CONTEXT"; then
  echo "expected partial install failure" >&2
  exit 1
fi
test "$(sha256 "$ROLLBACK_DEST/statusline.py")" = "$ROLLBACK_STATUS"
test "$(sha256 "$ROLLBACK_DEST/context_overhead.py")" = "$ROLLBACK_CONTEXT"
test "$(stat -f '%Lp' "$ROLLBACK_DEST/statusline.py")" = "$ROLLBACK_STATUS_MODE"
test "$(stat -f '%Lp' "$ROLLBACK_DEST/context_overhead.py")" = "$ROLLBACK_CONTEXT_MODE"
test ! -e "$ROLLBACK_DEST/statusline_full.py"

REPORT_DEST="$TMP/rollback-report"
REPORT_BACKUP="$TMP/rollback-report-backup"
REPORT_BIN="$TMP/rollback-report-bin"
mkdir -p "$REPORT_DEST" "$REPORT_BIN"
printf '%s\n' 'old report status' > "$REPORT_DEST/statusline.py"
printf '%s\n' 'old report context' > "$REPORT_DEST/context_overhead.py"
REPORT_STATUS=$(sha256 "$REPORT_DEST/statusline.py")
REPORT_CONTEXT=$(sha256 "$REPORT_DEST/context_overhead.py")
# shellcheck disable=SC2016 # The wrapper must expand these values when it runs.
printf '%s\n' \
  '#!/bin/bash' \
  'destination=${!#}' \
  'if [ "$destination" = "$QLINE_REPORT_STATUS" ] && [ ! -e "$QLINE_REPORT_STATUS_INSTALLED" ]; then' \
  '  : > "$QLINE_REPORT_STATUS_INSTALLED"' \
  '  exec "$QLINE_REAL_MV" "$@"' \
  'fi' \
  'if [ "$destination" = "$QLINE_REPORT_CONTEXT" ] || [ "$destination" = "$QLINE_REPORT_STATUS" ]; then' \
  '  exit 1' \
  'fi' \
  'exec "$QLINE_REAL_MV" "$@"' > "$REPORT_BIN/mv"
chmod 755 "$REPORT_BIN/mv"
if PATH="$REPORT_BIN:$PATH" QLINE_REAL_MV="$REAL_MV" QLINE_REPORT_STATUS="$REPORT_DEST/statusline.py" QLINE_REPORT_CONTEXT="$REPORT_DEST/context_overhead.py" QLINE_REPORT_STATUS_INSTALLED="$TMP/report-status-installed" "$INSTALLER" \
  --dest "$REPORT_DEST" \
  --backup-dir "$REPORT_BACKUP" \
  --expect-status "$REPORT_STATUS" \
  --expect-full absent \
  --expect-context "$REPORT_CONTEXT" 2>"$TMP/rollback-report.stderr"; then
  echo "expected rollback reporting fixture to fail" >&2
  exit 1
fi
test "$(sha256 "$REPORT_BACKUP/statusline.py")" = "$REPORT_STATUS"
test "$(sha256 "$REPORT_BACKUP/context_overhead.py")" = "$REPORT_CONTEXT"
grep -Fq "rollback failed for $REPORT_DEST/statusline.py" "$TMP/rollback-report.stderr"
grep -Fq "rollback incomplete; backup retained at $REPORT_BACKUP" "$TMP/rollback-report.stderr"

echo "guarded core installer: PASS"
