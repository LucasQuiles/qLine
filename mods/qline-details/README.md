# qLine details mod

This optional plugin opens a qLine metrics pane with `/qline`. Press **r** to
reload the recorded values and **q** or **Esc** to close the pane. It uses no
model request and does not run collectors. The ordinary qLine status line stays
in place.

From the qLine repository, start an isolated trial:

```sh
claude --plugin-dir ./mods/qline-details
```

This loads the plugin for that process; it does not install it. Start the next
session without `--plugin-dir` to leave it unloaded. If another component owns
`/qline`, this mod skips registration and leaves that component's command intact.

The pane displays the current session's latest valid qLine snapshot: model,
project, cost, context, token counts, duration, and the time the snapshot was
recorded. Age is measured when Refresh is pressed, not continuously. Missing
values remain unavailable. A damaged final record is reported rather than
presented as current data.

## Existing data contract

The mod reads `OBS_ROOT/runtime/<session_id>.json`, using
`~/.claude/observability` when `OBS_ROOT` is unset. Its `package_root` identifies
`native/statusline/snapshots.jsonl`, written by qLine's existing renderer. It
reads only on command or Refresh, and does not scan session directories, read
transcripts, write files, spawn processes, or change tool permissions.

Claude Code limits each `fs.read` to 4 MiB. An oversized or unreadable file
produces an unavailable-data message; the status line remains the fallback.
This pilot does not change snapshot retention or introduce a second collector.

## Verification

Tested with Claude Code **2.1.302**. Other releases and graphical clients are
unqualified. The terminal trial covers opening, refreshing, and closing a pane
with a known snapshot; it does not establish a performance improvement.

```sh
claude plugin validate ./mods/qline-details --strict
claude plugin test ./mods/qline-details
tsc --noEmit -p ./mods/qline-details
```

The type check requires the declarations Claude Code generates on the first
interactive `--plugin-dir` load. Generated declarations are ignored by Git;
they must match the runtime being tested. No additional runtime package is
required.

Tests cover recorded values and age, refresh, close, incomplete records,
another session's data, read refusal, session transitions, command collisions,
unknown metrics, and clock skew. The native test kit checks the element tree;
a terminal trial also checks that the controls actually render and respond.

Keep this pilot optional. Its demonstrated benefit is on-demand inspection of
existing metrics. Compare any future optimization against qLine's installed
throttle and current refresh cadence, including total collector and renderer
cost. No latency, token, or disk-I/O saving is claimed here.

API references: [mod creation](https://code.claude.com/docs/en/plugins/mods/create),
[interface](https://code.claude.com/docs/en/plugins/mods/interface), and
[tests](https://code.claude.com/docs/en/plugins/mods/test). Generated declarations
take precedence when the installed release differs from these pages.
