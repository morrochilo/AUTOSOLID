"""Configuration for an OpenAI-compatible provider.

The configuration separates public values from the API key. The key is excluded
from ``repr`` and is never included in error details.
"""

from __future__ import annotations

import ipaddress
import math
import os
from dataclasses import dataclass, field
from numbers import Real
from typing import Any, Mapping
from urllib.parse import urlsplit

from .errors import configuration_error

DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RESPONSE_BYTES = 4_000_000
DEFAULT_ENDPOINT_PATH = "/chat/completions"

_ENV_BASE_URL = "AUTOSOLID_OPENAI_BASE_URL"
_ENV_MODEL = "AUTOSOLID_OPENAI_MODEL"
_ENV_API_KEY = "AUTOSOLID_OPENAI_API_KEY"
_ENV_ORGANIZATION = "AUTOSOLID_OPENAI_ORGANIZATION"
_ENV_TIMEOUT = "AUTOSOLID_OPENAI_TIMEOUT_SECONDS"
_ENV_MAX_BYTES = "AUTOSOLID_OPENAI_MAX_RESPONSE_BYTES"
_ENV_ALLOW_INSECURE = "AUTOSOLID_OPENAI_ALLOW_INSECURE_HTTP"
_ENV_USE_PROXY = "AUTOSOLID_OPENAI_USE_SYSTEM_PROXY"


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _validate_single_line(value: str, field_name: str) -> None:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise configuration_error(
            f"El campo {field_name} no puede contener caracteres de control.",
            details={"field": field_name},
        )


def _validate_header_value(value: str, field_name: str) -> None:
    _validate_single_line(value, field_name)
    try:
        value.encode("latin-1")
    except UnicodeEncodeError as error:
        raise configuration_error(
            f"El campo {field_name} solo admite caracteres Latin-1.",
            details={"field": field_name},
        ) from error


def _validate_ascii_url(value: str, field_name: str) -> None:
    try:
        value.encode("ascii")
    except UnicodeEncodeError as error:
        raise configuration_error(
            f"El campo {field_name} solo admite ASCII; percent-encode la URL.",
            details={"field": field_name},
        ) from error


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    """Validated connection settings for an OpenAI-compatible HTTP API."""

    base_url: str
    model: str
    api_key: str | None = field(default=None, repr=False)
    organization: str | None = field(default=None, repr=False)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    allow_insecure_http: bool = False
    use_system_proxy: bool = False
    provider_name: str = "openai_compatible"
    endpoint_path: str = DEFAULT_ENDPOINT_PATH

    def __post_init__(self) -> None:
        if not isinstance(self.base_url, str):
            raise configuration_error(
                "base_url debe ser texto.",
                details={"field": "base_url"},
            )
        if not isinstance(self.model, str):
            raise configuration_error(
                "model debe ser texto.",
                details={"field": "model"},
            )
        if self.api_key is not None and not isinstance(self.api_key, str):
            raise configuration_error(
                "api_key debe ser texto.",
                details={"field": "api_key"},
            )
        if self.organization is not None and not isinstance(
            self.organization, str
        ):
            raise configuration_error(
                "organization debe ser texto.",
                details={"field": "organization"},
            )
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, Real)
        ):
            raise configuration_error(
                "timeout_seconds debe ser numérico.",
                details={"field": "timeout_seconds"},
            )
        if (
            isinstance(self.max_response_bytes, bool)
            or not isinstance(self.max_response_bytes, int)
        ):
            raise configuration_error(
                "max_response_bytes debe ser un entero.",
                details={"field": "max_response_bytes"},
            )
        if not isinstance(self.allow_insecure_http, bool):
            raise configuration_error(
                "allow_insecure_http debe ser booleano.",
                details={"field": "allow_insecure_http"},
            )
        if not isinstance(self.use_system_proxy, bool):
            raise configuration_error(
                "use_system_proxy debe ser booleano.",
                details={"field": "use_system_proxy"},
            )
        if not isinstance(self.provider_name, str):
            raise configuration_error(
                "provider_name debe ser texto.",
                details={"field": "provider_name"},
            )
        if not isinstance(self.endpoint_path, str):
            raise configuration_error(
                "endpoint_path debe ser texto.",
                details={"field": "endpoint_path"},
            )

        base_url = self.base_url.strip()
        if not base_url or len(base_url) > 2048:
            raise configuration_error(
                "base_url es obligatoria y no puede superar 2048 caracteres.",
                details={"field": "base_url"},
            )
        _validate_single_line(base_url, "base_url")
        _validate_ascii_url(base_url, "base_url")
        try:
            parsed = urlsplit(base_url)
        except ValueError as error:
            raise configuration_error(
                "base_url no es una URL válida.",
                details={"field": "base_url"},
            ) from error

        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise configuration_error(
                "base_url debe ser una URL http o https con host.",
                details={"field": "base_url"},
            )
        try:
            parsed.port
        except ValueError as error:
            raise configuration_error(
                "base_url tiene un puerto inválido.",
                details={"field": "base_url"},
            ) from error
        if parsed.username is not None or parsed.password is not None:
            raise configuration_error(
                "base_url no puede incluir credenciales.",
                details={"field": "base_url"},
            )
        if parsed.query or parsed.fragment or "?" in base_url or "#" in base_url:
            raise configuration_error(
                "base_url no puede incluir consulta ni fragmento.",
                details={"field": "base_url"},
            )
        if (
            parsed.scheme == "http"
            and not _is_loopback(parsed.hostname)
            and not self.allow_insecure_http
        ):
            raise configuration_error(
                "HTTP sin TLS solo se permite en loopback; usa https o "
                "allow_insecure_http explícitamente.",
                details={"field": "base_url"},
            )

        model = self.model.strip()
        if not model or len(model) > 200:
            raise configuration_error(
                "model es obligatorio y no puede superar 200 caracteres.",
                details={"field": "model"},
            )
        _validate_single_line(model, "model")

        endpoint_path = self.endpoint_path.strip()
        if (
            not endpoint_path.startswith("/")
            or endpoint_path.startswith("//")
            or "?" in endpoint_path
            or "#" in endpoint_path
        ):
            raise configuration_error(
                "endpoint_path debe ser una ruta absoluta sin consulta ni fragmento.",
                details={"field": "endpoint_path"},
            )
        _validate_single_line(endpoint_path, "endpoint_path")
        _validate_ascii_url(endpoint_path, "endpoint_path")

        timeout_seconds = float(self.timeout_seconds)
        if (
            not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
            or timeout_seconds > 300
        ):
            raise configuration_error(
                "timeout_seconds debe estar en (0, 300].",
                details={"field": "timeout_seconds"},
            )
        if self.max_response_bytes <= 0 or self.max_response_bytes > 100_000_000:
            raise configuration_error(
                "max_response_bytes debe estar en (0, 100000000].",
                details={"field": "max_response_bytes"},
            )

        provider_name = self.provider_name.strip()
        if not provider_name or len(provider_name) > 100:
            raise configuration_error(
                "provider_name es obligatorio y no puede superar 100 caracteres.",
                details={"field": "provider_name"},
            )

        if self.api_key is not None:
            key = self.api_key.strip()
            if not key or len(key) > 4096:
                raise configuration_error(
                    "api_key no puede estar vacía ni superar 4096 caracteres.",
                    details={"field": "api_key"},
                )
            _validate_header_value(key, "api_key")
            object.__setattr__(self, "api_key", key)
        if self.organization is not None:
            organization = self.organization.strip()
            if not organization or len(organization) > 200:
                raise configuration_error(
                    "organization no puede estar vacía ni superar 200 caracteres.",
                    details={"field": "organization"},
                )
            _validate_header_value(organization, "organization")
            object.__setattr__(self, "organization", organization)

        object.__setattr__(self, "base_url", base_url.rstrip("/"))
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "endpoint_path", endpoint_path)
        object.__setattr__(self, "provider_name", provider_name)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)

    @property
    def endpoint_url(self) -> str:
        return f"{self.base_url}{self.endpoint_path}"

    def to_public_dict(self) -> dict[str, Any]:
        """Return settings safe to log or expose in a health report."""

        return {
            "provider": self.provider_name,
            "base_url": self.base_url,
            "model": self.model,
            "endpoint_path": self.endpoint_path,
            "timeout_seconds": self.timeout_seconds,
            "max_response_bytes": self.max_response_bytes,
            "allow_insecure_http": self.allow_insecure_http,
            "use_system_proxy": self.use_system_proxy,
            "has_api_key": self.api_key is not None,
            "has_organization": self.organization is not None,
        }

    @classmethod
    def from_env(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "OpenAICompatibleConfig":
        env = os.environ if environment is None else environment
        missing = [name for name in (_ENV_BASE_URL, _ENV_MODEL) if not env.get(name)]
        if missing:
            raise configuration_error(
                "Faltan variables de entorno obligatorias del proveedor.",
                details={"missing": missing},
            )

        timeout = _parse_float(env, _ENV_TIMEOUT, DEFAULT_TIMEOUT_SECONDS)
        max_bytes = _parse_int(
            env, _ENV_MAX_BYTES, DEFAULT_MAX_RESPONSE_BYTES
        )
        return cls(
            base_url=env[_ENV_BASE_URL],
            model=env[_ENV_MODEL],
            api_key=env.get(_ENV_API_KEY),
            organization=env.get(_ENV_ORGANIZATION),
            timeout_seconds=timeout,
            max_response_bytes=max_bytes,
            allow_insecure_http=_parse_bool(env, _ENV_ALLOW_INSECURE, False),
            use_system_proxy=_parse_bool(env, _ENV_USE_PROXY, False),
        )


def _parse_bool(
    env: Mapping[str, str],
    name: str,
    default: bool,
) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise configuration_error(
        f"La variable {name} debe ser booleana.",
        details={"variable": name},
    )


def _parse_float(
    env: Mapping[str, str],
    name: str,
    default: float,
) -> float:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as error:
        raise configuration_error(
            f"La variable {name} debe ser numérica.",
            details={"variable": name},
        ) from error


def _parse_int(
    env: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise configuration_error(
            f"La variable {name} debe ser un entero.",
            details={"variable": name},
        ) from error
