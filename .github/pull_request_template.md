## Summary

Describe the behavior changed and why.

## Verification

- [ ] I ran `python3 scripts/verify.py doctor`.
- [ ] I ran the unmasked canonical gate: `python3 scripts/verify.py run`.
- [ ] I recorded the real exit status and did not treat a skipped, timed-out,
      masked, or blocked result as a pass.
- [ ] I reviewed [docs/VERIFICATION.md](../docs/VERIFICATION.md) for the relevant
      `QLV-*` diagnostics and remediation guidance.
- [ ] I updated tests and documentation for behavior or contract changes.
- [ ] I documented any change to filesystem, network, destructive, or
      idempotency effects.

Paste a concise result summary. Do not attach private full-log directories
without reviewing them for paths, environment details, and session-derived data.
