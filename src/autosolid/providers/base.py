"""Provider contract independent from HTTP and CAD."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import CompletionRequest, CompletionResponse


@runtime_checkable
class ModelProvider(Protocol):
    """A replaceable model backend.

    Implementations are synchronous; callers on an event loop should offload
    blocking work (for example with ``anyio.to_thread.run_sync``).
    """

    name: str
    model: str

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Return a validated completion or raise ``ProviderError``."""
