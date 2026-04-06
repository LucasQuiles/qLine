#!/usr/bin/env python3
"""Brick circuit breaker auto-heal probe (P8a).

Runs periodically via systemd timer. When the circuit breaker is not CLOSED,
probes the Brick health endpoint and records success/failure to nudge the
state machine toward recovery.
"""
import json
import ssl
import subprocess
import sys
import urllib.request

# Add hooks directory for brick_circuit / brick_metrics imports
sys.path.insert(0, "/home/q/.claude/hooks")

from brick_circuit import CircuitBreaker, CircuitState
from brick_metrics import log_enrichment

HEALTH_URL = "https://brick.tail64ad01.ts.net:8443/health"
CB_STATE_FILE = "/tmp/brick-lab/circuit-breaker.json"
TIMEOUT_S = 10


def get_api_key() -> str:
    result = subprocess.run(
        ["secret-tool", "lookup", "service", "brick-api-key"],
        capture_output=True, text=True, timeout=5,
    )
    return result.stdout.strip()


def probe_health(api_key: str) -> tuple[bool, str]:
    """Hit the Brick health endpoint. Returns (ok, detail)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(
        HEALTH_URL,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=ctx) as resp:
            if resp.status == 200:
                return True, f"HTTP {resp.status}"
            return False, f"HTTP {resp.status}"
    except Exception as e:
        return False, str(e)


def main() -> None:
    cb = CircuitBreaker(state_file=CB_STATE_FILE)
    state = cb.state

    if state == CircuitState.CLOSED:
        # Nothing to heal
        return

    api_key = get_api_key()
    if not api_key:
        print("brick_cb_probe: could not retrieve API key", file=sys.stderr)
        return

    ok, detail = probe_health(api_key)
    prev_state = state.value

    if ok:
        cb.record_success()
        new_state = cb.state.value
        log_enrichment(
            hook="probe",
            session_id="",
            tool_name="brick_cb_probe",
            action="healed",
            reason=f"{prev_state} -> {new_state} (health OK: {detail})",
        )
        print(f"brick_cb_probe: healed {prev_state} -> {new_state}")
    else:
        cb.record_failure()
        new_state = cb.state.value
        log_enrichment(
            hook="probe",
            session_id="",
            tool_name="brick_cb_probe",
            action="failed",
            reason=f"{prev_state} -> {new_state} (health fail: {detail})",
        )
        print(f"brick_cb_probe: failed {prev_state} -> {new_state} ({detail})")


if __name__ == "__main__":
    main()
