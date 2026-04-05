"""Tests for brick_circuit.CircuitBreaker state machine.

State machine:
  CLOSED -> (3 failures in 60s) -> DEGRADED -> (3 more) -> OPEN -> (120s cooldown) -> HALF_OPEN
  HALF_OPEN + success -> CLOSED
  HALF_OPEN + failure -> OPEN
  Success in CLOSED/DEGRADED resets counters -> CLOSED
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from brick_circuit import CircuitBreaker, CircuitState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def state_file(tmp_path):
    return str(tmp_path / "circuit-breaker.json")


@pytest.fixture
def cb(state_file):
    return CircuitBreaker(state_file=state_file)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_starts_closed(cb):
    """Fresh breaker starts in CLOSED state."""
    assert cb.state == CircuitState.CLOSED


def test_degrades_after_3_failures(cb):
    """3 failures within the window transitions CLOSED -> DEGRADED."""
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitState.DEGRADED


def test_opens_after_6_total_failures(cb):
    """3 more failures in DEGRADED transitions to OPEN."""
    for _ in range(6):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN


def test_cooldown_to_half_open(state_file):
    """After cooldown period, OPEN transitions to HALF_OPEN on state read."""
    cb = CircuitBreaker(state_file=state_file)
    # Force into OPEN
    for _ in range(6):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # Backdate opened_at to simulate cooldown elapsed
    with open(state_file) as f:
        data = json.load(f)
    data["opened_at"] = time.time() - 200  # well past 120s cooldown
    with open(state_file, "w") as f:
        json.dump(data, f)

    cb2 = CircuitBreaker(state_file=state_file)
    assert cb2.state == CircuitState.HALF_OPEN


def test_success_closes_from_half_open(state_file):
    """A single success in HALF_OPEN transitions to CLOSED."""
    cb = CircuitBreaker(state_file=state_file)
    for _ in range(6):
        cb.record_failure()

    # Backdate opened_at
    with open(state_file) as f:
        data = json.load(f)
    data["opened_at"] = time.time() - 200
    with open(state_file, "w") as f:
        json.dump(data, f)

    cb2 = CircuitBreaker(state_file=state_file)
    assert cb2.state == CircuitState.HALF_OPEN

    cb2.record_success()
    assert cb2.state == CircuitState.CLOSED


def test_failure_reopens_from_half_open(state_file):
    """A single failure in HALF_OPEN transitions back to OPEN."""
    cb = CircuitBreaker(state_file=state_file)
    for _ in range(6):
        cb.record_failure()

    with open(state_file) as f:
        data = json.load(f)
    data["opened_at"] = time.time() - 200
    with open(state_file, "w") as f:
        json.dump(data, f)

    cb2 = CircuitBreaker(state_file=state_file)
    assert cb2.state == CircuitState.HALF_OPEN

    cb2.record_failure()
    assert cb2.state == CircuitState.OPEN


def test_success_resets_failure_count(cb):
    """Success in CLOSED/DEGRADED resets failure counters to CLOSED."""
    cb.record_failure()
    cb.record_failure()
    # 2 failures — still CLOSED
    assert cb.state == CircuitState.CLOSED
    cb.record_success()
    # Counter reset — need 3 more to degrade
    for _ in range(2):
        cb.record_failure()
    assert cb.state == CircuitState.CLOSED


def test_success_resets_from_degraded(cb):
    """Success in DEGRADED resets counters and returns to CLOSED."""
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitState.DEGRADED
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_state_persists_to_file(state_file):
    """State survives across instances via the state file."""
    cb1 = CircuitBreaker(state_file=state_file)
    for _ in range(3):
        cb1.record_failure()
    assert cb1.state == CircuitState.DEGRADED

    cb2 = CircuitBreaker(state_file=state_file)
    assert cb2.state == CircuitState.DEGRADED


def test_allow_request_false_when_open(cb):
    """allow_request() returns False only when OPEN."""
    assert cb.allow_request() is True
    for _ in range(6):
        cb.record_failure()
    assert cb.allow_request() is False


def test_is_degraded_true_when_degraded(cb):
    """is_degraded() returns True only when DEGRADED."""
    assert cb.is_degraded() is False
    for _ in range(3):
        cb.record_failure()
    assert cb.is_degraded() is True


def test_old_failures_outside_window_ignored(state_file):
    """Failures older than _FAILURE_WINDOW_S are pruned and don't count."""
    cb = CircuitBreaker(state_file=state_file)
    cb.record_failure()
    cb.record_failure()

    # Backdate the failure timestamps beyond the 60s window
    with open(state_file) as f:
        data = json.load(f)
    data["failure_timestamps"] = [time.time() - 120, time.time() - 120]
    with open(state_file, "w") as f:
        json.dump(data, f)

    cb2 = CircuitBreaker(state_file=state_file)
    cb2.record_failure()
    # Only 1 recent failure — should still be CLOSED
    assert cb2.state == CircuitState.CLOSED


def test_creates_parent_dirs(tmp_path):
    """Constructor creates parent directories if they don't exist."""
    deep = str(tmp_path / "a" / "b" / "c" / "state.json")
    cb = CircuitBreaker(state_file=deep)
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert os.path.exists(deep)
