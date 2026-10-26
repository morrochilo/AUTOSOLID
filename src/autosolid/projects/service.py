"""Application use cases for projects and ``CadSpec`` revisions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from autosolid.artifacts import ArtifactStore, ArtifactStoreError
from autosolid.build import (
    BuildExecutionError,
    DestinationError,
    ResolvedDestination,
    SerialJobQueue,
    SolidWorksRunner,
    SubprocessSolidWorksRunner,
    UnavailableSolidWorksRunner,
    resolve_destination,
)
from autosolid.cad.models import CadSpec, Diagnostic
from autosolid.cad.validation import validate_spec

from .exceptions import (
    ApprovalBlockedError,
    ApprovalHashMismatchError,
    BuildApprovalStaleError,
    BuildDestinationError,
    BuildDestinationMismatchError,
    BuildJobConflictError,
    InvalidApprovalError,
    InvalidBuildApprovalError,
    InvalidBuildRequestError,
    InvalidRevisionError,
    InvalidSpecError,
    RevisionConflictError,
    StoreError,
)
from .naming import validate_project_name
from .sources import MAX_SOURCE_BYTES, validate_source
from .store import (
    ApprovalRecord,
    BuildApprovalRecord,
    BuildConsumptionRecord,
    BuildJobRecord,
    ProjectRecord,
    ProjectStore,
    RevisionRecord,
    SourceRecord,
    format_timestamp,
)

APPROVAL_SCOPES = ("design",)
BUILD_APPROVAL_SCOPE = "build"
MAX_APPROVER_CHARS = 120
MAX_APPROVAL_NOTE_CHARS = 2_000
MAX_IDEMPOTENCY_KEY_CHARS = 128
MIN_IDEMPOTENCY_KEY_CHARS = 8
DEFAULT_BUILD_APPROVAL_TTL_SECONDS = 900
MIN_BUILD_APPROVAL_TTL_SECONDS = 30
MAX_BUILD_APPROVAL_TTL_SECONDS = 3_600
DEFAULT_BUILD_RUNNER_TIMEOUT_SECONDS = 120.0
_TERMINAL_JOB_STATES = frozenset({"completed", "failed"})
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_IDEMPOTENCY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}")
_PROCESS_BUILD_LOCK = threading.Lock()


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


@dataclass(frozen=True)
class BuildApprovalInfo:
    id: str
    project_id: str
    revision: int
    revision_sha256: str
    scope: str
    approved_by: str
    note: str | None
    destination: str
    destination_hash: str
    created_at: str
    expires_at: str
    status: str
    consumed_at: str | None
    job_id: str | None


@dataclass(frozen=True)
class BuildJobInfo:
    id: str
    project_id: str
    revision: int
    revision_sha256: str
    approval_id: str
    idempotency_key: str
    destination: str
    destination_hash: str
    state: str
    attempt: int
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    error_code: str | None
    error_message: str | None
    artifact_name: str | None
    artifact_sha256: str | None
    artifact_byte_size: int | None


class ProjectService:
    """Thin application layer independent from FastAPI."""

    def __init__(
        self,
        store: ProjectStore,
        *,
        artifact_store: ArtifactStore | None = None,
        max_source_bytes: int = MAX_SOURCE_BYTES,
        build_output_dir: str | os.PathLike[str] | None = None,
        build_approval_ttl_seconds: int = DEFAULT_BUILD_APPROVAL_TTL_SECONDS,
        build_runner: SolidWorksRunner | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if (
            isinstance(max_source_bytes, bool)
            or not isinstance(max_source_bytes, int)
            or max_source_bytes < 1
        ):
            raise ValueError("max_source_bytes debe ser un entero positivo.")
        if (
            isinstance(build_approval_ttl_seconds, bool)
            or not isinstance(build_approval_ttl_seconds, int)
            or not (
                MIN_BUILD_APPROVAL_TTL_SECONDS
                <= build_approval_ttl_seconds
                <= MAX_BUILD_APPROVAL_TTL_SECONDS
            )
        ):
            raise ValueError(
                "build_approval_ttl_seconds debe estar entre "
                f"{MIN_BUILD_APPROVAL_TTL_SECONDS} y "
                f"{MAX_BUILD_APPROVAL_TTL_SECONDS}."
            )
        self._store = store
        self._artifacts = artifact_store or ArtifactStore(store.data_dir)
        self.max_source_bytes = max_source_bytes
        self.build_approval_ttl_seconds = build_approval_ttl_seconds
        self._now = now or (lambda: datetime.now(timezone.utc))

        configured_root = build_output_dir
        if configured_root is None:
            configured_root = os.environ.get("AUTOSOLID_BUILD_DIR") or None
        base_root = (
            Path(configured_root)
            if configured_root is not None
            else store.data_dir / "builds"
        )
        self._build_root = Path(base_root).expanduser().resolve()
        self._runner = (
            build_runner if build_runner is not None else _runner_from_environment()
        )
        self._queue = SerialJobQueue(
            self._process_build_job,
            name="autosolid-build",
        )

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

    # -- Build approvals and serial jobs -----------------------------------

    def create_build_approval(
        self,
        project_id: str,
        revision: object,
        sha256: object,
        approved_by: object,
        destination: object,
        *,
        expires_in_seconds: object = None,
        note: object = None,
    ) -> BuildApprovalInfo:
        """Create a one-use build approval bound to revision, hash and path."""

        try:
            approved_revision = _check_approval_revision(revision)
            provided_sha256 = _check_approval_sha256(sha256)
            approver, approval_note = _check_approval_text(approved_by, note)
        except InvalidApprovalError as error:
            raise InvalidBuildApprovalError(
                error.message,
                reason=error.reason,
            ) from error
        ttl_seconds = _check_build_ttl(
            self.build_approval_ttl_seconds
            if expires_in_seconds is None
            else expires_in_seconds
        )
        project = self._store.get_project(project_id)
        resolved = self._resolve_destination(destination, require_absent=True)

        if project.current_revision != approved_revision:
            raise BuildApprovalStaleError(
                project_id,
                approved_revision,
                current_revision=project.current_revision,
            )
        stored = self._to_stored(
            self._store.get_revision(project_id, approved_revision)
        )
        if stored.sha256 != provided_sha256:
            raise BuildApprovalStaleError(
                project_id,
                approved_revision,
                current_revision=project.current_revision,
            )
        diagnostics = validate_spec(stored.spec)
        if _has_errors(diagnostics):
            raise ApprovalBlockedError(diagnostics)

        now = self._now()
        created_at = format_timestamp(now)
        expires_at = format_timestamp(now + timedelta(seconds=ttl_seconds))
        record = self._store.save_build_approval(
            project_id=project_id,
            revision=approved_revision,
            revision_sha256=stored.sha256,
            approved_by=approver,
            note=approval_note,
            destination=resolved.relative,
            destination_hash=resolved.destination_hash,
            created_at=created_at,
            expires_at=expires_at,
        )
        return self.get_build_approval(project_id, record.id)

    def list_build_approvals(self, project_id: str) -> list[BuildApprovalInfo]:
        project, current_revision, records, consumptions = (
            self._store.build_approval_snapshot(project_id)
        )
        current_sha256 = (
            self._to_stored(current_revision).sha256 if current_revision else None
        )
        now = format_timestamp(self._now())
        return [
            self._build_approval_info(
                record,
                project,
                current_sha256,
                consumptions.get(record.id),
                now,
            )
            for record in records
        ]

    def get_build_approval(
        self,
        project_id: str,
        approval_id: str,
    ) -> BuildApprovalInfo:
        project, current_revision, records, consumptions = (
            self._store.build_approval_snapshot(project_id, approval_id)
        )
        current_sha256 = (
            self._to_stored(current_revision).sha256 if current_revision else None
        )
        return self._build_approval_info(
            records[0],
            project,
            current_sha256,
            consumptions.get(records[0].id),
            format_timestamp(self._now()),
        )

    @staticmethod
    def _build_approval_info(
        record: BuildApprovalRecord,
        project: ProjectRecord,
        current_sha256: str | None,
        consumption: BuildConsumptionRecord | None,
        now: str,
    ) -> BuildApprovalInfo:
        if consumption is not None:
            status = "used"
        elif now >= record.expires_at:
            status = "expired"
        elif (
            record.revision != project.current_revision
            or record.revision_sha256 != current_sha256
        ):
            status = "stale"
        else:
            status = "valid"
        return BuildApprovalInfo(
            id=record.id,
            project_id=record.project_id,
            revision=record.revision,
            revision_sha256=record.revision_sha256,
            scope=record.scope,
            approved_by=record.approved_by,
            note=record.note,
            destination=record.destination,
            destination_hash=record.destination_hash,
            created_at=record.created_at,
            expires_at=record.expires_at,
            status=status,
            consumed_at=(
                None if consumption is None else consumption.consumed_at
            ),
            job_id=None if consumption is None else consumption.job_id,
        )

    def request_build(
        self,
        project_id: str,
        approval_id: object,
        destination: object,
        idempotency_key: object,
    ) -> tuple[BuildJobInfo, bool]:
        """Consume an approval and enqueue a build job exactly once."""

        checked_approval = _check_build_approval_id(approval_id)
        checked_key = _check_idempotency_key(idempotency_key)
        self._store.get_project(project_id)
        resolved = self._resolve_destination(destination, require_absent=False)

        existing = self._store.get_build_job_by_idempotency(
            project_id, checked_key
        )
        if existing is not None:
            if (
                existing.approval_id != checked_approval
                or existing.destination_hash != resolved.destination_hash
            ):
                raise BuildJobConflictError(
                    "La clave de idempotencia ya pertenece a otro trabajo.",
                    reason="idempotency_key",
                )
            return self._build_job_info(existing), False

        approval = self.get_build_approval(project_id, checked_approval)
        if approval.status != "valid":
            # Let the atomic store decide. It may return the job that belongs
            # to this idempotency key, or raise consumed/expired/stale.
            record, created = self._store.enqueue_build_job(
                project_id=project_id,
                approval_id=checked_approval,
                idempotency_key=checked_key,
                destination=resolved.relative,
                destination_hash=resolved.destination_hash,
                now=format_timestamp(self._now()),
            )
            if created:
                self._queue.submit(record.id)
            return self._build_job_info(record), created

        if resolved.destination_hash != approval.destination_hash:
            raise BuildDestinationMismatchError(
                project_id, checked_approval
            )
        if resolved.path.exists() or resolved.path.is_symlink():
            # A concurrent completion with the same key must stay idempotent.
            existing = self._store.get_build_job_by_idempotency(
                project_id, checked_key
            )
            if existing is not None and (
                existing.approval_id == checked_approval
                and existing.destination_hash == resolved.destination_hash
            ):
                return self._build_job_info(existing), False
            raise BuildDestinationError(
                "El destino ya existe; no se sobrescribe.",
                reason="exists",
            )

        record, created = self._store.enqueue_build_job(
            project_id=project_id,
            approval_id=checked_approval,
            idempotency_key=checked_key,
            destination=resolved.relative,
            destination_hash=resolved.destination_hash,
            now=format_timestamp(self._now()),
        )
        if created:
            self._queue.submit(record.id)
        return self._build_job_info(record), created

    def list_build_jobs(self, project_id: str) -> list[BuildJobInfo]:
        return [
            self._build_job_info(record)
            for record in self._store.list_build_jobs(project_id)
        ]

    def get_build_job(self, project_id: str, job_id: str) -> BuildJobInfo:
        return self._build_job_info(self._store.get_build_job(project_id, job_id))

    def retry_build_job(
        self,
        project_id: str,
        job_id: str,
    ) -> tuple[BuildJobInfo, bool]:
        """Requeue a failed job without consuming its approval again.

        A ``running`` job left behind by a crash or by a failed durable update
        is first reconciled: if its prepared artifact is already published and
        matches the stored hash, the job is marked completed without running
        the agent again.
        """

        record = self._store.get_build_job(project_id, job_id)
        if record.state == "running":
            if self._queue.is_active(record.id):
                return self._build_job_info(record), False
            record = self._reconcile_running_job(record)
            if record.state == "completed":
                return self._build_job_info(record), False

        if record.state == "queued":
            # Harmless if it is already in this process's serial queue; after
            # a restart this is the explicit way to resume a durable queued job.
            self._queue.submit(record.id)
            return self._build_job_info(record), False
        if record.state != "failed":
            return self._build_job_info(record), False

        # A failure after publication may still have a durable artifact. Never
        # rebuild or consume the approval again when the file already matches.
        if record.artifact_sha256 is not None:
            completed = self._complete_if_published(record)
            if completed.state == "completed":
                return self._build_job_info(completed), False
            record = completed

        project = self._store.get_project(project_id)
        stored = self._to_stored(
            self._store.get_revision(project_id, record.revision)
        )
        if (
            project.current_revision != record.revision
            or stored.sha256 != record.revision_sha256
        ):
            raise BuildApprovalStaleError(
                project_id,
                record.revision,
                current_revision=project.current_revision,
            )
        resolved = self._resolve_destination(record.destination, require_absent=True)
        if resolved.destination_hash != record.destination_hash:
            raise BuildDestinationMismatchError(project_id, record.approval_id)

        requeued, changed = self._store.requeue_build_job(
            project_id,
            job_id,
            now=format_timestamp(self._now()),
        )
        if changed:
            self._queue.submit(requeued.id)
        return self._build_job_info(requeued), changed

    def recover_incomplete_build_jobs(self) -> list[BuildJobInfo]:
        """Reconcile durable jobs left ``running`` or partially published.

        This is safe to call at startup. It never invokes the CAD agent and
        never deletes an unverified file: a matching published artifact is
        marked completed, while an unverifiable one becomes a recoverable
        failure that the explicit retry endpoint can handle.
        """

        results: list[BuildJobInfo] = []
        # Do not race the in-process worker: an item that is still active will
        # publish or fail on its own before recovery inspects the durable state.
        self._queue.wait_idle()
        for record in self._store.list_build_jobs_in_states(
            ("running", "failed")
        ):
            if self._queue.is_active(record.id):
                results.append(self._build_job_info(record))
                continue
            if record.state == "running":
                updated = self._reconcile_running_job(record)
            elif record.artifact_sha256 is not None:
                updated = self._complete_if_published(record)
            else:
                updated = record
            results.append(self._build_job_info(updated))
        return results

    def wait_for_job(
        self,
        project_id: str,
        job_id: str,
        *,
        timeout: float = 10.0,
        interval: float = 0.02,
    ) -> BuildJobInfo:
        deadline = time.monotonic() + timeout
        while True:
            job = self.get_build_job(project_id, job_id)
            if job.state in _TERMINAL_JOB_STATES:
                return job
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"El trabajo '{job_id}' no terminó dentro del plazo."
                )
            time.sleep(interval)

    def shutdown(self) -> None:
        """Stop the in-process build worker, if it was started."""

        self._queue.stop()

    @staticmethod
    def _build_job_info(record: BuildJobRecord) -> BuildJobInfo:
        return BuildJobInfo(
            id=record.id,
            project_id=record.project_id,
            revision=record.revision,
            revision_sha256=record.revision_sha256,
            approval_id=record.approval_id,
            idempotency_key=record.idempotency_key,
            destination=record.destination,
            destination_hash=record.destination_hash,
            state=record.state,
            attempt=record.attempt,
            created_at=record.created_at,
            updated_at=record.updated_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            error_code=record.error_code,
            error_message=record.error_message,
            artifact_name=record.artifact_name,
            artifact_sha256=record.artifact_sha256,
            artifact_byte_size=record.artifact_byte_size,
        )

    def _resolve_destination(
        self,
        destination: object,
        *,
        require_absent: bool,
    ) -> ResolvedDestination:
        try:
            return resolve_destination(
                self._build_root,
                destination,
                require_absent=require_absent,
            )
        except DestinationError as error:
            raise BuildDestinationError(error.message, reason=error.reason) from error

    def _reconcile_running_job(self, record: BuildJobRecord) -> BuildJobRecord:
        """Complete a published artifact or mark the job recoverably failed."""

        if record.state != "running" or self._queue.is_active(record.id):
            return record
        if record.artifact_sha256 is not None:
            completed = self._complete_if_published(record)
            if completed.state == "completed":
                return completed
            return self._fail_recovery(
                record,
                "El artefacto publicado no coincide con los metadatos del trabajo.",
            )
        return self._fail_recovery(
            record,
            "El trabajo quedó en ejecución sin metadatos de artefacto.",
        )

    def _complete_if_published(self, record: BuildJobRecord) -> BuildJobRecord:
        """Mark ``record`` completed when its exact artifact is already on disk."""

        if record.artifact_sha256 is None:
            return record
        project = self._store.get_project(record.project_id)
        revision = self._store.get_revision(
            record.project_id,
            record.revision,
        )
        if (
            project.current_revision != record.revision
            or revision.sha256 != record.revision_sha256
        ):
            return record
        try:
            resolved = self._resolve_destination(
                record.destination,
                require_absent=False,
            )
        except BuildDestinationError:
            return record
        if resolved.destination_hash != record.destination_hash:
            return record
        if not _matches_artifact(
            resolved.path,
            record.artifact_sha256,
            record.artifact_byte_size,
        ):
            return record
        completed = self._store.finalize_recovered_build_job(
            record.id,
            now=format_timestamp(self._now()),
            artifact_sha256=record.artifact_sha256,
            artifact_byte_size=record.artifact_byte_size,
        )
        return record if completed is None else completed

    def _fail_recovery(self, record: BuildJobRecord, message: str) -> BuildJobRecord:
        return self._store.finish_build_job(
            record.id,
            state="failed",
            now=format_timestamp(self._now()),
            error_code="OUTPUT_RECOVERY_FAILED",
            error_message=message[:500],
        )

    def _process_build_job(self, job_id: str) -> None:
        """Serial worker entry point; never lets a runner command be chosen."""

        try:
            job = self._store.start_build_job(
                job_id,
                now=format_timestamp(self._now()),
            )
        except Exception:
            return
        if job is None or job.state != "running":
            return

        try:
            with _PROCESS_BUILD_LOCK:
                artifact = self._execute_build_job(job)
        except BuildExecutionError as error:
            self._finish_failed(job_id, error.code, error.message)
            return
        except BuildDestinationError as error:
            code = (
                "DESTINATION_EXISTS"
                if error.reason == "exists"
                else "INVALID_DESTINATION"
            )
            self._finish_failed(job_id, code, error.message)
            return
        except Exception:
            self._finish_failed(
                job_id,
                "INTERNAL_ERROR",
                "El trabajo de construcción falló de forma inesperada.",
            )
            return

        try:
            self._store.finish_build_job(
                job_id,
                state="completed",
                now=format_timestamp(self._now()),
                artifact_name=artifact[0],
                artifact_sha256=artifact[1],
                artifact_byte_size=artifact[2],
            )
        except Exception:  # pragma: no cover - durable record remains running
            return

    def _execute_build_job(
        self,
        job: BuildJobRecord,
    ) -> tuple[str, str, int]:
        project = self._store.get_project(job.project_id)
        stored = self._to_stored(
            self._store.get_revision(job.project_id, job.revision)
        )
        if (
            project.current_revision != job.revision
            or stored.sha256 != job.revision_sha256
        ):
            raise BuildExecutionError(
                "APPROVAL_STALE",
                "La revisión cambió después de consumir la aprobación.",
            )

        resolved = self._resolve_destination(
            job.destination,
            require_absent=True,
        )
        if resolved.destination_hash != job.destination_hash:
            raise BuildExecutionError(
                "DESTINATION_MISMATCH",
                "El destino del trabajo no coincide con su aprobación.",
            )

        work_root = self._build_root / ".work"
        try:
            work_root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise BuildExecutionError(
                "OUTPUT_WRITE_FAILED",
                "No se pudo preparar el directorio de trabajo de construcción.",
            ) from error

        try:
            with tempfile.TemporaryDirectory(
                prefix=f"{job.id}-",
                dir=work_root,
                ignore_cleanup_errors=True,
            ) as temporary:
                temporary_path = Path(temporary)
                spec_path = temporary_path / "spec.json"
                spec_path.write_text(
                    json.dumps(
                        stored.spec,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    encoding="utf-8",
                )
                staging_path = temporary_path / "staging.sldprt"
                self._runner.build(
                    spec_path,
                    staging_path,
                    output_root=self._build_root,
                )
                if (
                    staging_path.is_symlink()
                    or not staging_path.is_file()
                    or not staging_path.resolve().is_relative_to(self._build_root)
                    or staging_path.stat().st_size <= 0
                ):
                    raise BuildExecutionError(
                        "OUTPUT_MISSING",
                        "El agente no generó un archivo .sldprt válido.",
                    )

                # Hash and metadata are prepared before the final file exists.
                # A failure here can never leave a valid SLDPRT without a
                # durable record, and a later crash can be reconciled.
                sha256, byte_size = _file_digest(staging_path)
                recorded = self._store.record_build_job_artifact(
                    job.id,
                    now=format_timestamp(self._now()),
                    artifact_name=resolved.relative,
                    artifact_sha256=sha256,
                    artifact_byte_size=byte_size,
                )
                if recorded is None:
                    raise BuildExecutionError(
                        "JOB_NOT_RUNNING",
                        "El trabajo dejó de estar en ejecución antes de publicar.",
                    )

                # TOCTOU recheck immediately before the exclusive publish.
                current = self._resolve_destination(
                    job.destination,
                    require_absent=True,
                )
                if (
                    current.destination_hash != job.destination_hash
                    or current.path != resolved.path
                ):
                    raise BuildExecutionError(
                        "DESTINATION_CHANGED",
                        "El destino cambió antes de publicar el archivo .sldprt.",
                    )
                self._move_without_overwrite(staging_path, current.path)
        except BuildExecutionError:
            raise
        except OSError as error:
            raise BuildExecutionError(
                "OUTPUT_WRITE_FAILED",
                "No se pudo guardar el archivo .sldprt resultante.",
            ) from error

        return resolved.relative, sha256, byte_size

    def _finish_failed(self, job_id: str, code: str, message: str) -> None:
        try:
            self._store.finish_build_job(
                job_id,
                state="failed",
                now=format_timestamp(self._now()),
                error_code=code[:80],
                error_message=message[:500],
            )
        except Exception:  # pragma: no cover - durable record remains running
            return

    @staticmethod
    def _move_without_overwrite(source: Path, target: Path) -> None:
        """Publish a prepared file with an exclusive hard link only.

        The hard link is atomic and never exposes a partial file at ``target``.
        Hard links are mandatory: when ``os.link`` is unavailable the publish
        fails with ``OUTPUT_WRITE_FAILED`` instead of copying, renaming or
        replacing anything. ``target`` is never opened for writing and is never
        removed; a pre-existing file is always treated as someone else's.
        """

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise BuildExecutionError(
                "OUTPUT_WRITE_FAILED",
                "No se pudo preparar el destino del archivo .sldprt.",
            ) from error

        try:
            os.link(source, target)
        except FileExistsError as error:
            raise BuildExecutionError(
                "DESTINATION_EXISTS",
                "El destino ya existe; no se sobrescribe.",
            ) from error
        except (OSError, NotImplementedError) as error:
            raise BuildExecutionError(
                "OUTPUT_WRITE_FAILED",
                "No se pudo publicar el archivo .sldprt sin sobrescribir.",
            ) from error

        _unlink_quiet(source)

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


def _check_build_ttl(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not (
            MIN_BUILD_APPROVAL_TTL_SECONDS
            <= value
            <= MAX_BUILD_APPROVAL_TTL_SECONDS
        )
    ):
        raise InvalidBuildApprovalError(
            "La validez de la aprobación debe ser un entero entre "
            f"{MIN_BUILD_APPROVAL_TTL_SECONDS} y "
            f"{MAX_BUILD_APPROVAL_TTL_SECONDS} segundos.",
            reason="expires_in_seconds",
        )
    return value


def _check_build_approval_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 120
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise InvalidBuildRequestError(
            "La aprobación de construcción no es válida.",
            reason="approval_id",
        )
    return value.strip()


def _check_idempotency_key(value: object) -> str:
    if (
        not isinstance(value, str)
        or _IDEMPOTENCY_PATTERN.fullmatch(value) is None
    ):
        raise InvalidBuildRequestError(
            "La clave de idempotencia debe tener entre "
            f"{MIN_IDEMPOTENCY_KEY_CHARS} y "
            f"{MAX_IDEMPOTENCY_KEY_CHARS} caracteres alfanuméricos, "
            "punto, guion, guion bajo o dos puntos.",
            reason="idempotency_key",
        )
    return value


def _runner_from_environment() -> SolidWorksRunner:
    executable = os.environ.get("AUTOSOLID_SOLIDWORKS_AGENT", "").strip()
    if not executable:
        return UnavailableSolidWorksRunner()

    timeout_seconds = DEFAULT_BUILD_RUNNER_TIMEOUT_SECONDS
    configured_timeout = os.environ.get("AUTOSOLID_SOLIDWORKS_TIMEOUT")
    if configured_timeout:
        try:
            candidate = float(configured_timeout)
            if candidate > 0:
                timeout_seconds = candidate
        except ValueError:
            pass

    max_output_bytes = 64 * 1024
    configured_output = os.environ.get("AUTOSOLID_SOLIDWORKS_MAX_OUTPUT")
    if configured_output:
        try:
            candidate_output = int(configured_output)
            if candidate_output >= 1024:
                max_output_bytes = candidate_output
        except ValueError:
            pass

    return SubprocessSolidWorksRunner(
        executable,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
    )


def _file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _unlink_quiet(path: Path) -> None:
    """Remove a path owned by this process, ignoring cleanup failures."""

    try:
        path.unlink()
    except OSError:
        pass


def _matches_artifact(
    path: Path,
    expected_sha256: str,
    expected_byte_size: int | None,
) -> bool:
    """Return ``True`` only for a complete, regular file with the exact hash."""

    try:
        if path.is_symlink() or not path.is_file():
            return False
        digest, byte_size = _file_digest(path)
    except OSError:
        return False
    if digest != expected_sha256:
        return False
    return expected_byte_size is None or byte_size == expected_byte_size
