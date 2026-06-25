# In this version, both simulated providers route through OpenAI. They use
# different models to demonstrate retry/failover behavior without requiring
# multiple paid provider accounts. Swapping in a real second provider later
# would only require adding a new function with the same prompt -> provider
# response shape.

"""Provider adapters for LLM backends."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import OpenAI

from fault_injector import maybe_fail
from pricing import calculate_cost_usd


@dataclass(frozen=True)
class ProviderResponse:
    """Text plus cost metadata returned by a provider call."""

    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float

    def __str__(self) -> str:
        """Keep throwaway print tests readable by showing only response text."""
        return self.text


class ProviderCallError(RuntimeError):
    """Provider call failure that may still include billed token cost."""

    def __init__(
        self,
        message: str,
        *,
        cost_usd: float = 0.0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        super().__init__(message)
        self.cost_usd = cost_usd
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


def _create_client() -> OpenAI:
    """Load environment configuration and return an OpenAI client."""
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set. Add it to your .env file.")

    return OpenAI(api_key=api_key)


def _call_openai_model(prompt: str, model: str) -> ProviderResponse:
    """Call one OpenAI model and return text with cost metadata."""
    client = _create_client()

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as exc:
        raise RuntimeError(f"OpenAI call failed for model {model}: {exc}") from exc

    usage = response.usage
    prompt_tokens = usage.prompt_tokens if usage is not None else 0
    completion_tokens = usage.completion_tokens if usage is not None else 0
    cost_usd = calculate_cost_usd(model, prompt_tokens, completion_tokens)

    text = response.choices[0].message.content
    if text is None:
        raise ProviderCallError(
            f"OpenAI call for model {model} returned no text.",
            cost_usd=cost_usd,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    return ProviderResponse(
        text=text,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
    )


def call_provider_a(prompt: str) -> ProviderResponse:
    """Call the simulated primary provider using OpenAI gpt-4o-mini."""
    # Fault injection happens before the real API call so retry/failover logic
    # can be validated without wasting real OpenAI requests.
    maybe_fail("A")
    return _call_openai_model(prompt, model="gpt-4o-mini")


def call_provider_b(prompt: str) -> ProviderResponse:
    """Call the simulated fallback provider using OpenAI gpt-4o."""
    # This mirrors Provider A's chaos-testing hook while preserving the same
    # prompt -> provider response shape expected by the gateway.
    maybe_fail("B")
    return _call_openai_model(prompt, model="gpt-4o")
