"""Pricing helpers for estimating OpenAI call cost.

These are illustrative August 2024 list prices used for this portfolio
project. OpenAI pricing changes over time, so production systems should verify
these values against OpenAI's current pricing page before using them for
billing or budget enforcement.
"""


MODEL_PRICING_PER_1M_TOKENS: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {
        "input": 0.15,
        "output": 0.60,
    },
    "gpt-4o": {
        "input": 2.50,
        "output": 10.00,
    },
}


def calculate_cost_usd(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Calculate cost in USD for one model call."""
    try:
        pricing = MODEL_PRICING_PER_1M_TOKENS[model]
    except KeyError as exc:
        raise ValueError(f"No pricing configured for model '{model}'.") from exc

    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost

