"""Map application failures to stable, non-leaking MCP error payloads."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from autosolid.projects.exceptions import (
    ApprovalBlockedError,
    ApprovalHashMismatchError,
    ApprovalNotFoundError,
    CadspecNotFoundError,
    InvalidApprovalError,
    InvalidProjectNameError,
    InvalidRevisionError,
    InvalidSpecError,
    ProjectNotFoundError,
    RevisionConflictError,
    SourceNotFoundError,
    SourceNotTextError,
    StoreError,
)

from .models import ErrorInfo


def invalid_arguments(error: ValidationError) -> ErrorInfo:
    details = [
        {
            "path": ".".join(str(part) for part in item.get("loc", ())),
            "message": str(item.get("msg", "Entrada inválida")),
            "type": str(item.get("type", "validation_error")),
        }
        for item in error.errors()
    ]
    return ErrorInfo(
        code="INVALID_ARGUMENTS",
        message="Los argumentos de la herramienta no son válidos.",
        details=details,
    )


def from_exception(error: Exception) -> ErrorInfo:
    if isinstance(error, ProjectNotFoundError):
        return ErrorInfo(
            code="PROJECT_NOT_FOUND",
            message="El proyecto solicitado no existe.",
            details={"project_id": error.project_id},
        )
    if isinstance(error, CadspecNotFoundError):
        return ErrorInfo(
            code="CADSPEC_NOT_FOUND",
            message="El proyecto no tiene una especificación guardada.",
            details={"project_id": error.project_id},
        )
    if isinstance(error, RevisionConflictError):
        return ErrorInfo(
            code="REVISION_CONFLICT",
            message="La revisión esperada no coincide con la revisión actual.",
            details={
                "expected_revision": error.expected_revision,
                "current_revision": error.current_revision,
            },
        )
    if isinstance(error, InvalidSpecError):
        return ErrorInfo(
            code="SPEC_INVALID",
            message="La especificación contiene diagnósticos de error.",
            details=[
                diagnostic.model_dump(mode="json")
                for diagnostic in error.diagnostics
            ],
        )
    if isinstance(error, InvalidProjectNameError):
        return ErrorInfo(
            code="INVALID_PROJECT_NAME",
            message=error.message,
        )
    if isinstance(error, InvalidRevisionError):
        return ErrorInfo(
            code="INVALID_EXPECTED_REVISION",
            message=error.message,
        )
    if isinstance(error, SourceNotFoundError):
        return ErrorInfo(
            code="SOURCE_NOT_FOUND",
            message="La fuente solicitada no existe en el proyecto.",
            details={
                "project_id": error.project_id,
                "source_id": error.source_id,
            },
        )
    if isinstance(error, SourceNotTextError):
        return ErrorInfo(
            code="SOURCE_NOT_TEXT",
            message="La fuente solicitada no es de tipo texto.",
            details={
                "project_id": error.project_id,
                "source_id": error.source_id,
                "kind": error.kind,
            },
        )
    if isinstance(error, ApprovalNotFoundError):
        return ErrorInfo(
            code="APPROVAL_NOT_FOUND",
            message="La aprobación solicitada no existe en el proyecto.",
            details={
                "project_id": error.project_id,
                "approval_id": error.approval_id,
            },
        )
    if isinstance(error, ApprovalHashMismatchError):
        return ErrorInfo(
            code="APPROVAL_HASH_MISMATCH",
            message="El hash indicado no coincide con el de la revisión.",
            details={
                "project_id": error.project_id,
                "revision": error.revision,
                "provided_sha256": error.provided_sha256,
                "current_sha256": error.current_sha256,
            },
        )
    if isinstance(error, ApprovalBlockedError):
        return ErrorInfo(
            code="APPROVAL_BLOCKED",
            message="La revisión no cumple las condiciones para aprobarse.",
            details=[
                diagnostic.model_dump(mode="json")
                for diagnostic in error.diagnostics
            ],
        )
    if isinstance(error, InvalidApprovalError):
        return ErrorInfo(
            code="INVALID_APPROVAL",
            message=error.message,
            details={"reason": error.reason},
        )
    if isinstance(error, StoreError):
        return ErrorInfo(
            code="STORE_ERROR",
            message="No se pudo completar la operación de almacenamiento.",
        )
    return ErrorInfo(
        code="INTERNAL_ERROR",
        message="Se produjo un error interno.",
    )


def error_payload(error: ErrorInfo) -> dict[str, Any]:
    return {"ok": False, "error": error.model_dump(mode="json")}
