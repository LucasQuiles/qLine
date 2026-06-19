# PreCompact Orchestrator + Deterministic Capsule — v1 Design

**Date:** 2026-06-19
**Status:** Design approved (v1 scope); external-worker distillation deferred to v2
**Repos touched:** qLine (primary), bricklab (producer module)

## Problem

When a Claude Code session compacts (manual `/compact` or auto-compact when the
context window fills), three independent PreCompact hooks fire across two repos:

- `bricklab/hooks/enrich-precompact.py` — action-ledger aggregation into a "Brick
  brief" (~600-token cap). No GPU call; pure local aggregation. Also replays
  stored Brick *findings* (LLM speculation captured earlier in the session).
- `qLine/hooks/precompact-preserve.py` — injects open tasks + active plan via
  `systemMessage`. **This is the only hook delivering real continuity value today.**
- `qLine/hooks/obs-precompact.py` — telemetry only (emits `compact.started`).

Three subprocesses, two separate fail-open wrappers (`hook_utils.run_fail_open`
vs `brick_hook_support.run_fail_open`), two separately-injected blobs with
overlap and a semantics gap, and no clean pairing with the SessionStart:compact
re-injection set. The injected content is mechanical and shallow; it does not
capture *intent, drift, blockers, or next action* — the things a resumed agent
most needs.

An earlier proposal added an async external-cheap-model ("opencode worker")
distillation panel to inject "intelligent" judgment artifacts. A 4-lens
adversarial review (security, latency, signal-fidelity, ops) refuted that panel
as specced — see **Appendix A**. This design carries forward only what survived.

## Goals

1. **Consolidate** the three PreCompact hooks into one orchestrator that produces
   a single capsule through one fail-open boundary (Shape A).
2. **Harden** the deterministic core so it is fast, bounded, observable, and never
   silently rots.
3. **Add the one intelligent upgrade that survived review:** an
   **agent-authored handoff note** — the live, fully-context'd, *trusted* agent
   writes intent / blockers / next-action / drift in its own words at compaction
   time. No sanitization, no latency, no third-party exposure, no "unverified"
   label.
4. **Protect** the currently-working `precompact-preserve.py` behavior with a
   golden parity test and a safe rollout.

## Non-Goals (deferred to v2)

- External cheap-model worker panel (distiller / drift-auditor / concern-spotter /
  prioritizer). Deferred pending: a sanitization model that is actually
  fail-closed, an injection path that the artifact reaches in time, and a
  measurement harness proving it beats the handoff note. See **Appendix B**.
- Pinecone / episodic durable-memory writes of the capsule.
- Any change to the SessionStart hooks beyond what re-injection + observability
  require.

## Architecture

### Orchestrator

One registered PreCompact hook (`precompact-orchestrator.py` in qLine). It invokes
each producer and merges results into ONE capsule object, then injects once.

**Producer isolation — subprocess, not import.** Producers run as subprocesses
(`python3 <producer> --json-out`), not Python imports. This removes the cross-repo
import coupling (qLine importing bricklab modules with no deploy contract) flagged
by the ops lens, and gives hard fail-isolation: one producer crashing cannot
corrupt the orchestrator's memory or block the others.

**Single fail-open boundary.** The orchestrator is wrapped once in
`run_fail_open`. A producer that errors, times out, or returns malformed JSON is
recorded as failed (see Observability) and omitted; the capsule still ships with
the surviving sections.

### Producers (v1)

| Producer | Source | Output section | Must-be-exact |
|---|---|---|---|
| `preserve` | open tasks + active plan (existing logic) | `open_tasks`, `active_plan` | yes |
| `git` | branch, dirty count, unpushed count per active repo | `git_state` | yes |
| `failures` | failed commands with no later success in session | `unresolved_failures` | yes |
| `stats` | action-ledger tool/file/repo counts (demoted Brick aggregator) | `session_stats` | informational |
| `handoff` | **agent-authored note** (see below) | `handoff_note` | trusted, agent's words |

**Dropped from the old pipeline:** the Brick *findings replay*. It re-injected
unverified LLM speculation at every compaction, which our own doctrine ("Brick
enrichments are untrusted hints") says to skip. The mechanical `stats` aggregator
is retained.

### Agent-Authored Handoff Note

The highest-value addition. Rather than a model guessing intent from starved
metadata, the **live agent** records a short handoff at compaction time, in its
own words, covering: current intent, active blockers, next concrete action, and
any drift from the stated goal.

**Mechanism (to be finalized in the implementation plan):** the agent maintains a
small, append/overwrite handoff file during the session (e.g. via a lightweight
`capture_task`-style write or a dedicated note path keyed on `session_id`). At
PreCompact the `handoff` producer reads the latest note. If no note exists, the
section is simply absent — never fabricated. Because this content is authored by
the trusted agent and never leaves the machine, it requires **no sanitization**
and carries **no "unverified" label**.

### Capsule + Injection

- PreCompact writes the merged capsule synchronously and injects it (single
  `systemMessage` / `additionalContext`). All work on this path is bounded and
  fast (see Performance).
- The capsule is also written to a `session_id`-keyed file so the
  SessionStart:compact re-injection hook can confirm/re-surface it.

## Hardening (each maps to an adversarial finding)

1. **Bounded reads, not full-file scans** *(latency CRIT).* The action-ledger /
   metrics JSONL must be read by **tail / offset index**, not
   `read_text().splitlines()`. The current full-file read (≈45 MB) silently fails
   open once it exceeds the 5s hook timeout. Target: O(session), not O(all-time).
2. **Per-producer observability** *(ops CRIT — owner rule: "alerts must be
   actionable; silent degradation is unacceptable").* The capsule carries
   `_producers_ok` / `_producers_failed`. The SessionStart re-injection asserts
   expected sections are present and **alerts BOT PATCHES** when a producer has
   been dead. No silent rot. stderr is not a monitoring channel on a compact event.
3. **Internal deadline on every producer** *(latency MED).* Each producer
   subprocess gets a hard wall-clock timeout (≤3s) enforced by the orchestrator,
   independent of the outer hook timeout. JSONL reads get their own guard.
4. **Empty-output signal** *(latency/ops MED).* When all producers yield nothing
   on a compaction, that is logged as an actionable signal (capture pipeline not
   capturing), not silently treated as success.

## Performance budget

- Orchestrator synchronous path target: **< 1.5s p95**, hard ceiling 3s.
- Producers run concurrently where independent; each bounded ≤3s.
- No network calls on the PreCompact path in v1.

## Observability

- Capsule envelope: `{ _producers_ok: [...], _producers_failed: [...],
  _empty: bool, _ms: <int> }`.
- SessionStart:compact validates the envelope and fires a BOT PATCHES alert if a
  producer regressed or the capsule was empty.
- A weekly summary (producer success rates, p95 latency) is acceptable as a
  follow-on, not required for v1.

## Rollout (no flag day)

*(ops HIGH — hooks are all-or-nothing in settings.json)*

1. Land the orchestrator gated behind `PRECOMPACT_ORCHESTRATOR_ENABLED=1`. Unset →
   it exits 0 immediately.
2. Keep the legacy `precompact-preserve.py` registered **in parallel** during
   migration. Duplicate task/plan injection is idempotent and harmless.
3. Enable the orchestrator; audit ≥5 real compaction capsules via the SessionStart
   sentinel.
4. Only after clean audits, deregister the three legacy hooks. Rollback = unset
   the env var; the legacy hook resumes.

## Testing

- **Golden parity test** *(ops MED — protect the one working hook).* A pytest
  fixture with a synthetic transcript containing open tasks + an active plan
  asserts the **orchestrator** capsule reproduces those tasks/plan in the format
  SessionStart re-injection expects. Integration-level (full orchestrator), not
  the producer in isolation. This is the regression gate for existing value.
- Producer-failure test: a deliberately-throwing producer is recorded in
  `_producers_failed` and the capsule still ships surviving sections.
- Bounded-read test: a large synthetic JSONL completes under the deadline.
- Empty-session test: no tasks / no actions → capsule absent or `_empty`, never
  fabricated.

## Open implementation questions (for writing-plans)

- Exact handoff-note storage mechanism and write ergonomics (so the agent
  actually updates it without friction).
- Whether `git_state` enumerates a fixed active-repo list or derives it from the
  session's touched files.
- Index/tail strategy for the ledger reads (byte-offset index vs reverse read).

---

## Appendix A — Adversarial panel verdict (2026-06-19)

Four parallel adversarial reviewers (security/opsec, latency/blocking,
signal-fidelity, ops/failure-mode). Convergent killers that shaped this design:

- **Async distilled capsule lands never.** Post-compact SessionStart fires within
  seconds; a worker panel takes 30–60s+. No wired hook re-checks for the artifact;
  the Brick session-start hook `exit(0)`s on `source==compact`. The artifact rots.
- **Judgment panel is signal-starved + self-canceling.** Workers see tool
  metadata but no tool *results*, so drift/concern/priority are guesses from exit
  codes. The "labeled unverified" tag is self-defeating: our CLAUDE.md trains the
  resumed agent to ignore unverified hints. 3 of 4 lenses said cut most of it.
- **"Safe by construction" sanitization is false.** Message text leaks: assistant
  prose mirrors secrets it just read; `tool_use.input` carries `Write` contents
  and `secret-tool` args; the 80-char command prefix catches `KEY=… cmd` and
  `curl -H "Bearer …"`; system-reminders carry JIDs/phones/hostnames/email.
  Regex scrub misses low-entropy structured secrets. Feeding external workers
  safely needs exactly the heavy redaction we cut for latency.
- **Ops debt:** silent producer rot, cross-repo import coupling, no rollback /
  parity test, unbounded JSONL read on the hot path.

## Appendix B — v2 revisit criteria (external worker distillation)

Reconsider the external-model panel only when ALL hold:

1. A **fail-closed** sanitizer exists: structural drop of `tool_result` AND
   `tool_use.input`; non-`user`/`assistant` roles dropped; command prefix scrubbed
   *before* truncation; environment denylist (phones, JIDs, `/home/q` paths, host
   labels, user email) on top of entropy scrub. User/assistant text is NOT safe by
   construction.
2. A real **injection path**: the artifact is consumed at the *next organic*
   SessionStart (cwd + session match), not the immediate post-compact one — with a
   per-session lock to prevent fork-storm and atomic temp-then-rename writes.
3. A **measurement harness**: the resumed agent logs which capsule fields it acted
   on; after N sessions we can show the panel beats the agent-authored handoff note.
4. Per-provider **no-train / retention** confirmation, plus a prompt-injection
   guard on staged content.

Until then, v1's agent-authored handoff note is the trusted, zero-leak,
zero-latency substitute.
