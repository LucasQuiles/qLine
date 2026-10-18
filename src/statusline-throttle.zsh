#!/bin/zsh -f
# Reuse one session's status-line output while its transcript is unchanged.
emulate -L zsh
zmodload zsh/datetime 2>/dev/null
zmodload -F zsh/stat b:zstat 2>/dev/null

full=${0:A:h}/statusline_full.py
ttl=${QLINE_THROTTLE_TTL:-10}
[[ $ttl == <-> ]] || ttl=10

payload=''
IFS= read -r -d '' payload

run_full() {
  print -rn -- "$payload" | "$full"
}

safe_cache_dir() {
  local -A state
  if [[ -e $1 || -L $1 ]]; then
    [[ -d $1 && ! -L $1 ]] || return 1
  else
    mkdir -p -m 700 -- "$1" 2>/dev/null || return 1
  fi
  zstat -H state -- "$1" 2>/dev/null || return 1
  (( state[uid] == EUID && state[mode] == 16832 ))
}

[[ -x $full ]] || exit 0
sid='' transcript=''
[[ $payload =~ '"session_id"[[:space:]]*:[[:space:]]*"([A-Za-z0-9_-]+)"' ]] && sid=$match[1]
[[ $payload =~ '"transcript_path"[[:space:]]*:[[:space:]]*"([^"]+)"' ]] && transcript=$match[1]

local -A transcript_state
if [[ -z $sid || -z $transcript || -z ${EPOCHSECONDS-} ]] || ! zstat -H transcript_state -- "$transcript" 2>/dev/null; then
  run_full
  exit 0
fi

cache_dir=${TMPDIR:-/tmp}/qline-throttle
if ! safe_cache_dir "$cache_dir"; then
  run_full
  exit 0
fi

cache=$cache_dir/$sid
now=$EPOCHSECONDS
if [[ -f $cache && ! -L $cache ]]; then
  {
    IFS=' ' read -r cached_at cached_mtime cached_size
    body=''
    IFS= read -r -d '' body
  } < "$cache"
  if [[ $cached_at == <-> && $cached_mtime == <-> && $cached_size == <-> ]] \
    && (( now >= cached_at && now - cached_at < ttl )) \
    && (( cached_mtime == transcript_state[mtime] )) \
    && (( cached_size == transcript_state[size] )); then
    print -rn -- "$body"
    exit 0
  fi
fi

out=$(run_full; print -n x)
out=${out%x}
stage=$(mktemp "$cache_dir/.qline-${sid}.XXXXXX" 2>/dev/null) || {
  print -rn -- "$out"
  exit 0
}
{
  print -r -- "$now ${transcript_state[mtime]} ${transcript_state[size]}"
  print -rn -- "$out"
} >| "$stage"
chmod 600 "$stage" 2>/dev/null || true
mv -f -- "$stage" "$cache" 2>/dev/null || rm -f -- "$stage"
print -rn -- "$out"
