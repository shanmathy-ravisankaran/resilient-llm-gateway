"""Simple in-memory circuit breaker for provider health.

The breaker prevents repeated wasted calls to a provider that is already
failing. After enough consecutive failures, the circuit opens and future calls
are skipped until a cooldown expires. The next call after cooldown is a
half-open trial: success closes the circuit, failure reopens it.
"""

from time import monotonic
from typing import Any


FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 30

_circuit_state: dict[str, dict[str, Any]] = {}


class CircuitOpenError(RuntimeError):
    """Raised when a provider call is skipped because its circuit is open."""


def _normalize_provider(provider: str) -> str:
    """Normalize and validate a provider name."""
    normalized = provider.upper()
    if normalized not in {"A", "B"}:
        raise ValueError("provider must be 'A' or 'B'.")
    return normalized


def _get_state(provider: str) -> dict[str, Any]:
    """Return mutable circuit state for one provider."""
    normalized = _normalize_provider(provider)
    return _circuit_state.setdefault(
        normalized,
        {
            "state": "closed",
            "consecutive_failures": 0,
            "opened_until": 0.0,
        },
    )


def is_circuit_open(provider: str) -> bool:
    """Return True when calls to provider should be skipped."""
    state = _get_state(provider)

    if state["state"] != "open":
        return False

    if monotonic() < state["opened_until"]:
        return True

    # Cooldown expired: allow one trial call through in half-open state.
    state["state"] = "half_open"
    return False


def record_success(provider: str) -> None:
    """Close the circuit and clear failures after a successful provider call."""
    state = _get_state(provider)
    state["state"] = "closed"
    state["consecutive_failures"] = 0
    state["opened_until"] = 0.0


def record_failure(provider: str) -> None:
    """Record a failed call and open/reopen the circuit when needed."""
    state = _get_state(provider)

    if state["state"] == "half_open":
        state["state"] = "open"
        state["consecutive_failures"] = FAILURE_THRESHOLD
        state["opened_until"] = monotonic() + COOLDOWN_SECONDS
        return

    state["consecutive_failures"] += 1

    if state["consecutive_failures"] >= FAILURE_THRESHOLD:
        state["state"] = "open"
        state["opened_until"] = monotonic() + COOLDOWN_SECONDS


def reset_circuits() -> None:
    """Clear all circuit breaker state, useful for local tests."""
    _circuit_state.clear()
