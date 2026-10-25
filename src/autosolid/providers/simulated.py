"""Deterministic in-memory provider for tests and local development."""

from __future__ import annotations

import json
import threading
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .errors import ProviderError
from .json_output import parse_json_object
from .models import CompletionRequest, CompletionResponse, CompletionUsage


@dataclass(frozen=True)
class SimulatedReply:
    """One queued reply: raw text, parsed JSON or an injected failure."""

    content: str | None = None
    parsed_json: dict[str, Any] | None = None
    error: Exception | None = None


Reply = str | Mapping[str, Any] | SimulatedReply | Exception


def _strict_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as error:
        raise ProviderError(
            "MODEL_OUTPUT_INVALID",
            "La respuesta simulada no es JSON válido.",
            details={"reason": "invalid_json"},
        ) from error


class SimulatedProvider:
    """Queue-backed provider with no network, clock or randomness."""

    def __init__(
        self,
        replies: Iterable[Reply] = (),
        *,
        name: str = "simulated",
        model: str = "simulated-model",
    ) -> None:
        self.name = name
        self.model = model
        self._replies: deque[Reply] = deque(replies)
        self.requests: list[CompletionRequest] = []
        self._lock = threading.RLock()

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._replies)

    def push(self, *replies: Reply) -> None:
        with self._lock:
            self._replies.extend(replies)

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        with self._lock:
            self.requests.append(request.model_copy(deep=True))
            call_index = len(self.requests)
            if not self._replies:
                raise ProviderError(
                    "SIMULATED_PROVIDER_EXHAUSTED",
                    "No quedan respuestas simuladas.",
                    details={"calls": call_index},
                )
            reply = self._replies.popleft()

        if isinstance(reply, BaseException):
            raise reply
        if isinstance(reply, SimulatedReply):
            if reply.error is not None:
                raise reply.error
            content, parsed_json = self._content_from_reply(reply, request)
        elif isinstance(reply, Mapping):
            content = _strict_json(reply)
            parsed_json = (
                parse_json_object(content)
                if request.response_format == "json_object"
                else None
            )
        else:
            content = reply
            parsed_json = (
                parse_json_object(content)
                if request.response_format == "json_object"
                else None
            )

        return CompletionResponse(
            provider=self.name,
            model=request.model or self.model,
            content=content,
            parsed_json=parsed_json,
            usage=CompletionUsage(),
            latency_ms=0.0,
            request_id=f"sim_{call_index}",
            finish_reason="stop",
        )

    @staticmethod
    def _content_from_reply(
        reply: SimulatedReply,
        request: CompletionRequest,
    ) -> tuple[str, dict[str, Any] | None]:
        if reply.content is not None:
            content = reply.content
        elif reply.parsed_json is not None:
            content = _strict_json(reply.parsed_json)
        else:
            content = ""

        if request.response_format != "json_object":
            return content, None
        parsed = parse_json_object(content)
        if reply.parsed_json is not None and parsed != reply.parsed_json:
            raise ProviderError(
                "MODEL_OUTPUT_INVALID",
                "El contenido y el JSON simulado no coinciden.",
                details={"reason": "inconsistent_reply"},
            )
        return content, parsed
