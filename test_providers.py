"""Throwaway smoke test for the simulated provider functions."""

from providers import call_provider_a, call_provider_b


def main() -> None:
    prompt = "Say hello in 5 words"

    print("Provider A:")
    print(call_provider_a(prompt))
    print()

    print("Provider B:")
    print(call_provider_b(prompt))


if __name__ == "__main__":
    main()
