"""HTTP adapters for the project application service."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, Request, Response

from autosolid.projects import ProjectRecord, ProjectService, StoredCadspec

from .errors import ApiRequestError
from .schemas import ProjectCreateRequest

router = APIRouter(prefix="/api/v1")


def get_service(request: Request) -> ProjectService:
    return request.app.state.service


ServiceDep = Annotated[ProjectService, Depends(get_service)]


def _project_payload(project: ProjectRecord) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "current_revision": project.current_revision,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def _set_spec_headers(response: Response, stored: StoredCadspec) -> None:
    response.headers["ETag"] = f'"{stored.sha256}"'
    response.headers["X-CadSpec-SHA256"] = stored.sha256
    response.headers["X-CadSpec-Revision"] = str(stored.revision)


def _extract_update(
    payload: Any,
    query_expected_revision: int | None,
) -> tuple[Any, Any]:
    expected_revision = query_expected_revision
    spec_payload = payload

    if isinstance(payload, dict) and "spec" in payload:
        extra_fields = sorted(set(payload) - {"spec", "expected_revision"})
        if extra_fields:
            raise ApiRequestError(
                "REQUEST_INVALID",
                "La actualización contiene campos no admitidos.",
                details={"extra_fields": extra_fields},
            )
        spec_payload = payload["spec"]
        if "expected_revision" in payload:
            body_expected = payload["expected_revision"]
            if (
                query_expected_revision is not None
                and body_expected != query_expected_revision
            ):
                raise ApiRequestError(
                    "REQUEST_INVALID",
                    "expected_revision no coincide entre el cuerpo y la consulta.",
                )
            expected_revision = body_expected
    elif isinstance(payload, dict) and "expected_revision" in payload:
        spec_payload = dict(payload)
        body_expected = spec_payload.pop("expected_revision")
        if (
            query_expected_revision is not None
            and body_expected != query_expected_revision
        ):
            raise ApiRequestError(
                "REQUEST_INVALID",
                "expected_revision no coincide entre el cuerpo y la consulta.",
            )
        expected_revision = body_expected

    if expected_revision is None:
        raise ApiRequestError(
            "MISSING_EXPECTED_REVISION",
            "La actualización requiere expected_revision.",
        )

    return expected_revision, spec_payload


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/projects", status_code=201)
def create_project(
    request: ProjectCreateRequest,
    service: ServiceDep,
) -> dict[str, Any]:
    return _project_payload(service.create_project(request.name))


@router.get("/projects")
def list_projects(service: ServiceDep) -> list[dict[str, Any]]:
    return [_project_payload(project) for project in service.list_projects()]


@router.get("/projects/{project_id}")
def get_project(project_id: str, service: ServiceDep) -> dict[str, Any]:
    return _project_payload(service.get_project(project_id))


@router.get("/projects/{project_id}/cadspec")
def get_cadspec(
    service: ServiceDep,
    project_id: str,
    response: Response,
) -> dict[str, Any]:
    stored = service.get_cadspec(project_id)
    _set_spec_headers(response, stored)
    return stored.spec


@router.post("/projects/{project_id}/cadspec/validate")
def validate_cadspec(
    service: ServiceDep,
    project_id: str,
    payload: Any = Body(...),
) -> dict[str, Any]:
    outcome = service.validate_cadspec(project_id, payload)
    return {
        "valid": outcome.valid,
        "project_id": outcome.project_id,
        "current_revision": outcome.current_revision,
        "diagnostics": [
            diagnostic.model_dump(mode="json")
            for diagnostic in outcome.diagnostics
        ],
    }


@router.put("/projects/{project_id}/cadspec")
def save_cadspec(
    service: ServiceDep,
    project_id: str,
    response: Response,
    payload: Any = Body(...),
    expected_revision: int | None = Query(default=None),
) -> dict[str, Any]:
    expected, spec_payload = _extract_update(payload, expected_revision)
    stored = service.save_cadspec(project_id, expected, spec_payload)
    _set_spec_headers(response, stored)
    return stored.spec
