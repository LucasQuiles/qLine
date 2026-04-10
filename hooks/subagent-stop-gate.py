#!/usr/bin/env python3
"""SubagentStop handoff hook (warn-first): checks handoff quality from subagents.

Logs a warning to stderr when a subagent completes without a meaningful handoff
summary in last_assistant_message. Exempts read-only explorers.

Payload shape (verified from fixtures):
    session_id, transcript_path, cwd, permission_mode, agent_id, agent_type,
    hook_event_name, stop_hook_active, agent_transcript_path, last_assistant_message
"""
import json
import os
import sys

from hook_utils import read_hook_input, is_strict, block_stop, log_hook_diagnostic, run_fail_open

# Agent types exempt from handoff quality checks (read-only by nature)
EXEMPT_AGENT_TYPES = [
    "Explore",
    "Plan",
    "claude-code-guide",
    "feature-dev:code-explorer",
    "feature-dev:code-architect",
    "episodic-memory:search-conversations",
    "superpowers-chrome:browser-user",
]

# Minimum meaningful message length (characters)
MIN_MESSAGE_LENGTH = 50

# Signals that suggest a meaningful handoff
HANDOFF_SIGNALS = [
    "summary", "result", "complete", "implemented", "created",
    "modified", "changed", "fixed", "added", "updated",
    "file", "test", "error", "failed", "blocked",
]


def main():
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    agent_type = str(input_data.get("agent_type") or "")
    agent_id = str(input_data.get("agent_id") or "?")
    last_message = str(input_data.get("last_assistant_message") or "")

    # Exempt read-only/explorer agents
    if any(exempt in agent_type for exempt in EXEMPT_AGENT_TYPES):
        sys.exit(0)

    strict = is_strict("CLAUDE_SUBAGENT_STOP_STRICT")

    # Check handoff quality
    if not last_message or len(last_message) < MIN_MESSAGE_LENGTH:
        msg = (
            f"[subagent-stop-gate] Agent {agent_id} ({agent_type}) "
            f"completed with minimal handoff message "
            f"({len(last_message or '')} chars). "
            f"Consider requesting a summary of changes and outcomes."
        )
        log_hook_diagnostic(
            "subagent-stop-gate", "SubagentStop",
            "minimal_handoff", msg,
            level="warning",
            context={"agent_id": agent_id, "agent_type": agent_type,
                     "message_length": len(last_message or "")},
        )
        if strict:
            block_stop(msg)
        else:
            log_hook_diagnostic(
                "subagent-stop-gate", "SubagentStop",
                "minimal_handoff_warn", msg,
                level="warning",
            )
        sys.exit(0)

    # Check for meaningful content signals
    msg_lower = last_message.lower()
    has_signals = any(s in msg_lower for s in HANDOFF_SIGNALS)

    if not has_signals:
        msg = (
            f"[subagent-stop-gate] Agent {agent_id} ({agent_type}) "
            f"handoff message lacks outcome signals (files changed, results, etc.)."
        )
        log_hook_diagnostic(
            "subagent-stop-gate", "SubagentStop",
            "no_outcome_signals", msg,
            level="warning",
            context={"agent_id": agent_id, "agent_type": agent_type},
        )
        if strict:
            block_stop(msg)
        else:
            log_hook_diagnostic(
                "subagent-stop-gate", "SubagentStop",
                "no_signals_warn", msg,
                level="warning",
            )

    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, "subagent-stop-gate", "SubagentStop")
