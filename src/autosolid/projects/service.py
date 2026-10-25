"""Application use cases for projects and ``CadSpec`` revisions."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from autosolid.artifacts import ArtifactStore, ArtifactStoreError
from autosolid.cad.models import CadSpec, Diagnostic
from autosolid.cad.validation import validate_spec

from .exceptions import (
    ApprovalBlockedError,
    ApprovalHashMismatchError,
    InvalidApprovalError,
    InvalidRevisionError,
    InvalidSpecError,
    RevisionConflictError,
    StoreError,
)
from .naming import validate_project_name
from .sources import MAX_SOURCE_BYTES, validate_source
from .store import (
    ApprovalRecord,
    ProjectRecord,
    ProjectStore,
    RevisionRecord,
    SourceRecord,
)

APPROVAL_SCOPES = ("design",)
MAX_APPROVER_CHARS = 120
MAX_APPROVAL_NOTE_CHARS = 2_000
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


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


@dataclass(frozen=True)
class StoredSourceContent:
    source: SourceRecord
    data: bytes


@dataclass(frozen=True)
class ApprovalInfo:
    id: str
    project_id: str
    revision: int
    revision_sha256: str
    scope: str
    approved_by: str
    note: str | None
    created_at: str
    status: str


class ProjectService:
    """Thin application layer independent from FastAPI."""

    def __init__(
        self,
        store: ProjectStore,
        *,
        artifact_store: ArtifactStore | None = None,
        max_source_bytes: int = MAX_SOURCE_BYTES,
    ) -> None:
        if (
            isinstance(max_source_bytes, bool)
            or not isinstance(max_source_bytes, int)
            or max_source_bytes < 1
        ):
            raise ValueError("max_source_bytes debe ser un entero positivo.")
        self._store = store
        self._artifacts = artifact_store or ArtifactStore(store.data_dir)
        self.max_source_bytes = max_source_bytes

    @property
    def store(self) -> ProjectStore:
        return self._store

    @property
    def artifacts(self) -> ArtifactStore:
        return self._artifacts

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

    def add_source(
        self,
        project_id: str,
        filename: object,
        data: object,
        *,
        kind: object = None,
    ) -> tuple[SourceRecord, bool]:
        """Validate and persist an immutable source; return ``(record, created)``."""

        self._store.get_project(project_id)
        validated = validate_source(
            filename,
            data,
            kind_hint=kind,
            max_bytes=self.max_source_bytes,
        )
        try:
            sha256 = self._artifacts.put(data)
        except ArtifactStoreError as error:
            raise StoreError(
                "No se pudo guardar el contenido de la fuente."
            ) from error
        if sha256 != validated.sha256:
            raise StoreError(
                "El contenido de la fuente no supera la comprobación de integridad."
            )
        return self._store.save_source(
            project_id=project_id,
            sha256=sha256,
            kind=validated.kind,
            filename=validated.filename,
            byte_size=validated.byte_size,
            media_type=validated.media_type,
        )

    def list_sources(self, project_id: str) -> list[SourceRecord]:
        return self._store.list_sources(project_id)

    def get_source(self, project_id: str, source_id: str) -> SourceRecord:
        return self._store.get_source(project_id, source_id)

    def read_source(
        self,
        project_id: str,
        source_id: str,
    ) -> StoredSourceContent:
        source = self._store.get_source(project_id, source_id)
        try:
            data = self._artifacts.read(source.sha256)
        except ArtifactStoreError as error:
            raise StoreError(
                "La fuente almacenada no supera la comprobación de integridad."
            ) from error
        if len(data) != source.byte_size:
            raise StoreError(
                "La fuente almacenada no coincide con sus metadatos."
            )
        return StoredSourceContent(source=source, data=data)

    def approve_revision(
        self,
        project_id: str,
        revision: object,
        sha256: object,
        approved_by: object,
        *,
        scope: object = "design",
        note: object = None,
    ) -> tuple[ApprovalInfo, bool]:
        """Approve the current revision, bound to its stored SHA-256.

        The revision is revalidated before recording the approval. The store
        repeats the current-revision and hash checks inside the write
        transaction.
        """

        approved_revision = _check_approval_revision(revision)
        provided_sha256 = _check_approval_sha256(sha256)
        approval_scope = _check_approval_scope(scope)
        approver, approval_note = _check_approval_text(approved_by, note)

        project = self._store.get_project(project_id)
        if project.current_revision != approved_revision:
            raise RevisionConflictError(
                approved_revision, project.current_revision
            )

        stored = self._to_stored(
            self._store.get_revision(project_id, approved_revision)
        )
        if stored.sha256 != provided_sha256:
            raise ApprovalHashMismatchError(
                project_id,
                approved_revision,
                provided_sha256,
                stored.sha256,
            )

        diagnostics = validate_spec(stored.spec)
        if _has_errors(diagnostics):
            raise ApprovalBlockedError(diagnostics)

        record, created = self._store.save_approval(
            project_id=project_id,
            revision=approved_revision,
            revision_sha256=stored.sha256,
            scope=approval_scope,
            approved_by=approver,
            note=approval_note,
        )
        return self.get_approval(project_id, record.id), created

    def list_approvals(self, project_id: str) -> list[ApprovalInfo]:
        project, current_revision, records = self._store.approval_snapshot(
            project_id
        )
        current_sha256 = (
            self._to_stored(current_revision).sha256 if current_revision else None
        )
        return [
            self._approval_info(record, project, current_sha256)
            for record in records
        ]

    def get_approval(self, project_id: str, approval_id: str) -> ApprovalInfo:
        project, current_revision, records = self._store.approval_snapshot(
            project_id, approval_id
        )
        current_sha256 = (
            self._to_stored(current_revision).sha256 if current_revision else None
        )
        return self._approval_info(records[0], project, current_sha256)

    @staticmethod
    def _approval_info(
        record: ApprovalRecord,
        project: ProjectRecord,
        current_sha256: str | None,
    ) -> ApprovalInfo:
        valid = (
            record.revision == project.current_revision
            and record.revision_sha256 == current_sha256
        )
        return ApprovalInfo(
            id=record.id,
            project_id=record.project_id,
            revision=record.revision,
            revision_sha256=record.revision_sha256,
            scope=record.scope,
            approved_by=record.approved_by,
            note=record.note,
            created_at=record.created_at,
            status="valid" if valid else "stale",
        )

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


def _check_approval_revision(revision: object) -> int:
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 1
    ):
        raise InvalidApprovalError(
            "La revisión aprobada debe ser un entero mayor o igual que uno.",
            reason="revision",
        )
    return revision


def _check_approval_sha256(sha256: object) -> str:
    if not isinstance(sha256, str) or _SHA256_PATTERN.fullmatch(sha256) is None:
        raise InvalidApprovalError(
            "El hash debe ser un SHA-256 hexadecimal de 64 caracteres en minúsculas.",
            reason="sha256",
        )
    return sha256


def _check_approval_scope(scope: object) -> str:
    if scope not in APPROVAL_SCOPES:
        raise InvalidApprovalError(
            "El alcance de la aprobación no es válido.",
            reason="scope",
        )
    return str(scope)


def _check_approval_text(
    approved_by: object,
    note: object,
) -> tuple[str, str | None]:
    if not isinstance(approved_by, str):
        raise InvalidApprovalError(
            "El nombre del revisor debe ser texto.",
            reason="approved_by",
        )
    approver = approved_by.strip()
    if not approver or len(approver) > MAX_APPROVER_CHARS:
        raise InvalidApprovalError(
            (
                "El nombre del revisor debe tener entre 1 y "
                f"{MAX_APPROVER_CHARS} caracteres."
            ),
            reason="approved_by",
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in approver):
        raise InvalidApprovalError(
            "El nombre del revisor no puede contener caracteres de control.",
            reason="approved_by",
        )

    normalized_note: str | None = None
    if note is not None:
        if not isinstance(note, str):
            raise InvalidApprovalError(
                "La nota debe ser texto.",
                reason="note",
            )
        candidate = note.strip()
        if len(candidate) > MAX_APPROVAL_NOTE_CHARS:
            raise InvalidApprovalError(
                (
                    "La nota no puede superar los "
                    f"{MAX_APPROVAL_NOTE_CHARS} caracteres."
                ),
                reason="note",
            )
        if any(
            character == "\x00"
            or (ord(character) < 32 and character not in "\n\r\t")
            for character in candidate
        ):
            raise InvalidApprovalError(
                "La nota contiene caracteres de control no admitidos.",
                reason="note",
            )
        normalized_note = candidate or None

    return approver, normalized_note
