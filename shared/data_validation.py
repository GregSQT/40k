"""
Validation helpers for enforcing strict configuration and data requirements.

These helpers centralize the "raise on missing / invalid" behavior required by
the AI coding rules so that all modules can share a single, explicit pattern.
"""

from __future__ import annotations

from typing import Any, Mapping, TypeVar


T = TypeVar("T")


class ConfigurationError(RuntimeError):
    """Raised when required configuration or structural data is missing."""


def require_present(value: T | None, name: str) -> T:
    """
    Ensure that a value is present (not None).

    This is the preferred way to validate externally provided values, such as
    data loaded from JSON, environment variables, or external services.
    """
    if value is None:
        raise ConfigurationError(f"Required value '{name}' is missing.")
    return value


def require_key(mapping: Mapping[str, Any], key: str) -> Any:
    """
    Ensure that a key exists in a mapping (typically configuration dictionaries).

    This helper must be used instead of direct dictionary access whenever
    a key is required by design. It raises immediately if the key is absent.
    """
    if key not in mapping:
        raise ConfigurationError(f"Required key '{key}' is missing from mapping.")
    return mapping[key]



