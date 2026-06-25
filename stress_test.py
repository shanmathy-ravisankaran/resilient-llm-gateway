"""Stress test runner for the resilient LLM gateway.

Run with:

    python stress_test.py

This script intentionally uses the fault injector to create predictable retry
and failover scenarios. That gives a repeatable resilience demo without trying
to trigger real OpenAI rate limits or outages.
"""

import json
import time
from pathlib import Path
from statistics import mean
from typing import Any

from circuit_breaker import reset_circuits
from fault_injector import inject_fault, reset_faults
from gateway import call_with_resilience


RESULTS_PATH = Path("stress_test_results.json")
PROMPT = "Reply with exactly one short sentence about reliable systems."


def build_scenarios() -> list[dict[str, Any]]:
    """Return the 20 requested stress-test scenarios."""
    scenarios: list[dict[str, Any]] = []

    for _ in range(10):
        scenarios.append(
            {
                "scenario": "clean_baseline",
                "provider_a_failures": 0,
            }
        )

    for _ in range(5):
        scenarios.append(
            {
                "scenario": "provider_a_retries_then_succeeds",
                "provider_a_failures": 2,
            }
        )

    for _ in range(5):
        scenarios.append(
            {
                "scenario": "provider_a_failover_to_b",
                "provider_a_failures": 3,
            }
        )

    return scenarios


def run_request(request_id: int, scenario_config: dict[str, Any]) -> dict[str, Any]:
    """Run one gateway request and return a result row."""
    reset_faults()
    reset_circuits()

    provider_a_failures = scenario_config["provider_a_failures"]
    if provider_a_failures:
        inject_fault("A", provider_a_failures)

    start_time = time.perf_counter()

    try:
        gateway_result = call_with_resilience(PROMPT)
        success = True
        error = None
    except Exception as exc:
        gateway_result = {
            "response": None,
            "provider_used": None,
            "attempts": None,
            "failed_over": None,
            "total_cost_usd": 0.0,
        }
        success = False
        error = str(exc)

    elapsed = time.perf_counter() - start_time

    return {
        "request_id": request_id,
        "scenario": scenario_config["scenario"],
        "provider_used": gateway_result["provider_used"],
        "attempts": gateway_result["attempts"],
        "failed_over": gateway_result["failed_over"],
        "total_cost_usd": gateway_result.get("total_cost_usd", 0.0),
        "time_seconds": round(elapsed, 3),
        "success": success,
        "error": error,
        "response": gateway_result["response"],
    }


def run_circuit_breaker_savings_scenario() -> list[dict[str, Any]]:
    """Run four repeated failures to measure open-circuit latency savings."""
    reset_faults()
    reset_circuits()
    inject_fault("A", 10)

    results = []

    for call_number in range(1, 5):
        print()
        print(f"Circuit breaker savings call {call_number}/4")
        start_time = time.perf_counter()

        try:
            gateway_result = call_with_resilience(PROMPT)
            success = True
            error = None
        except Exception as exc:
            gateway_result = {
                "response": None,
                "provider_used": None,
                "attempts": None,
                "failed_over": None,
                "total_cost_usd": 0.0,
            }
            success = False
            error = str(exc)

        elapsed = time.perf_counter() - start_time

        results.append(
            {
                "scenario": "circuit_breaker_savings",
                "call_number": call_number,
                "provider_used": gateway_result["provider_used"],
                "attempts": gateway_result["attempts"],
                "failed_over": gateway_result["failed_over"],
                "total_cost_usd": gateway_result.get("total_cost_usd", 0.0),
                "time_seconds": round(elapsed, 3),
                "success": success,
                "error": error,
                "response": gateway_result["response"],
            }
        )

    reset_faults()
    reset_circuits()
    return results


def percent(count: int, total: int) -> float:
    """Return a rounded percentage for summary reporting."""
    if total == 0:
        return 0.0
    return round((count / total) * 100, 1)


def average_time(results: list[dict[str, Any]]) -> float | None:
    """Average time_seconds for a result subset."""
    if not results:
        return None
    return round(mean(result["time_seconds"] for result in results), 3)


def print_summary(results: list[dict[str, Any]]) -> None:
    """Print aggregate metrics and a compact per-request table."""
    total_requests = len(results)
    successes = [result for result in results if result["success"]]
    retried = [
        result
        for result in results
        if result["attempts"] is not None and result["attempts"] > 1
    ]
    failed_over = [result for result in results if result["failed_over"] is True]
    clean_successes = [
        result
        for result in successes
        if result["scenario"] == "clean_baseline"
    ]
    retried_successes = [
        result
        for result in successes
        if result["attempts"] is not None and result["attempts"] > 1
    ]

    clean_average = average_time(clean_successes)
    retried_average = average_time(retried_successes)
    added_latency = None
    if clean_average is not None and retried_average is not None:
        added_latency = round(retried_average - clean_average, 3)

    print()
    print("Stress Test Summary")
    print("===================")
    print(f"Total requests: {total_requests}")
    print(f"Success rate: {percent(len(successes), total_requests)}%")
    print(f"Required at least 1 retry: {percent(len(retried), total_requests)}%")
    print(f"Required failover to Provider B: {percent(len(failed_over), total_requests)}%")

    if added_latency is None:
        print("Average added latency for retried requests vs clean requests: n/a")
    else:
        print(
            "Average added latency for retried requests vs clean requests: "
            f"{added_latency:.3f}s"
        )

    print()
    print("Per-Request Results")
    print("===================")
    header = (
        f"{'ID':>2}  {'scenario':<34}  {'provider':<8}  "
        f"{'attempts':<8}  {'time':<8}  {'success':<7}"
    )
    print(header)
    print("-" * len(header))

    for result in results:
        provider_used = result["provider_used"] or "-"
        attempts = str(result["attempts"]) if result["attempts"] is not None else "-"
        print(
            f"{result['request_id']:>2}  "
            f"{result['scenario']:<34}  "
            f"{provider_used:<8}  "
            f"{attempts:<8}  "
            f"{result['time_seconds']:<8.3f}  "
            f"{str(result['success']):<7}"
        )


def print_circuit_breaker_savings_summary(results: list[dict[str, Any]]) -> None:
    """Print the dedicated circuit breaker savings report."""
    print()
    print("Circuit Breaker Savings")
    print("=======================")

    if len(results) != 4:
        print("Expected 4 circuit breaker calls, but results are incomplete.")
        return

    call_1_time = results[0]["time_seconds"]
    calls_2_to_4 = results[1:]
    avg_open_circuit_time = average_time(calls_2_to_4)

    print(f"Call 1 time, circuit closed: {call_1_time:.3f}s")

    for result in calls_2_to_4:
        print(
            f"Call {result['call_number']} time, circuit should be open: "
            f"{result['time_seconds']:.3f}s"
        )

    if call_1_time <= 0 or avg_open_circuit_time is None:
        print("Percentage speedup: n/a")
        return

    speedup = ((call_1_time - avg_open_circuit_time) / call_1_time) * 100
    print(f"Average calls 2-4 time: {avg_open_circuit_time:.3f}s")
    print(f"Percentage speedup: {speedup:.1f}%")


def save_results(
    results: list[dict[str, Any]],
    circuit_breaker_results: list[dict[str, Any]],
) -> None:
    """Persist full request results to JSON."""
    payload = {
        "per_request_results": results,
        "circuit_breaker_savings": circuit_breaker_results,
    }

    RESULTS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print()
    print(f"Saved full results to {RESULTS_PATH}")


def main() -> None:
    """Run all configured scenarios and print/save results."""
    results = []

    for request_id, scenario_config in enumerate(build_scenarios(), start=1):
        print()
        print(
            f"Request {request_id}: {scenario_config['scenario']} "
            f"(Provider A injected failures: {scenario_config['provider_a_failures']})"
        )
        results.append(run_request(request_id, scenario_config))

    print_summary(results)
    print()
    print("Running circuit breaker savings scenario last from clean breaker state.")
    circuit_breaker_results = run_circuit_breaker_savings_scenario()
    print_circuit_breaker_savings_summary(circuit_breaker_results)
    save_results(results, circuit_breaker_results)
    reset_faults()
    reset_circuits()


if __name__ == "__main__":
    main()
