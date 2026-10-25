"""OpenAI-compatible chat-completions adapter using the standard library."""

from __future__ import annotations

import json
import socket
import time
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from autosolid import __version__

from .config import OpenAICompatibleConfig
from .errors import ProviderError
from .json_output import parse_json_object
from .models import (
    CompletionRequest,
    CompletionResponse,
    CompletionUsage,
    FinishReason,
)

_FINISH_REASONS = {"stop", "length", "content_filter", "tool_calls"}


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class OpenAICompatibleProvider:
    """Call an OpenAI-compatible ``/chat/completions`` endpoint."""

    def __init__(self, config: OpenAICompatibleConfig) -> None:
        self.name = config.provider_name
        self.model = config.model
        self._config = config
        handlers: list[Any] = [_NoRedirectHandler()]
        if not config.use_system_proxy:
            handlers.append(ProxyHandler({}))
        self._opener = build_opener(*handlers)

    @property
    def config(self) -> OpenAICompatibleConfig:
        return self._config

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        started = time.perf_counter()
        payload = self._build_payload(request)
        response_payload = self._post(payload, request)
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        content, model, request_id, finish_reason, usage = _decode_completion(
            response_payload,
            fallback_model=request.model or self._config.model,
        )
        parsed_json = (
            parse_json_object(content)
            if request.response_format == "json_object"
            else None
        )
        return CompletionResponse(
            provider=self.name,
            model=model,
            content=content,
            parsed_json=parsed_json,
            usage=usage,
            latency_ms=elapsed_ms,
            request_id=request_id,
            finish_reason=finish_reason,
        )

    def _build_payload(self, request: CompletionRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model or self._config.model,
            "messages": [
                message.model_dump(mode="json") for message in request.messages
            ],
            "temperature": request.temperature,
            "stream": False,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _post(
        self,
        payload: dict[str, Any],
        request: CompletionRequest,
    ) -> dict[str, Any]:
        timeout = (
            request.timeout_seconds
            if request.timeout_seconds is not None
            else self._config.timeout_seconds
        )
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": f"autosolid/{__version__}",
        }
        if self._config.api_key is not None:
            request_headers["Authorization"] = f"Bearer {self._config.api_key}"
        if self._config.organization is not None:
            request_headers["OpenAI-Organization"] = self._config.organization

        http_request = Request(
            self._config.endpoint_url,
            data=body,
            headers=request_headers,
            method="POST",
        )
        try:
            with self._opener.open(http_request, timeout=timeout) as response:
                data = response.read(self._config.max_response_bytes + 1)
        except HTTPError as error:
            provider_error = _http_error(error)
            try:
                error.close()
            except OSError:
                pass
            raise provider_error from error
        except URLError as error:
            raise _url_error(error, timeout) from error
        except (TimeoutError, socket.timeout) as error:
            raise _timeout_error(timeout) from error
        except (ConnectionError, OSError, HTTPException) as error:
            raise ProviderError(
                "PROVIDER_UNAVAILABLE",
                "No se pudo conectar con el proveedor de modelos.",
                details={"reason": "connection_error"},
            ) from error

        if len(data) > self._config.max_response_bytes:
            raise ProviderError(
                "PROVIDER_RESPONSE_TOO_LARGE",
                "La respuesta del proveedor supera el límite configurado.",
                details={"max_response_bytes": self._config.max_response_bytes},
            )

        return _decode_response_body(data)


def _decode_response_body(data: bytes) -> dict[str, Any]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProviderError(
            "PROVIDER_RESPONSE_INVALID",
            "La respuesta del proveedor no es texto UTF-8 válido.",
            details={"reason": "invalid_utf8"},
        ) from error
    if not text.strip():
        raise ProviderError(
            "PROVIDER_RESPONSE_INVALID",
            "La respuesta del proveedor está vacía.",
            details={"reason": "empty_body"},
        )
    def reject_non_finite(value: str) -> None:
        raise ValueError(f"Número JSON no finito: {value}")

    try:
        parsed = json.loads(text, parse_constant=reject_non_finite)
    except json.JSONDecodeError as error:
        raise ProviderError(
            "PROVIDER_RESPONSE_INVALID",
            "La respuesta del proveedor no es JSON válido.",
            details={"reason": "invalid_json", "position": error.pos},
        ) from error
    except (ValueError, RecursionError) as error:
        raise ProviderError(
            "PROVIDER_RESPONSE_INVALID",
            "La respuesta JSON del proveedor es demasiado compleja o inválida.",
            details={"reason": "invalid_json"},
        ) from error
    if not isinstance(parsed, dict):
        raise ProviderError(
            "PROVIDER_RESPONSE_INVALID",
            "La respuesta del proveedor debe ser un objeto JSON.",
            details={"reason": "json_not_object"},
        )
    return parsed


def _decode_completion(
    payload: dict[str, Any],
    *,
    fallback_model: str,
) -> tuple[str, str, str | None, FinishReason | None, CompletionUsage]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError(
            "PROVIDER_RESPONSE_INVALID",
            "La respuesta del proveedor no contiene opciones.",
            details={"reason": "missing_choices"},
        )
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ProviderError(
            "PROVIDER_RESPONSE_INVALID",
            "La primera opción de la respuesta no es válida.",
            details={"reason": "invalid_choice"},
        )
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ProviderError(
            "PROVIDER_RESPONSE_INVALID",
            "La respuesta del proveedor no contiene un mensaje.",
            details={"reason": "missing_message"},
        )
    content = message.get("content")
    if not isinstance(content, str):
        raise ProviderError(
            "PROVIDER_RESPONSE_INVALID",
            "El mensaje del proveedor no contiene texto.",
            details={"reason": "missing_content"},
        )

    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        model = fallback_model
    request_id = payload.get("id")
    if not isinstance(request_id, str) or not request_id:
        request_id = None
    finish_reason = choice.get("finish_reason")
    if finish_reason not in _FINISH_REASONS:
        finish_reason = None

    return (
        content,
        model,
        request_id,
        finish_reason,
        _decode_usage(payload.get("usage")),
    )


def _decode_usage(raw: Any) -> CompletionUsage:
    if not isinstance(raw, dict):
        return CompletionUsage()
    return CompletionUsage(
        prompt_tokens=_optional_int(raw.get("prompt_tokens")),
        completion_tokens=_optional_int(raw.get("completion_tokens")),
        total_tokens=_optional_int(raw.get("total_tokens")),
    )


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _http_error(error: HTTPError) -> ProviderError:
    status = int(error.code)
    if status in {301, 302, 303, 307, 308}:
        return ProviderError(
            "PROVIDER_REDIRECT_BLOCKED",
            "El proveedor intentó redirigir la petición; no se siguen redirecciones.",
            details={"status": status},
        )
    if status in {401, 403}:
        return ProviderError(
            "PROVIDER_AUTH_FAILED",
            "El proveedor rechazó la autenticación.",
            details={"status": status},
        )
    if status == 429:
        return ProviderError(
            "PROVIDER_RATE_LIMITED",
            "El proveedor limitó temporalmente las peticiones.",
            details={"status": status},
        )
    if 500 <= status <= 599:
        return ProviderError(
            "PROVIDER_UNAVAILABLE",
            "El proveedor no está disponible.",
            details={"status": status},
        )
    return ProviderError(
        "PROVIDER_HTTP_ERROR",
        "El proveedor devolvió un error HTTP.",
        details={"status": status},
    )


def _url_error(error: URLError, timeout: float) -> ProviderError:
    reason = getattr(error, "reason", None)
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return _timeout_error(timeout)
    return ProviderError(
        "PROVIDER_UNAVAILABLE",
        "No se pudo conectar con el proveedor de modelos.",
        details={"reason": "connection_error"},
    )


def _timeout_error(timeout: float) -> ProviderError:
    return ProviderError(
        "PROVIDER_TIMEOUT",
        "El proveedor de modelos agotó el tiempo de espera.",
        details={"timeout_seconds": timeout},
    )
