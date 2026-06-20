# PreCompact Orchestrator — portable tool

One registered `PreCompact` hook that preserves the most load-bearing session
state into a single capsule injected back at compaction time. Shape A: one hook
runs N producers as subprocesses, merges into one versioned capsule with an
observability envelope, behind a single fail-open boundary.

## Files

| File | Role |
|------|------|
| `precompact-orchestrator.py` | Registered hook entrypoint (gated by env flag). |
| `precompact_orchestrator_lib.py` | Fan-out core: run producers concurrently, merge. |
| `precompact_producers.py` | The 5 producers (preserve, git, failures, stats, handoff). |
| `precompact_capsule.py` | Versioned capsule schema + session-keyed store. |
| `precompact_handoff.py` | Agent-authored handoff note (read/write CLI). |
| `precompact_ledger.py` | Bounded tail reader for the action-ledger. |
| `precompact_paths.py` | Single session-id → path-safe filename sanitizer. |
| `precompact_botpatches_forward.py` | Optional fault-rot escalation relay. |
| **`precompact_config.py`** | **Single config surface — every host seam resolves here.** |

## Configuration (single surface)

All host/environment-specific seams live in `precompact_config.py`. Nothing
host-specific is baked into any other module — no machine paths, no chat IDs.
A deployer points the tool at their environment with env vars only:

| Env var | Default | Purpose |
|---------|---------|---------|
| `PRECOMPACT_ORCHESTRATOR_ENABLED` | unset (off) | Master enable flag (`1` = on). Rollback = unset. |
| `PRECOMPACT_CAPSULE_DIR` | `~/.claude/precompact-capsules` | Capsule store. |
| `PRECOMPACT_HANDOFF_DIR` | `~/.claude/precompact-handoff` | Handoff-note store. |
| `PRECOMPACT_LEDGER_PATH` | `~/.local/share/brick-lab/action-ledger.jsonl` | Source action-ledger. |
| `PRECOMPACT_FAULT_LEDGER` | `~/.claude/logs/lifecycle-hook-faults.jsonl` | Fault/rot ledger. |
| `PRECOMPACT_ROT_OFFSET_FILE` | `~/.claude/logs/precompact-rot-forward.offset` | Rot-forward cursor. |
| `PRECOMPACT_BOTPATCHES_CHAT` | `""` (disabled) | Escalation channel id. **Empty ships sterile**; set to opt in. |
| `PRECOMPACT_PRODUCER_DEADLINE_S` | `3.0` | Per-producer subprocess deadline. |
| `PRECOMPACT_MAX_REPOS` | `5` | Max git repos reported. |
| `PRECOMPACT_MAX_FAILURES` | `10` | Max unresolved failures reported. |

## Deploy

1. Copy the `precompact_*.py` modules + `precompact-orchestrator.py` into your
   hooks dir (alongside `hook_utils.py`, `obs_utils.py`).
2. Register the hook in your Claude settings `PreCompact` array, pointing at
   `precompact-orchestrator.py` via your hook runner.
3. Set env in settings `env`:
   - `PRECOMPACT_ORCHESTRATOR_ENABLED": "1"` to enable.
   - Optionally override any path/tunable above.
   - Set `PRECOMPACT_BOTPATCHES_CHAT` only if you want fault-rot escalation.
4. Roll out shadow → warn → enforce; rollback by unsetting the enable flag.

## Design principles (Appendix D rider)

Reuse-first (not reuse-only) · single versioned receipt/event schema · shared
classifiers · shadow→warn→enforce rollout with env flag + rollback · no raw
secrets / no transcript persistence · measurable + experiment-gated.

## Tests

```
python3 -m pytest tests/ -q
```

Full spec + rollout/hardening log: `docs/superpowers/specs/2026-06-19-precompact-orchestrator-design.md`.
