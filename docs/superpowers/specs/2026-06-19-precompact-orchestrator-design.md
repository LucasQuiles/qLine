# PreCompact Orchestrator + Deterministic Capsule — v1 Design

**Date:** 2026-06-19
**Status:** Design approved (v1 scope); external-worker distillation deferred to v2
**Repos touched:** qLine (producer scripts, primary), bricklab (producer module).
**Hook registration lives in global `~/.claude/settings.json`** — not in either
repo's `.claude/`. See Rollout for the blast-radius consequence.

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

*(ops HIGH — the three PreCompact hooks are registered in the **global**
`~/.claude/settings.json` `PreCompact` array, lines ~323–343, not in qLine's or
bricklab's repo-scoped `.claude/`. Registration is therefore machine-wide: it
fires on **every** Claude Code compaction on this host, across all projects, not
just qLine sessions. Two consequences: (a) the env-flag gate carries the full
safety burden — there is no repo scoping to fall back on; (b) deregistering edits
a shared global file, so the parity audit must cover non-qLine sessions too.)*

1. Land the orchestrator gated behind `PRECOMPACT_ORCHESTRATOR_ENABLED=1`. Unset →
   it exits 0 immediately. Register it in the same global `~/.claude/settings.json`
   `PreCompact` array.
2. Keep the legacy `precompact-preserve.py` registered **in parallel** during
   migration. Duplicate task/plan injection is idempotent and harmless.
3. Enable the orchestrator; audit ≥5 real compaction capsules via the SessionStart
   sentinel — including at least one compaction from a non-qLine project, since
   registration is global.
4. Only after clean audits, deregister the three legacy hooks from the global
   settings. Rollback = unset the env var; the legacy hooks resume.

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

## Appendix C — Codebase verification (2026-06-19)

Every load-bearing claim in this design was checked against the live code on the
q machine before approval. Results:

| Claim | Verified against | Result |
|---|---|---|
| Ledger read is unbounded full-file | `enrich-precompact.py:46` `_ACTION_LEDGER.read_text().splitlines()`; metrics same at `:63` | **TRUE.** File is **45.5 MB / 131,935 lines** — the latency CRIT is real, not hypothetical. Output is capped at `_MAX_CONTEXT_TOKENS*4` (`:242`) only *after* the full read. |
| Three PreCompact hooks registered | `~/.claude/settings.json` `PreCompact` array `:323–343` | **TRUE**, and registration is **global**, not per-repo (correction folded into Rollout). |
| Two separate fail-open wrappers | `enrich-precompact.py:21` imports `brick_hook_support.run_fail_open`; `precompact-preserve.py:13` imports `hook_utils.run_fail_open` | **TRUE.** |
| `preserve` injects open tasks **and** active plan | `precompact-preserve.py:30` `find_latest_plan()`, appended conditionally `:31–32` | **TRUE.** Plan line is conditional; absent in the last capsule only because no plan file existed then. |
| Post-compact SessionStart does not re-surface the brief (artifact rots) | `enrich-session-start.py:194` `if source == "compact": sys.exit(0)` | **TRUE, exactly as Appendix A states.** Confirms there is no existing consumer for a compact-time capsule — the SessionStart sentinel in this design is net-new wiring. |

No claim was refuted. The only correction was the registration location (global,
not repo-scoped), which strengthens rather than weakens the env-flag-gated rollout.

## Appendix D — Reuse-first rider alignment (design input for the plan)

A reuse-first runtime-hardening rider informs this work. The rider's literal
artifacts (`/Users/q/...` macOS paths, `AGENT_RUNTIME_STANDARD.md`,
`agent-runtime-probes/`, an `AGENT_MCP_ALLOWLIST.yaml`) **do not exist on this
host** — this is Linux `/home/q`, and a grounding check (2026-06-19) found all of
them MISSING. We therefore adopt the rider's **principles**, not its paths. The
plan and implementation MUST honor:

| Rider principle | How this design satisfies it (plan must preserve) |
|---|---|
| **Reuse first, not reuse only** | `preserve`/`git`/`failures`/`stats` producers wrap existing logic invoked as subprocesses; only `handoff` is a net-new primitive — and it closes a real gap (no compact-time capsule consumer exists; Appendix C row 5). |
| **One canonical event schema; receipts** | The capsule's `{_producers_ok, _producers_failed, _empty, _ms}` envelope IS the receipt. Plan: keep it a single, versioned schema; each producer emits the same shape. |
| **Shared classifiers, not per-producer logic** | Bounded-read + path/secret scrub live in ONE shared helper the producers call — not duplicated per producer. |
| **Shadow → warn → enforce; rollback** | `PRECOMPACT_ORCHESTRATOR_ENABLED=1` runs in parallel with legacy hooks; ≥5 clean audits (incl. ≥1 non-qLine compaction) before deregistering; rollback = unset flag. |
| **No raw secrets / no raw transcript persistence** | The handoff note is agent-authored, local-only, never staged to any external worker; the v2 external-panel deferral (Appendix B) keeps it that way until a fail-closed sanitizer exists. |
| **Measurable; experiment-gated** | Golden parity test + producer-failure + bounded-read + empty-session tests; the observability envelope makes producer rot visible (SessionStart alert to BOT PATCHES). |

**Rider Add-in 8 ("compaction state capsule") is this project** — same primitive,
already specced. The remaining rider add-ins (live inventory, MCP capability
ledger, OTel exporter, OPA bridge, etc.) are explicitly **out of scope** here; if
pursued they are separate specs, not folded into this one (rider §"decompose
first"). The plan does NOT introduce any `/Users/q` path or assume any rider
doctrine file exists.

## Appendix E — Rollout audit log (2026-06-19)

Tasks 1–7 implemented and committed on `spec/precompact-orchestrator`; full hooks
suite **91 passed**. Global registration (Task 8) executed with a consolidation
pass — conflicts, blast radius, regression points, and protections below.

**Consolidation finding (conflict).** The plan assumed all three legacy PreCompact
hooks lived in `PreCompact[0].hooks`. Live `settings.json` actually splits them
across **two** groups: `[0]` matcher `auto|manual` → `enrich-precompact.py`; `[1]`
no matcher → `obs-precompact.py`, `precompact-preserve.py`. Resolution: orchestrator
appended to `[0]` (fires on both triggers, matches the plan's `[0]` validation);
`[1]` left untouched.

**Pre-flight proof (empirical, before edit).**
- No-op / shadow: flag **unset** → both entrypoints exit 0 with **zero** stdout
  (orchestrator and sentinel) — exact current behavior preserved.
- Enabled path vs a **real** session (`42c66455…`, 2048 actions): exit 0,
  `_producers_ok=['preserve','failures','stats']`, `_producers_failed=[]`,
  `_empty=False`, **79 ms** (vs 10 s timeout). Injected capsule carried real open
  tasks, session stats, and a **generically-redacted** failure line (no secret leak).
- Sentinel vs that capsule: exit 0, no false rot alert.

**Blast radius.** Registration is global but scoped to the `q` user's `~/.claude`.
Per compaction: +1 fail-open subprocess fan-out (~79 ms measured). Per session
start: +1 capsule read (sentinel). Bounded by per-producer 3 s deadline,
`ThreadPoolExecutor`, and the 10 s/8 s hook timeouts.

**Regression points + protections.**
- JSON corruption → timestamped backup `~/.claude/settings.json.bak-precompact-*`
  + post-edit `json.load` assertion; legacy entries asserted intact.
- Hook crash → `run_fail_open` wrapper on both entrypoints.
- Latency → measured 79 ms; capped by timeouts.
- Secret leak → `_safe_preview` redaction verified live (generic `(failed tool)`).
- Schema guard → `validate-settings-schema.py` is forward-compatible + non-blocking.

**Phase: WARN.** `PRECOMPACT_ORCHESTRATOR_ENABLED=1` set in `settings.json` `env`;
orchestrator now runs in **parallel** with the three legacy hooks for new sessions.
Rollback = remove that env line (→ shadow) or restore the backup.

**Step 8 (deregister legacy) — DONE (enforce).** Gate audit ran the exact
orchestrator PreCompact code path against 5 real sessions spanning 4 distinct
projects; all clean. Legacy `enrich-precompact.py` (the 45 MB latency-CRIT reader)
and `precompact-preserve.py` (superseded by the `preserve` producer) deregistered;
`obs-precompact.py` retained (pure telemetry, no injection overlap). Orchestrator is
now the sole PreCompact injector. Sentinel active on SessionStart.

| # | Project (cwd) | Trigger | `_producers_ok` | `_producers_failed` | `_empty` | Verdict |
|---|---------------|---------|-----------------|---------------------|----------|---------|
| 1 | `/home/q/agents/q` | auto | failures | — | False | ✅ clean |
| 2 | `/home/q/agents/q` | auto | preserve,failures,stats | — | False | ✅ clean |
| 3 | `/home/q` | auto | stats | — | False | ✅ clean |
| 4 | `/home/q/LAB/Loops` | auto | failures | — | False | ✅ clean |
| 5 | `/home/q/agents/q/docs/sdlc/active` | auto | failures | — | False | ✅ clean |

Worst-case latency observed 79 ms (budget 10 s). Forwarder run post-audit: only
payload was the synthetic empty-session capsule from the pre-flight no-op test
(offset advanced; never sent to BOT PATCHES).

**Post-enforce rollback.** Legacy is no longer registered, so `unset
PRECOMPACT_ORCHESTRATOR_ENABLED` alone leaves only `obs-precompact` telemetry (no
injection). Full rollback = restore `~/.claude/settings.json.bak-precompact-1781910083`
(re-adds the three legacy hooks) **and** unset the flag.

**Note — stale trailer convention.** The operating convention "qLine commits use a
`Co-Authored-By: Claude Opus 4.8 (1M context)` trailer" conflicts with the
fleet-wide W28 pre-push hook (`REM/git-hooks/pre-push`), which blocks all AI
`Co-Authored-By` trailers on push to any remote. The 20 unpushed rollout commits
were rewritten to strip the trailer (local-only history; trees byte-identical),
then pushed clean. The convention is not codified in any qLine repo file, so the
durable fix is to stop emitting the trailer on qLine commits. Candidate BOT PATCHES
escalation: the global trailer convention should be reconciled with the W28 policy
fleet-wide so the contradiction stops recurring.
