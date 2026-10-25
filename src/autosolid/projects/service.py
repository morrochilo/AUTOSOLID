"""Application use cases for projects and ``CadSpec`` revisions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from autosolid.cad.models import CadSpec, Diagnostic
from autosolid.cad.validation import validate_spec

from .exceptions import (
    InvalidRevisionError,
    InvalidSpecError,
    RevisionConflictError,
    StoreError,
)
from .naming import validate_project_name
from .store import ProjectRecord, ProjectStore, RevisionRecord


@dataclass(frozen=True)
class ValidationOutcome:
    project_id: str
    current_revision: int
    valid: bool
    diagnostics: list[Diagnostic]


@dataclass(frozen=True)
class StoredCadspec:
    project_id: str
    revision: int
    sha256: str
    spec: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class RevisionInfo:
    project_id: str
    revision: int
    sha256: str
    created_at: str


class ProjectService:
    """Thin application layer independent from FastAPI."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    @property
    def store(self) -> ProjectStore:
        return self._store

    def create_project(self, name: str) -> ProjectRecord:
        return self._store.create_project(validate_project_name(name))

    def list_projects(self) -> list[ProjectRecord]:
        return self._store.list_projects()

    def get_project(self, project_id: str) -> ProjectRecord:
        return self._store.get_project(project_id)

    def get_cadspec(self, project_id: str) -> StoredCadspec:
        return self._to_stored(self._store.get_cadspec(project_id))

    def get_revision(self, project_id: str, revision: int) -> StoredCadspec:
        return self._to_stored(self._store.get_revision(project_id, revision))

    def list_revisions(self, project_id: str) -> list[RevisionInfo]:
        self._store.get_project(project_id)
        return [
            RevisionInfo(
                project_id=record.project_id,
                revision=record.revision,
                sha256=record.sha256,
                created_at=record.created_at,
            )
            for record in self._store.list_revisions(project_id)
        ]

    def validate_cadspec(
        self,
        project_id: str,
        payload: Mapping[str, Any] | CadSpec,
    ) -> ValidationOutcome:
        project = self._store.get_project(project_id)
        _, diagnostics = self._prepare(project_id, payload)
        return ValidationOutcome(
            project_id=project_id,
            current_revision=project.current_revision,
            valid=not _has_errors(diagnostics),
            diagnostics=diagnostics,
        )

    def save_cadspec(
        self,
        project_id: str,
        expected_revision: int,
        payload: Mapping[str, Any] | CadSpec,
    ) -> StoredCadspec:
        _check_expected_revision(expected_revision)
        project = self._store.get_project(project_id)

        if project.current_revision != expected_revision:
            raise RevisionConflictError(
                expected_revision, project.current_revision
            )

        spec, diagnostics = self._prepare(project_id, payload)
        if spec is None or _has_errors(diagnostics):
            raise InvalidSpecError(diagnostics)

        new_revision = expected_revision + 1
        stored_spec = spec.model_copy(update={"revision": new_revision})
        spec_json = stored_spec.model_dump_json()
        sha256 = hashlib.sha256(spec_json.encode("utf-8")).hexdigest()

        record = self._store.save_revision(
            project_id=project_id,
            expected_revision=expected_revision,
            revision=new_revision,
            spec_json=spec_json,
            sha256=sha256,
        )
        return self._to_stored(record)

    @staticmethod
    def _prepare(
        project_id: str,
        payload: Mapping[str, Any] | CadSpec,
    ) -> tuple[CadSpec | None, list[Diagnostic]]:
        diagnostics = validate_spec(payload)
        if _has_errors(diagnostics):
            return None, diagnostics

        try:
            spec = (
                payload
                if isinstance(payload, CadSpec)
                else CadSpec.model_validate(payload)
            )
        except ValidationError as error:
            return None, [
                Diagnostic(
                    code="SCHEMA_INVALID",
                    severity="error",
                    path="$.spec",
                    message=str(error),
                )
            ]

        if spec.project_id != project_id:
            diagnostics.append(
                Diagnostic(
                    code="PROJECT_ID_MISMATCH",
                    severity="error",
                    path="project_id",
                    message=(
                        "El project_id de la especificación no coincide con "
                        "el proyecto de la ruta."
                    ),
                )
            )
        return spec, diagnostics

    @staticmethod
    def _to_stored(record: RevisionRecord) -> StoredCadspec:
        actual_hash = hashlib.sha256(record.spec_json.encode("utf-8")).hexdigest()
        if actual_hash != record.sha256:
            raise StoreError("La revisión almacenada no supera la comprobación de integridad.")

        try:
            spec = json.loads(record.spec_json)
        except json.JSONDecodeError as error:
            raise StoreError("La revisión almacenada no contiene JSON válido.") from error

        if (
            not isinstance(spec, dict)
            or spec.get("project_id") != record.project_id
            or spec.get("revision") != record.revision
        ):
            raise StoreError("La revisión almacenada no es coherente con su índice.")

        return StoredCadspec(
            project_id=record.project_id,
            revision=record.revision,
            sha256=record.sha256,
            spec=spec,
            created_at=record.created_at,
        )


def _has_errors(diagnostics: list[Diagnostic]) -> bool:
    return any(diagnostic.severity == "error" for diagnostic in diagnostics)


def _check_expected_revision(expected_revision: object) -> None:
    if (
        isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
        or expected_revision < 0
    ):
        raise InvalidRevisionError(
            "expected_revision debe ser un entero mayor o igual que cero."
        )
