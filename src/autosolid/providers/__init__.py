"""Replaceable model-provider adapters for AUTOSOLID."""

from .base import ModelProvider
from .config import OpenAICompatibleConfig
from .errors import ProviderError
from .models import (
    ChatMessage,
    CompletionRequest,
    CompletionResponse,
    CompletionUsage,
)
from .openai_compatible import OpenAICompatibleProvider
from .simulated import SimulatedProvider, SimulatedReply

__all__ = [
    "ChatMessage",
    "CompletionRequest",
    "CompletionResponse",
    "CompletionUsage",
    "ModelProvider",
    "OpenAICompatibleConfig",
    "OpenAICompatibleProvider",
    "ProviderError",
    "SimulatedProvider",
    "SimulatedReply",
]
