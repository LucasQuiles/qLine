"""Brick circuit breaker — state machine with file-backed persistence.

State machine:
  CLOSED -> (3 failures in 60s) -> DEGRADED -> (3 more) -> OPEN
  OPEN -> (120s cooldown) -> HALF_OPEN
  HALF_OPEN + 1 success -> CLOSED
  HALF_OPEN + 1 failure -> OPEN
  Success in CLOSED/DEGRADED resets counters -> CLOSED
"""
import json
import os
import tempfile
import time
from enum import Enum
from typing import Any


class CircuitState(str, Enum):
    CLOSED = "closed"
    DEGRADED = "degraded"
    OPEN = "open"
    HALF_OPEN = "half_open"


_FAILURE_WINDOW_S = 60
_FAILURES_TO_DEGRADE = 3
_FAILURES_TO_OPEN = 3  # 3 more after DEGRADED (6 total)
_COOLDOWN_S = 120

class CircuitBreaker:
    """Circuit breaker for Brick enrichment pipeline.

    Persists state to a JSON file using atomic write (temp + rename).
    """

    def __init__(self, state_file: str = "/tmp/brick-lab/circuit-breaker.json"):
        self._state_file = state_file
        os.makedirs(os.path.dirname(state_file), exist_ok=True)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        try:
            with open(self._state_file) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            return {
                "state": CircuitState.CLOSED.value,
                "failure_timestamps": [],
                "opened_at": None,
            }

    def _write(self, data: dict[str, Any]) -> None:
        parent = os.path.dirname(self._state_file)
        fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self._state_file)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # State property — handles OPEN->HALF_OPEN cooldown check
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        data = self._read()
        current = CircuitState(data.get("state", CircuitState.CLOSED.value))

        if current == CircuitState.OPEN:
            opened_at = data.get("opened_at")
            if opened_at is not None and (time.time() - opened_at) >= _COOLDOWN_S:
                data["state"] = CircuitState.HALF_OPEN.value
                self._write(data)
                return CircuitState.HALF_OPEN

        return current

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def allow_request(self) -> bool:
        """False only when OPEN."""
        return self.state != CircuitState.OPEN

    def is_degraded(self) -> bool:
        return self.state == CircuitState.DEGRADED

    def record_success(self) -> None:
        data = self._read()
        current = CircuitState(data.get("state", CircuitState.CLOSED.value))

        if current == CircuitState.HALF_OPEN:
            # Probe succeeded — close the circuit
            data["state"] = CircuitState.CLOSED.value
            data["failure_timestamps"] = []
            data["opened_at"] = None
            self._write(data)
        elif current in (CircuitState.CLOSED, CircuitState.DEGRADED):
            # Reset counters, return to CLOSED
            data["state"] = CircuitState.CLOSED.value
            data["failure_timestamps"] = []
            self._write(data)

    def record_failure(self) -> None:
        data = self._read()
        current = CircuitState(data.get("state", CircuitState.CLOSED.value))

        # Handle OPEN->HALF_OPEN transition before processing failure
        if current == CircuitState.OPEN:
            opened_at = data.get("opened_at")
            if opened_at is not None and (time.time() - opened_at) >= _COOLDOWN_S:
                current = CircuitState.HALF_OPEN
                data["state"] = CircuitState.HALF_OPEN.value

        if current == CircuitState.HALF_OPEN:
            # Single failure in HALF_OPEN -> OPEN
            data["state"] = CircuitState.OPEN.value
            data["opened_at"] = time.time()
            data["failure_timestamps"] = []
            self._write(data)
            return

        now = time.time()
        timestamps = data.get("failure_timestamps", [])
        timestamps.append(now)

        # Prune failures outside the window
        cutoff = now - _FAILURE_WINDOW_S
        timestamps = [t for t in timestamps if t >= cutoff]
        data["failure_timestamps"] = timestamps

        recent_count = len(timestamps)

        if current == CircuitState.CLOSED:
            if recent_count >= _FAILURES_TO_DEGRADE:
                data["state"] = CircuitState.DEGRADED.value
        elif current == CircuitState.DEGRADED:
            # Total failures needed: _FAILURES_TO_DEGRADE + _FAILURES_TO_OPEN
            if recent_count >= (_FAILURES_TO_DEGRADE + _FAILURES_TO_OPEN):
                data["state"] = CircuitState.OPEN.value
                data["opened_at"] = time.time()
                data["failure_timestamps"] = []

        self._write(data)
