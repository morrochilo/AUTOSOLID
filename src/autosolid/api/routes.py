"""HTTP adapters for the project application service."""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import quote

import anyio
from fastapi import APIRouter, Body, Depends, Query, Request, Response

from autosolid.projects import (
    ApprovalInfo,
    BuildApprovalInfo,
    BuildJobInfo,
    ProjectRecord,
    ProjectService,
    SourceRecord,
    SourceTooLargeError,
    StoredCadspec,
)

from .errors import ApiRequestError
from .schemas import (
    ApprovalCreateRequest,
    BuildApprovalCreateRequest,
    BuildRequest,
    ProjectCreateRequest,
)

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


def _source_payload(source: SourceRecord) -> dict[str, Any]:
    return {
        "id": source.id,
        "project_id": source.project_id,
        "kind": source.kind,
        "filename": source.filename,
        "sha256": source.sha256,
        "byte_size": source.byte_size,
        "media_type": source.media_type,
        "created_at": source.created_at,
    }


def _approval_payload(approval: ApprovalInfo) -> dict[str, Any]:
    return {
        "id": approval.id,
        "project_id": approval.project_id,
        "revision": approval.revision,
        "revision_sha256": approval.revision_sha256,
        "scope": approval.scope,
        "approved_by": approval.approved_by,
        "note": approval.note,
        "created_at": approval.created_at,
        "status": approval.status,
    }


def _build_approval_payload(approval: BuildApprovalInfo) -> dict[str, Any]:
    return {
        "id": approval.id,
        "project_id": approval.project_id,
        "revision": approval.revision,
        "revision_sha256": approval.revision_sha256,
        "scope": approval.scope,
        "approved_by": approval.approved_by,
        "note": approval.note,
        "destination": approval.destination,
        "destination_hash": approval.destination_hash,
        "created_at": approval.created_at,
        "expires_at": approval.expires_at,
        "status": approval.status,
        "consumed_at": approval.consumed_at,
        "job_id": approval.job_id,
    }


def _build_job_payload(job: BuildJobInfo) -> dict[str, Any]:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "revision": job.revision,
        "revision_sha256": job.revision_sha256,
        "approval_id": job.approval_id,
        "idempotency_key": job.idempotency_key,
        "destination": job.destination,
        "destination_hash": job.destination_hash,
        "state": job.state,
        "attempt": job.attempt,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": (
            None
            if job.error_code is None
            else {
                "code": job.error_code,
                "message": job.error_message,
            }
        ),
        "artifact": (
            None
            if job.artifact_name is None
            else {
                "name": job.artifact_name,
                "sha256": job.artifact_sha256,
                "byte_size": job.artifact_byte_size,
            }
        ),
    }


def _set_spec_headers(response: Response, stored: StoredCadspec) -> None:
    response.headers["ETag"] = f'"{stored.sha256}"'
    response.headers["X-CadSpec-SHA256"] = stored.sha256
    response.headers["X-CadSpec-Revision"] = str(stored.revision)


def _content_disposition(filename: str) -> str:
    fallback = "".join(
        character
        if 32 <= ord(character) < 127 and character not in {'"', "\\"}
        else "_"
        for character in filename
    )
    if not fallback.strip(" _"):
        fallback = "source"
    return (
        f'attachment; filename="{fallback}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


async def _read_limited_body(request: Request, limit_bytes: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_length = int(declared)
        except ValueError as error:
            raise ApiRequestError(
                "REQUEST_INVALID",
                "La cabecera Content-Length no es válida.",
            ) from error
        if declared_length < 0:
            raise ApiRequestError(
                "REQUEST_INVALID",
                "La cabecera Content-Length no es válida.",
            )
        if declared_length > limit_bytes:
            raise SourceTooLargeError(limit_bytes, declared_length)

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit_bytes:
            raise SourceTooLargeError(limit_bytes)
        body.extend(chunk)
    return bytes(body)


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


@router.post("/projects/{project_id}/sources", status_code=201)
async def upload_source(
    request: Request,
    project_id: str,
    service: ServiceDep,
    response: Response,
    filename: str = Query(...),
    kind: str | None = Query(default=None),
) -> dict[str, Any]:
    data = await _read_limited_body(request, service.max_source_bytes)
    source, created = await anyio.to_thread.run_sync(
        lambda: service.add_source(project_id, filename, data, kind=kind)
    )
    response.status_code = 201 if created else 200
    response.headers["Location"] = (
        f"/api/v1/projects/{project_id}/sources/{source.id}"
    )
    return _source_payload(source)


@router.get("/projects/{project_id}/sources")
def list_sources(
    project_id: str,
    service: ServiceDep,
) -> list[dict[str, Any]]:
    return [
        _source_payload(source)
        for source in service.list_sources(project_id)
    ]


@router.get("/projects/{project_id}/sources/{source_id}")
def get_source(
    project_id: str,
    source_id: str,
    service: ServiceDep,
) -> dict[str, Any]:
    return _source_payload(service.get_source(project_id, source_id))


@router.get("/projects/{project_id}/sources/{source_id}/content")
def get_source_content(
    project_id: str,
    source_id: str,
    service: ServiceDep,
) -> Response:
    stored = service.read_source(project_id, source_id)
    media_type = stored.source.media_type
    if stored.source.kind == "text":
        media_type = f"{media_type}; charset=utf-8"

    return Response(
        content=stored.data,
        media_type=media_type,
        headers={
            "Content-Disposition": _content_disposition(stored.source.filename),
            "ETag": f'"{stored.source.sha256}"',
            "X-Content-SHA256": stored.source.sha256,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=31536000, immutable",
        },
    )


@router.post("/projects/{project_id}/approvals", status_code=201)
def create_approval(
    project_id: str,
    request: ApprovalCreateRequest,
    service: ServiceDep,
    response: Response,
) -> dict[str, Any]:
    approval, created = service.approve_revision(
        project_id,
        request.revision,
        request.sha256,
        request.approved_by,
        scope=request.scope,
        note=request.note,
    )
    response.status_code = 201 if created else 200
    response.headers["Location"] = (
        f"/api/v1/projects/{project_id}/approvals/{approval.id}"
    )
    return _approval_payload(approval)


@router.get("/projects/{project_id}/approvals")
def list_approvals(
    project_id: str,
    service: ServiceDep,
) -> list[dict[str, Any]]:
    return [
        _approval_payload(approval)
        for approval in service.list_approvals(project_id)
    ]


@router.get("/projects/{project_id}/approvals/{approval_id}")
def get_approval(
    project_id: str,
    approval_id: str,
    service: ServiceDep,
) -> dict[str, Any]:
    return _approval_payload(service.get_approval(project_id, approval_id))


@router.post("/projects/{project_id}/build-approvals", status_code=201)
def create_build_approval(
    project_id: str,
    request: BuildApprovalCreateRequest,
    service: ServiceDep,
    response: Response,
) -> dict[str, Any]:
    approval = service.create_build_approval(
        project_id,
        request.revision,
        request.sha256,
        request.approved_by,
        request.destination,
        expires_in_seconds=request.expires_in_seconds,
        note=request.note,
    )
    response.headers["Location"] = (
        f"/api/v1/projects/{project_id}/build-approvals/{approval.id}"
    )
    return _build_approval_payload(approval)


@router.get("/projects/{project_id}/build-approvals")
def list_build_approvals(
    project_id: str,
    service: ServiceDep,
) -> list[dict[str, Any]]:
    return [
        _build_approval_payload(approval)
        for approval in service.list_build_approvals(project_id)
    ]


@router.get("/projects/{project_id}/build-approvals/{approval_id}")
def get_build_approval(
    project_id: str,
    approval_id: str,
    service: ServiceDep,
) -> dict[str, Any]:
    return _build_approval_payload(
        service.get_build_approval(project_id, approval_id)
    )


@router.post("/projects/{project_id}/builds", status_code=202)
def request_build(
    project_id: str,
    request: BuildRequest,
    service: ServiceDep,
    response: Response,
) -> dict[str, Any]:
    job, created = service.request_build(
        project_id,
        request.approval_id,
        request.destination,
        request.idempotency_key,
    )
    response.status_code = 202 if created else 200
    response.headers["Location"] = (
        f"/api/v1/projects/{project_id}/builds/{job.id}"
    )
    return _build_job_payload(job)


@router.get("/projects/{project_id}/builds")
def list_builds(
    project_id: str,
    service: ServiceDep,
) -> list[dict[str, Any]]:
    return [
        _build_job_payload(job) for job in service.list_build_jobs(project_id)
    ]


@router.get("/projects/{project_id}/builds/{job_id}")
def get_build(
    project_id: str,
    job_id: str,
    service: ServiceDep,
) -> dict[str, Any]:
    return _build_job_payload(service.get_build_job(project_id, job_id))


@router.post("/projects/{project_id}/builds/{job_id}/retry", status_code=202)
def retry_build(
    project_id: str,
    job_id: str,
    service: ServiceDep,
    response: Response,
) -> dict[str, Any]:
    job, changed = service.retry_build_job(project_id, job_id)
    response.status_code = 202 if changed else 200
    response.headers["Location"] = (
        f"/api/v1/projects/{project_id}/builds/{job.id}"
    )
    return _build_job_payload(job)
