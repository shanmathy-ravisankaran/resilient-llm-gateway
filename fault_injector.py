"""Controllable failure simulation for gateway testing.

This is a deliberate fault-injection / chaos-testing pattern. It lets the
project validate retry and failover behavior without depending on real API
rate limits, timeouts, or outages, which are unpredictable and expensive to
trigger on demand.
"""


class SimulatedRateLimitError(Exception):
    """Raised when a configured provider should simulate a rate limit."""


_fault_counts: dict[str, int] = {}


def _normalize_provider(provider: str) -> str:
    """Normalize and validate a provider name."""
    normalized = provider.upper()
    if normalized not in {"A", "B"}:
        raise ValueError("provider must be 'A' or 'B'.")
    return normalized


def inject_fault(provider: str, fail_count: int) -> None:
    """Configure a provider to fail on its next fail_count calls."""
    normalized = _normalize_provider(provider)

    if fail_count < 0:
        raise ValueError("fail_count must be zero or greater.")

    if fail_count == 0:
        _fault_counts.pop(normalized, None)
        return

    _fault_counts[normalized] = fail_count


def maybe_fail(provider: str) -> None:
    """Raise a simulated rate-limit error if the provider is configured to fail."""
    normalized = _normalize_provider(provider)
    remaining_failures = _fault_counts.get(normalized, 0)

    if remaining_failures <= 0:
        return

    _fault_counts[normalized] = remaining_failures - 1
    raise SimulatedRateLimitError("Simulated rate limit exceeded for testing")


def reset_faults() -> None:
    """Clear all injected provider fault state."""
    _fault_counts.clear()
