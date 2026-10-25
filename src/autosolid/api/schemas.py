"""Request models for the local HTTP boundary."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr


class ApprovalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: StrictInt = Field(ge=1)
    sha256: StrictStr = Field(min_length=64, max_length=64)
    scope: Literal["design"] = "design"
    approved_by: StrictStr = Field(min_length=1, max_length=120)
    note: StrictStr | None = Field(default=None, max_length=2_000)
