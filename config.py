"""Configuration loading for the resilient LLM gateway."""

from copy import deepcopy
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).with_name("config.yaml")

DEFAULT_CONFIG: dict[str, Any] = {
    "providers": {
        "primary": "A",
        "backup": "B",
    },
    "retry": {
        "max_attempts_per_provider": 3,
        "base_delay_seconds": 1,
        "backoff_multiplier": 2,
    },
    "failover": {
        "enabled": True,
    },
}


def _warn(message: str) -> None:
    """Print a lightweight config warning without stopping the gateway."""
    print(f"Config warning: {message}", flush=True)


def _merge_with_defaults(
    defaults: dict[str, Any],
    loaded: dict[str, Any],
    path: str = "",
) -> dict[str, Any]:
    """Recursively merge loaded config values over defaults."""
    merged: dict[str, Any] = {}

    for key, default_value in defaults.items():
        key_path = f"{path}.{key}" if path else key

        if key not in loaded:
            _warn(f"missing '{key_path}', using default {default_value!r}.")
            merged[key] = deepcopy(default_value)
            continue

        loaded_value = loaded[key]
        if isinstance(default_value, dict):
            if isinstance(loaded_value, dict):
                merged[key] = _merge_with_defaults(default_value, loaded_value, key_path)
            else:
                _warn(f"'{key_path}' should be a mapping, using defaults.")
                merged[key] = deepcopy(default_value)
        else:
            merged[key] = loaded_value

    return merged


def _coerce_provider(value: Any, default: str, key_path: str) -> str:
    """Validate provider names while keeping a safe default."""
    if not isinstance(value, str):
        _warn(f"'{key_path}' should be a string, using default {default!r}.")
        return default

    provider = value.upper()
    if provider not in {"A", "B"}:
        _warn(f"'{key_path}' must be 'A' or 'B', using default {default!r}.")
        return default

    return provider


def _coerce_positive_int(value: Any, default: int, key_path: str) -> int:
    """Validate integer retry settings while keeping a safe default."""
    if not isinstance(value, int) or value < 1:
        _warn(f"'{key_path}' should be a positive integer, using default {default}.")
        return default
    return value


def _coerce_positive_number(value: Any, default: int | float, key_path: str) -> int | float:
    """Validate numeric delay settings while keeping a safe default."""
    if not isinstance(value, (int, float)) or value <= 0:
        _warn(f"'{key_path}' should be a positive number, using default {default}.")
        return default
    return value


def _coerce_bool(value: Any, default: bool, key_path: str) -> bool:
    """Validate boolean config settings while keeping a safe default."""
    if not isinstance(value, bool):
        _warn(f"'{key_path}' should be true or false, using default {default}.")
        return default
    return value


def _validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate config values and replace invalid entries with defaults."""
    config["providers"]["primary"] = _coerce_provider(
        config["providers"]["primary"],
        DEFAULT_CONFIG["providers"]["primary"],
        "providers.primary",
    )
    config["providers"]["backup"] = _coerce_provider(
        config["providers"]["backup"],
        DEFAULT_CONFIG["providers"]["backup"],
        "providers.backup",
    )
    config["retry"]["max_attempts_per_provider"] = _coerce_positive_int(
        config["retry"]["max_attempts_per_provider"],
        DEFAULT_CONFIG["retry"]["max_attempts_per_provider"],
        "retry.max_attempts_per_provider",
    )
    config["retry"]["base_delay_seconds"] = _coerce_positive_number(
        config["retry"]["base_delay_seconds"],
        DEFAULT_CONFIG["retry"]["base_delay_seconds"],
        "retry.base_delay_seconds",
    )
    config["retry"]["backoff_multiplier"] = _coerce_positive_number(
        config["retry"]["backoff_multiplier"],
        DEFAULT_CONFIG["retry"]["backoff_multiplier"],
        "retry.backoff_multiplier",
    )
    config["failover"]["enabled"] = _coerce_bool(
        config["failover"]["enabled"],
        DEFAULT_CONFIG["failover"]["enabled"],
        "failover.enabled",
    )

    return config


def load_config() -> dict[str, Any]:
    """Load config.yaml, falling back to safe defaults when needed."""
    if not CONFIG_PATH.exists():
        _warn(f"{CONFIG_PATH} not found, using safe defaults.")
        return deepcopy(DEFAULT_CONFIG)

    try:
        import yaml
    except ImportError:
        _warn("pyyaml is not installed, using safe defaults.")
        return deepcopy(DEFAULT_CONFIG)

    try:
        loaded = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        _warn(f"could not read {CONFIG_PATH}: {exc}. Using safe defaults.")
        return deepcopy(DEFAULT_CONFIG)

    if loaded is None:
        _warn(f"{CONFIG_PATH} is empty, using safe defaults.")
        return deepcopy(DEFAULT_CONFIG)

    if not isinstance(loaded, dict):
        _warn(f"{CONFIG_PATH} should contain a mapping, using safe defaults.")
        return deepcopy(DEFAULT_CONFIG)

    merged = _merge_with_defaults(DEFAULT_CONFIG, loaded)
    return _validate_config(merged)
