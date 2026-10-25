"""Stable HTTP error responses without leaking implementation details."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from autosolid.projects.exceptions import (
    ApprovalBlockedError,
    ApprovalHashMismatchError,
    ApprovalNotFoundError,
    CadspecNotFoundError,
    InvalidApprovalError,
    InvalidProjectNameError,
    InvalidRevisionError,
    InvalidSourceError,
    InvalidSpecError,
    ProjectNotFoundError,
    RevisionConflictError,
    SourceNotFoundError,
    SourceTooLargeError,
    StoreError,
)


class ApiRequestError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Any = None,
        status_code: int = 422,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = {} if details is None else details
        self.status_code = status_code


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": {} if details is None else details,
            }
        },
    )


def _diagnostic_details_from_list(
    diagnostics: list[Any],
) -> list[dict[str, Any]]:
    return [
        diagnostic.model_dump(mode="json")
        for diagnostic in diagnostics
    ]


def _diagnostic_details(error: InvalidSpecError) -> list[dict[str, Any]]:
    return _diagnostic_details_from_list(error.diagnostics)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiRequestError)
    async def _api_request_error(_: Request, error: ApiRequestError) -> JSONResponse:
        return error_response(
            error.status_code, error.code, error.message, error.details
        )

    @app.exception_handler(ProjectNotFoundError)
    async def _project_not_found(
        _: Request, error: ProjectNotFoundError
    ) -> JSONResponse:
        return error_response(
            404,
            "PROJECT_NOT_FOUND",
            "El proyecto solicitado no existe.",
            {"project_id": error.project_id},
        )

    @app.exception_handler(CadspecNotFoundError)
    async def _cadspec_not_found(
        _: Request, error: CadspecNotFoundError
    ) -> JSONResponse:
        return error_response(
            404,
            "CADSPEC_NOT_FOUND",
            "El proyecto no tiene una especificación guardada.",
            {"project_id": error.project_id},
        )

    @app.exception_handler(RevisionConflictError)
    async def _revision_conflict(
        _: Request, error: RevisionConflictError
    ) -> JSONResponse:
        return error_response(
            409,
            "REVISION_CONFLICT",
            "La revisión esperada no coincide con la revisión actual.",
            {
                "expected_revision": error.expected_revision,
                "current_revision": error.current_revision,
            },
        )

    @app.exception_handler(InvalidSpecError)
    async def _invalid_spec(
        _: Request, error: InvalidSpecError
    ) -> JSONResponse:
        return error_response(
            422,
            "SPEC_INVALID",
            "La especificación contiene diagnósticos de error.",
            _diagnostic_details(error),
        )

    @app.exception_handler(InvalidProjectNameError)
    async def _invalid_project_name(
        _: Request, error: InvalidProjectNameError
    ) -> JSONResponse:
        return error_response(422, "INVALID_PROJECT_NAME", error.message)

    @app.exception_handler(InvalidRevisionError)
    async def _invalid_revision(
        _: Request, error: InvalidRevisionError
    ) -> JSONResponse:
        return error_response(422, "INVALID_EXPECTED_REVISION", error.message)

    @app.exception_handler(InvalidSourceError)
    async def _invalid_source(
        _: Request, error: InvalidSourceError
    ) -> JSONResponse:
        return error_response(
            422,
            "INVALID_SOURCE",
            error.message,
            {"reason": error.reason},
        )

    @app.exception_handler(SourceTooLargeError)
    async def _source_too_large(
        _: Request, error: SourceTooLargeError
    ) -> JSONResponse:
        return error_response(
            413,
            "SOURCE_TOO_LARGE",
            "La fuente supera el límite permitido.",
            {
                "limit_bytes": error.limit_bytes,
                "actual_bytes": error.actual_bytes,
            },
        )

    @app.exception_handler(SourceNotFoundError)
    async def _source_not_found(
        _: Request, error: SourceNotFoundError
    ) -> JSONResponse:
        return error_response(
            404,
            "SOURCE_NOT_FOUND",
            "La fuente solicitada no existe en el proyecto.",
            {
                "project_id": error.project_id,
                "source_id": error.source_id,
            },
        )

    @app.exception_handler(InvalidApprovalError)
    async def _invalid_approval(
        _: Request, error: InvalidApprovalError
    ) -> JSONResponse:
        return error_response(
            422,
            "INVALID_APPROVAL",
            error.message,
            {"reason": error.reason},
        )

    @app.exception_handler(ApprovalNotFoundError)
    async def _approval_not_found(
        _: Request, error: ApprovalNotFoundError
    ) -> JSONResponse:
        return error_response(
            404,
            "APPROVAL_NOT_FOUND",
            "La aprobación solicitada no existe en el proyecto.",
            {
                "project_id": error.project_id,
                "approval_id": error.approval_id,
            },
        )

    @app.exception_handler(ApprovalHashMismatchError)
    async def _approval_hash_mismatch(
        _: Request, error: ApprovalHashMismatchError
    ) -> JSONResponse:
        return error_response(
            409,
            "APPROVAL_HASH_MISMATCH",
            "El hash indicado no coincide con el de la revisión.",
            {
                "project_id": error.project_id,
                "revision": error.revision,
                "provided_sha256": error.provided_sha256,
                "current_sha256": error.current_sha256,
            },
        )

    @app.exception_handler(ApprovalBlockedError)
    async def _approval_blocked(
        _: Request, error: ApprovalBlockedError
    ) -> JSONResponse:
        return error_response(
            409,
            "APPROVAL_BLOCKED",
            "La revisión no cumple las condiciones para aprobarse.",
            _diagnostic_details_from_list(error.diagnostics),
        )

    @app.exception_handler(StoreError)
    async def _store_error(_: Request, __: StoreError) -> JSONResponse:
        return error_response(
            500,
            "STORE_ERROR",
            "No se pudo completar la operación de almacenamiento.",
        )

    @app.exception_handler(RequestValidationError)
    async def _request_validation_error(
        _: Request, error: RequestValidationError
    ) -> JSONResponse:
        details = []
        for item in error.errors():
            details.append(
                {
                    "path": ".".join(str(part) for part in item.get("loc", ())),
                    "message": str(item.get("msg", "Entrada inválida")),
                    "type": str(item.get("type", "validation_error")),
                }
            )
        return error_response(
            422,
            "REQUEST_INVALID",
            "La solicitud no es válida.",
            details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(
        _: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        codes = {
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
        }
        messages = {
            404: "El recurso solicitado no existe.",
            405: "El método HTTP no está permitido para este recurso.",
        }
        return error_response(
            error.status_code,
            codes.get(error.status_code, "HTTP_ERROR"),
            messages.get(error.status_code, "La solicitud HTTP no pudo completarse."),
        )

    @app.exception_handler(Exception)
    async def _unexpected_error(_: Request, __: Exception) -> JSONResponse:
        return error_response(
            500,
            "INTERNAL_ERROR",
            "Se produjo un error interno.",
        )
