"""Stable provider errors without secrets or implementation details."""

from __future__ import annotations

from typing import Any


class ProviderError(Exception):
    """Expected failure while configuring or calling a model provider."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = {} if details is None else dict(details)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }

    def __str__(self) -> str:
        return self.message


def configuration_error(
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> ProviderError:
    return ProviderError("PROVIDER_CONFIG_INVALID", message, details=details)
