#!/usr/bin/env python3
"""PostToolUse(Agent) enrichment spool hook.

Non-blocking — writes qualifying Agent outputs to the spool.
Qualifying: output > 4K tokens (~16K chars) OR failed status.
"""
import importlib.util
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hook_utils import read_hook_input, run_fail_open
from brick_circuit import CircuitBreaker
try:
    from brick_metrics import log_enrichment
except ImportError:
    log_enrichment = None  # type: ignore

# Import from hyphenated filename via importlib
_bash_hook_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "enrich-posttool-bash.py")
_spec = importlib.util.spec_from_file_location("enrich_posttool_bash", _bash_hook_path)
_bash_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bash_mod)

should_spool_agent = _bash_mod.should_spool_agent
write_spool_entry = _bash_mod.write_spool_entry
_extract_output = _bash_mod._extract_output
_SPOOL_ROOT = _bash_mod._SPOOL_ROOT

_HOOK_NAME = "enrich-posttool-agent"
_EVENT_NAME = "PostToolUse"


def _is_failed(tool_response: dict | str | None) -> bool:
    """Check if the Agent response indicates failure."""
    if not isinstance(tool_response, dict):
        return False
    if tool_response.get("status") == "error":
        return True
    if tool_response.get("isError", False):
        return True
    return False


def main() -> None:
    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    if tool_name != "Agent":
        sys.exit(0)

    session_id = input_data.get("session_id", "")
    cb = CircuitBreaker()
    if not cb.allow_request():
        if log_enrichment:
            log_enrichment("agent", session_id, "Agent", action="skipped", reason="circuit_open")
        sys.exit(0)

    tool_response = input_data.get("tool_response")
    output = _extract_output(tool_response)
    failed = _is_failed(tool_response)

    if not output and not failed:
        sys.exit(0)

    if not should_spool_agent(output or "", failed):
        if log_enrichment:
            log_enrichment("agent", session_id, "Agent", action="skipped", reason="below_threshold")
        sys.exit(0)

    trace_id = str(uuid.uuid4())

    write_spool_entry(_SPOOL_ROOT, "Agent", output or "", session_id, trace_id)
    if log_enrichment:
        log_enrichment("agent", session_id, "Agent", action="spool", trace_id=trace_id)
    sys.exit(0)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
