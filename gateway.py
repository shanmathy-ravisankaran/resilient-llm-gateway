"""Core gateway layer for resilient LLM calls."""

from typing import Callable

from tenacity import (
    RetryCallState,
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from circuit_breaker import (
    CircuitOpenError,
    is_circuit_open,
    record_failure,
    record_success,
)
from config import load_config
from providers import call_provider_a, call_provider_b


PROVIDER_FUNCTIONS: dict[str, Callable[[str], object]] = {
    "A": call_provider_a,
    "B": call_provider_b,
}


def _log_wait_before_retry(provider_name: str) -> Callable[[RetryCallState], None]:
    """Return a Tenacity callback that logs the wait before the next retry."""

    def _callback(retry_state: RetryCallState) -> None:
        wait_time = 0.0
        if retry_state.next_action is not None:
            wait_time = retry_state.next_action.sleep

        next_attempt = retry_state.attempt_number + 1
        print(
            f"Provider {provider_name} attempt {retry_state.attempt_number} failed. "
            f"Retrying in {wait_time:.0f}s before attempt {next_attempt}.",
            flush=True,
        )

    return _callback


def _call_provider(
    provider_name: str,
    provider_func: Callable[[str], object],
    prompt: str,
    attempt_state: dict,
) -> str:
    """Call one provider once and record/log the attempt outcome."""
    if is_circuit_open(provider_name):
        raise CircuitOpenError(
            f"Provider {provider_name} circuit is open; skipping provider call."
        )

    attempt_state["total_attempts"] += 1
    attempt_state["provider_attempts"][provider_name] += 1

    provider_attempt = attempt_state["provider_attempts"][provider_name]
    print(f"Provider {provider_name} attempt {provider_attempt}: starting.", flush=True)

    try:
        provider_response = provider_func(prompt)
    except Exception as exc:
        failed_cost = getattr(exc, "cost_usd", 0.0)
        attempt_state["total_cost_usd"] += failed_cost
        record_failure(provider_name)
        print(
            f"Provider {provider_name} attempt {provider_attempt}: failed ({exc}).",
            flush=True,
        )
        if is_circuit_open(provider_name):
            raise CircuitOpenError(
                f"Provider {provider_name} circuit opened after consecutive failures."
            ) from exc
        raise

    response_cost = getattr(provider_response, "cost_usd", 0.0)
    attempt_state["total_cost_usd"] += response_cost
    record_success(provider_name)
    response_text = getattr(provider_response, "text", str(provider_response))

    print(
        f"Provider {provider_name} attempt {provider_attempt}: success "
        f"(cost ${response_cost:.8f}).",
        flush=True,
    )
    return response_text


def _get_provider_function(provider_name: str) -> Callable[[str], object]:
    """Return the provider function configured for a provider name."""
    try:
        return PROVIDER_FUNCTIONS[provider_name]
    except KeyError as exc:
        raise ValueError(f"Unknown provider '{provider_name}'. Expected 'A' or 'B'.") from exc


def _call_provider_with_retries(
    provider_name: str,
    prompt: str,
    attempt_state: dict,
    retry_config: dict,
) -> str:
    """Build a Tenacity retry wrapper from config and call one provider.

    The YAML config flows through load_config() into retry_config. Those values
    are used here to build Tenacity's retry decorator dynamically:
    stop_after_attempt(max_attempts_per_provider) controls the total real calls,
    and wait_exponential(multiplier=base_delay_seconds,
    exp_base=backoff_multiplier) controls the delay before each retry. Circuit
    breaker skips use CircuitOpenError, which Tenacity is configured not to
    retry, so open circuits fail fast instead of sleeping.
    """
    if is_circuit_open(provider_name):
        raise CircuitOpenError(
            f"Provider {provider_name} circuit is open; skipping retry attempts."
        )

    provider_func = _get_provider_function(provider_name)
    max_attempts = retry_config["max_attempts_per_provider"]
    base_delay = retry_config["base_delay_seconds"]
    backoff_multiplier = retry_config["backoff_multiplier"]

    retry_decorator = retry(
        retry=retry_if_not_exception_type(CircuitOpenError),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=base_delay, exp_base=backoff_multiplier),
        before_sleep=_log_wait_before_retry(provider_name),
        reraise=True,
    )

    @retry_decorator
    def _decorated_call() -> str:
        return _call_provider(provider_name, provider_func, prompt, attempt_state)

    return _decorated_call()


def call_with_resilience(prompt: str) -> dict:
    """Call the configured primary provider, then fail over if configured.

    stop_after_attempt counts total calls, not retries after the first call.
    With max_attempts_per_provider set to 3, each provider gets three real
    calls total. With the default config, that means attempt 1 immediately,
    attempt 2 after a 1s wait, and attempt 3 after a 2s wait.

    The failover logic sits one level above the retry decorators and the
    circuit breaker sits one level above that. If a configured provider's
    circuit is open, it is skipped before any retry attempts are created. If it
    is allowed through, each real attempt contributes any known token cost to
    total_cost_usd.
    """
    config = load_config()
    primary_provider = config["providers"]["primary"]
    backup_provider = config["providers"]["backup"]
    failover_enabled = config["failover"]["enabled"]
    retry_config = config["retry"]

    attempt_state = {
        "total_attempts": 0,
        "provider_attempts": {"A": 0, "B": 0},
        "total_cost_usd": 0.0,
    }
    primary_error_message = ""

    if is_circuit_open(primary_provider):
        primary_error_message = (
            f"Provider {primary_provider} circuit is open; skipping primary provider."
        )
        print(primary_error_message, flush=True)
    else:
        try:
            response = _call_provider_with_retries(
                primary_provider,
                prompt,
                attempt_state,
                retry_config,
            )
            return {
                "response": response,
                "provider_used": primary_provider,
                "attempts": attempt_state["total_attempts"],
                "failed_over": False,
                "total_cost_usd": round(attempt_state["total_cost_usd"], 10),
            }
        except Exception as primary_error:
            primary_error_message = str(primary_error)
            print(
                f"Provider {primary_provider} exhausted all retries: "
                f"{primary_error_message}",
                flush=True,
            )

    if not failover_enabled:
        raise RuntimeError(
            "Primary provider failed after all retry attempts, and failover is "
            f"disabled. Provider {primary_provider} final error: "
            f"{primary_error_message}."
        )

    if backup_provider == primary_provider:
        raise RuntimeError(
            "Primary provider failed after all retry attempts, and backup "
            f"provider is also configured as {primary_provider}. Final error: "
            f"{primary_error_message}."
        )

    print(f"Failing over to Provider {backup_provider}.", flush=True)

    if is_circuit_open(backup_provider):
        raise RuntimeError(
            "Primary provider failed and backup provider was skipped because "
            f"its circuit is open. Provider {primary_provider} final error: "
            f"{primary_error_message}. Provider {backup_provider} circuit is open."
        )

    try:
        response = _call_provider_with_retries(
            backup_provider,
            prompt,
            attempt_state,
            retry_config,
        )
        return {
            "response": response,
            "provider_used": backup_provider,
            "attempts": attempt_state["total_attempts"],
            "failed_over": True,
            "total_cost_usd": round(attempt_state["total_cost_usd"], 10),
        }
    except Exception as backup_error:
        raise RuntimeError(
            "Both providers failed after all retry attempts. "
            f"Provider {primary_provider} final error: {primary_error_message}. "
            f"Provider {backup_provider} final error: {backup_error}."
        ) from backup_error
