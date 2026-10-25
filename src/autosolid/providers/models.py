"""Strict request and response models for model-provider completions."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ChatRole = Literal["system", "user", "assistant"]
ResponseFormat = Literal["text", "json_object"]
FinishReason = Literal["stop", "length", "content_filter", "tool_calls"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ChatMessage(_StrictModel):
    role: ChatRole
    content: str = Field(min_length=1, max_length=1_000_000)


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


class CompletionRequest(_StrictModel):
    messages: tuple[ChatMessage, ...] = Field(
        min_length=1, max_length=200, strict=False
    )
    model: str | None = Field(default=None, min_length=1, max_length=200)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=200_000)
    response_format: ResponseFormat = "text"
    timeout_seconds: float | None = Field(default=None, gt=0, le=300.0)


class CompletionUsage(_StrictModel):
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class CompletionResponse(_StrictModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    content: str
    parsed_json: Mapping[str, Any] | None = None
    usage: CompletionUsage = Field(default_factory=CompletionUsage)
    latency_ms: float = Field(ge=0)
    request_id: str | None = None
    finish_reason: FinishReason | None = None

    @field_validator("parsed_json")
    @classmethod
    def freeze_parsed_json(cls, value: Any) -> Any:
        return _freeze_json(value)
