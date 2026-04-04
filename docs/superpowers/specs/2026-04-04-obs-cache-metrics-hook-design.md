# Obs Cache Metrics Hook — Design Spec

**Date:** 2026-04-04
**Status:** Approved (council-reviewed, 2 rounds)
**Scope:** New `obs-stop-cache.py` hook + `update_manifest_if_absent()` in obs_utils + status line anchor migration

## Problem

The qLine overhead monitor (`_inject_context_overhead`) reads the session transcript JSONL directly to extract cache metrics. This is architecturally wrong — no other obs hook parses the live transcript mid-session. The transcript reading is fragile (flush races, tail-window anchor drift on cache clears) and couples the status line to an undocumented file format.

The obs layer already captures every other session signal (reads, writes, bash commands, prompts, compactions, subagents, tasks) via dedicated hooks that write to the session package. Cache metrics are the missing signal.

## Solution

Add a new `obs-stop-cache.py` hook that fires on every `Stop` event, extracts cache metrics from the transcript, and writes them to the session package. The sidecar provides **durable forensics and anchor persistence** — it does NOT replace the status line's direct transcript reading for real-time display.

### What the sidecar IS for

1. **Durable forensics** — `generate_overhead_report()` reads the sidecar instead of re-parsing the full transcript
2. **Cache health history** — trailing window for hit rate, survives session package finalization
3. **Anchor persistence** — manifest stores `cache_anchor` so `_try_phase2_transcript` doesn't re-derive it after `/tmp` cache clears
4. **Compaction correlation** — tags turns as post-compaction using the manifest `compactions` array

### What the sidecar is NOT for

The status line continues reading the transcript directly for real-time overhead display. The sidecar is always one turn stale relative to the status line (both fire on the same Stop event), making it unsuitable as the primary real-time source.

## Hook: `obs-stop-cache.py`

### Trigger

`Stop` event only. Not `SubagentStop`. Timeout: 2000ms.

### Input

Hook payload via stdin: `session_id`, `transcript_path`, `hook_event_name`, `stop_hook_active`.

### Per-Invocation Flow

1. Read stdin via `read_hook_input(timeout_seconds=2)`
2. Exit 0 if: empty stdin, no `session_id`, `stop_hook_active` is true
3. Resolve `package_root` via `resolve_package_root(session_id)`. Exit 0 if None.
4. Read transcript tail — seek to last 8KB, scan backward for the last entry with `stop_reason != null` and a `message.usage` or `toolUseResult.usage` containing cache fields
5. **Flush detection:** Compare found entry against last-seen turn stored in sidecar. If no new entry since last invocation, emit `cache.skipped` to ledger with reason `NO_NEW_ENTRY` and exit.
6. Extract fields from usage object
7. **Compaction detection:** Read manifest `compactions` array length. Compare against last-seen count from previous sidecar record. If increased, tag record `post_compaction: true`.
8. Append `cache.observed` event to `hook_events.jsonl` via `append_event()`
9. Append full record to `custom/cache_metrics.jsonl` via `_atomic_jsonl_append()`
10. **Anchor (first non-compaction turn only):** Call `update_manifest_if_absent(package_root, "cache_anchor", value)` to write the anchor to the manifest. Also write `cache_anchor_turn` and `cache_anchor_is_post_compaction`.

### Transcript Reading — Hardened

Every `json.loads()` wrapped in try/except. Walks backward from EOF. Caps at 50 lines scanned.

**Flush detection** uses turn-sequence comparison, NOT timestamp staleness:
- The hook stores the last-seen transcript entry's `message.id` (or line offset) in the sidecar's last record
- On next invocation, if the latest parseable entry has the same ID, the transcript hasn't advanced — emit `cache.skipped` with `NO_NEW_ENTRY`
- This correctly detects "entry not flushed yet" without false-positiving on slow turns

**If no valid entry found:** Emit `cache.skipped` with `TRANSCRIPT_UNREADABLE`. Exit 0.

### Failure Mode

`run_fail_open` wrapper. Any exception exits 0 silently. Never blocks the session.

## Sidecar Schema: `custom/cache_metrics.jsonl`

Normal record (~250 bytes):
```json
{
  "ts": "2026-04-04T05:30:12Z",
  "session_id": "abc123",
  "turn": 7,
  "cache_read": 95000,
  "cache_create": 250,
  "input_tokens": 1200,
  "output_tokens": 443,
  "cache_create_1h": 250,
  "cache_create_5m": 0,
  "model": "claude-opus-4-6",
  "post_compaction": false,
  "last_entry_id": "msg_01ABC...",
  "skipped": false
}
```

Skipped record (~120 bytes):
```json
{
  "ts": "2026-04-04T05:30:45Z",
  "session_id": "abc123",
  "turn": 8,
  "skipped": true,
  "skip_reason": "NO_NEW_ENTRY"
}
```

Field naming follows the Anthropic API (`cache_creation_input_tokens` → `cache_create` for brevity, matching existing `_read_transcript_tail` variable names). `cache_create_1h` and `cache_create_5m` mirror the nested `cache_creation.ephemeral_*` fields.

Growth: ~250 bytes/turn. 200-turn session = ~50KB. 2000-turn pathological session = ~500KB.

## Manifest Additions

On first non-compaction turn, `update_manifest_if_absent()` writes:

```json
{
  "cache_anchor": 42000,
  "cache_anchor_turn": 1,
  "cache_anchor_is_post_compaction": false
}
```

Write-once — never overwritten during the session.

## New Function: `update_manifest_if_absent()`

Added to `~/.claude/scripts/obs_utils.py`:

```python
def update_manifest_if_absent(
    package_root: str, key: str, value: Any
) -> bool:
    """Write a key to manifest only if it doesn't already exist.

    Uses fcntl.LOCK_EX to prevent race conditions.
    Returns True if the key was written, False if already present.
    """
```

This opens the manifest under `fcntl.LOCK_EX`, checks `key not in manifest`, writes only if absent, and returns whether it wrote. Follows the same locking pattern as `update_manifest_array()`.

Also supports batch writes for related keys:

```python
def update_manifest_if_absent_batch(
    package_root: str, updates: dict[str, Any]
) -> bool:
    """Write multiple keys to manifest, only if the first key is absent.

    Atomically writes all keys or none. Uses the first key as the gate.
    """
```

## Ledger Event: `cache.observed`

Appended to `hook_events.jsonl` via `append_event()`:

```json
{
  "event": "cache.observed",
  "session_id": "abc123",
  "data": {
    "cache_read": 95000,
    "cache_create": 250,
    "input_tokens": 1200,
    "post_compaction": false
  }
}
```

For skipped turns:
```json
{
  "event": "cache.skipped",
  "session_id": "abc123",
  "data": {
    "reason": "NO_NEW_ENTRY"
  }
}
```

## Status Line Integration

### Anchor Migration

`_try_phase2_transcript()` in `statusline.py` currently derives the anchor from the transcript on every 30s cache refresh. Migrate to:

1. **Primary:** Read `cache_anchor` from manifest (via existing `_read_obs_health` path that already opens the manifest)
2. **Fallback:** Derive from transcript (existing behavior, kept intact)

This is a one-line change: before the `if "turn_1_anchor" not in session_cache:` block, check the manifest value first.

### No Other Status Line Changes

The status line's `_inject_context_overhead()` continues reading the transcript directly for real-time metrics. The sidecar is consumed only by `generate_overhead_report()` and future forensics tools.

### Cache Health from Sidecar (Future)

When a dedicated cache health display module is added (separate from the overhead bar), it can read the sidecar's trailing window for hit rate calculation. This is a future enhancement, not part of this spec.

## Compaction Detection

Read manifest `compactions` array length (maintained by `obs-precompact.py`). The hook stores the last-seen compaction count as a field in the most recent sidecar record. On each invocation:

- Read current `len(manifest["compactions"])` — manifest is already opened for anchor check
- Compare against `prev_record.get("compaction_count", 0)` from last sidecar line
- If increased: tag current record `post_compaction: true`

**Race condition with PreCompact:** If PreCompact and Stop fire concurrently, the manifest read may see the stale count. This produces at most one spurious `post_compaction: false` record per compaction event. This is acceptable because:
- The anchor is write-once (already set by the time compaction occurs)
- The `post_compaction` tag is informational, not used for control flow
- The next Stop invocation reads the correct count

## Hook Registration

Add to `~/.claude/settings.json` Stop event:

```json
{
  "matcher": "Stop",
  "hooks": [
    {
      "type": "command",
      "command": "/home/q/.claude/hooks/obs-stop-cache.py",
      "timeout": 2000
    }
  ]
}
```

## Implementation Scope

### Files Created
- `~/.claude/hooks/obs-stop-cache.py` — the hook

### Files Modified
- `~/.claude/scripts/obs_utils.py` — add `update_manifest_if_absent()` and `update_manifest_if_absent_batch()`
- `~/LAB/qLine/src/statusline.py` — anchor migration: read `cache_anchor` from manifest as primary source
- `~/.claude/settings.json` — add Stop hook registration

### Files NOT Modified
- Existing obs hooks — no changes needed
- `qline.example.toml` — no new config keys
- Test harness — new tests added to `tests/test-statusline.sh`

## Test Strategy

### Hook Unit Tests
- Mock transcript with known cache fields → verify sidecar output
- Truncated last line → verify graceful skip
- No new entry since last invocation → verify `cache.skipped` event
- First non-compaction turn → verify anchor written to manifest
- Second turn → verify anchor NOT overwritten
- Post-compaction turn → verify `post_compaction: true` tag

### Status Line Tests
- Manifest has `cache_anchor` → verify status line reads it
- Manifest missing `cache_anchor` → verify fallback to transcript derivation
- Both manifest and transcript available → verify manifest takes priority

### Integration Tests
- Full session flow: start → 3 turns → verify sidecar has 3 records + anchor in manifest

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Transcript not flushed when Stop fires | Missed turn in sidecar | Turn-sequence comparison detects it; `cache.skipped` event logged; next turn self-heals |
| Truncated last line in transcript | Failed parse | try/except on every json.loads; backward scan; skip unparseable lines |
| PreCompact races with Stop on manifest read | Wrong compaction count for one turn | Acceptable — post_compaction tag is informational only; anchor is already write-once |
| `update_manifest_if_absent` fails on turn 1 | Anchor never persisted to manifest | Status line falls back to transcript-derived anchor (existing behavior) |
| Sidecar grows large on pathological sessions | Disk usage | 250 bytes/turn; 2000 turns = 500KB; negligible |
| Claude Code changes transcript format | Hook extraction breaks | Hook exits 0 on any parse failure; status line transcript tailing unaffected |

## Council Review Log

### Round 1 (pre-revision)
- Architecture reviewer: Verify Stop timing contract; transcript reading in hooks is uncharted
- Payload verifier: Stop payload confirmed to include `session_id`, `transcript_path`; transcript flush not guaranteed
- Edge case reviewer: 2 blockers (flush race, truncation), 6 majors (compaction detection, anchor stability, double-counting, missing file handling)

### Round 2 (post-revision)
- Architecture reviewer: Blocker — `update_manifest()` doesn't support write-once; Major — don't replace transcript tailing with sidecar; Major — simplify cascade
- Edge case reviewer: staleness threshold detects wrong condition (use turn-sequence, not timestamp); compaction count race is acceptable; fallback oscillation must use existing TTL

### Design Revisions Applied
1. Sidecar is forensics + anchor persistence, NOT a status line replacement
2. Status line keeps direct transcript reading for real-time display
3. New `update_manifest_if_absent()` for write-once anchor
4. Turn-sequence comparison replaces timestamp staleness
5. Compaction detection via manifest array count, not `model=<synthetic>`
6. `session_id` added to sidecar schema per convention

## References

- Existing dual-write hook: `obs-pretool-read.py` (ledger + custom/reads.jsonl)
- Compaction tracking: `obs-precompact.py` (manifest compactions array)
- Session start pattern: `obs-session-start.py` (manifest creation + ledger)
- Shared library: `obs_utils.py` (append_event, update_manifest, _atomic_jsonl_append)
- Status line overhead monitor: `statusline.py` (_inject_context_overhead, _try_phase2_transcript)
- Context overhead monitor spec: `docs/superpowers/specs/2026-04-04-context-overhead-monitor-design.md`
