"""Strict input and structured output models for MCP tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from autosolid.projects import ApprovalInfo as ServiceApprovalInfo
from autosolid.projects import ProjectRecord, SourceRecord


class _InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _OutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorInfo(_OutputModel):
    code: str
    message: str
    details: Any = Field(default_factory=dict)


class ProjectInfo(_OutputModel):
    id: str
    name: str
    current_revision: int
    created_at: str
    updated_at: str

    @classmethod
    def from_record(cls, project: ProjectRecord) -> "ProjectInfo":
        return cls(
            id=project.id,
            name=project.name,
            current_revision=project.current_revision,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )


class SourceInfo(_OutputModel):
    id: str
    project_id: str
    kind: str
    filename: str
    sha256: str
    byte_size: int
    media_type: str
    created_at: str

    @classmethod
    def from_record(cls, source: SourceRecord) -> "SourceInfo":
        return cls(
            id=source.id,
            project_id=source.project_id,
            kind=source.kind,
            filename=source.filename,
            sha256=source.sha256,
            byte_size=source.byte_size,
            media_type=source.media_type,
            created_at=source.created_at,
        )


class ApprovalInfo(_OutputModel):
    id: str
    project_id: str
    revision: int
    revision_sha256: str
    scope: str
    approved_by: str
    note: str | None = None
    created_at: str
    status: str

    @classmethod
    def from_service(cls, approval: ServiceApprovalInfo) -> "ApprovalInfo":
        return cls(
            id=approval.id,
            project_id=approval.project_id,
            revision=approval.revision,
            revision_sha256=approval.revision_sha256,
            scope=approval.scope,
            approved_by=approval.approved_by,
            note=approval.note,
            created_at=approval.created_at,
            status=approval.status,
        )


class ProjectCreateInput(_InputModel):
    name: str = Field(min_length=1)


class ProjectListInput(_InputModel):
    pass


class ProjectGetInput(_InputModel):
    project_id: str = Field(min_length=1)


class SourceListInput(_InputModel):
    project_id: str = Field(min_length=1)


class SourceGetInput(_InputModel):
    project_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)


class SourceReadTextInput(_InputModel):
    project_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    max_chars: int = Field(default=20_000, ge=1, le=100_000)


class ApprovalListInput(_InputModel):
    project_id: str = Field(min_length=1)


class ApprovalGetInput(_InputModel):
    project_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)


class DesignGetInput(_InputModel):
    project_id: str = Field(min_length=1)


class DesignValidateInput(_InputModel):
    project_id: str = Field(min_length=1)
    spec: dict[str, Any]


class DesignUpdateInput(_InputModel):
    project_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    spec: dict[str, Any]


class ProjectCreateResult(_OutputModel):
    ok: bool
    project: ProjectInfo | None = None
    error: ErrorInfo | None = None


class ProjectListResult(_OutputModel):
    ok: bool
    projects: list[ProjectInfo] = Field(default_factory=list)
    error: ErrorInfo | None = None


class ProjectGetResult(_OutputModel):
    ok: bool
    project: ProjectInfo | None = None
    error: ErrorInfo | None = None


class SourceListResult(_OutputModel):
    ok: bool
    project_id: str | None = None
    sources: list[SourceInfo] = Field(default_factory=list)
    error: ErrorInfo | None = None


class SourceGetResult(_OutputModel):
    ok: bool
    source: SourceInfo | None = None
    error: ErrorInfo | None = None


class ApprovalListResult(_OutputModel):
    ok: bool
    project_id: str | None = None
    approvals: list[ApprovalInfo] = Field(default_factory=list)
    error: ErrorInfo | None = None


class ApprovalGetResult(_OutputModel):
    ok: bool
    approval: ApprovalInfo | None = None
    error: ErrorInfo | None = None


class SourceReadTextResult(_OutputModel):
    ok: bool
    project_id: str | None = None
    source_id: str | None = None
    filename: str | None = None
    sha256: str | None = None
    byte_size: int | None = None
    text: str | None = None
    returned_chars: int | None = None
    truncated: bool | None = None
    error: ErrorInfo | None = None


class DesignGetResult(_OutputModel):
    ok: bool
    project_id: str | None = None
    revision: int | None = None
    sha256: str | None = None
    spec: dict[str, Any] | None = None
    error: ErrorInfo | None = None


class DesignValidateResult(_OutputModel):
    ok: bool
    project_id: str | None = None
    current_revision: int | None = None
    valid: bool | None = None
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    error: ErrorInfo | None = None


class DesignUpdateResult(_OutputModel):
    ok: bool
    project_id: str | None = None
    revision: int | None = None
    sha256: str | None = None
    spec: dict[str, Any] | None = None
    error: ErrorInfo | None = None
