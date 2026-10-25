"""Request models for the local HTTP boundary."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, StrictStr


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr
