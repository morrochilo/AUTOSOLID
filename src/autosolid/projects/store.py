"""SQLite persistence for projects and immutable ``CadSpec`` revisions."""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .exceptions import (
    ApprovalHashMismatchError,
    ApprovalNotFoundError,
    CadspecNotFoundError,
    ProjectNotFoundError,
    RevisionConflictError,
    SourceNotFoundError,
    StoreClosedError,
    StoreError,
)
from .naming import validate_project_name
from .sources import source_media_type

SCHEMA_VERSION = 4
DATABASE_FILENAME = "autosolid.db"
BUSY_TIMEOUT_MS = 30_000

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    current_revision INTEGER NOT NULL DEFAULT 0 CHECK (current_revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS revisions (
    project_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    spec_json TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, revision),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TRIGGER IF NOT EXISTS revisions_immutable_update
BEFORE UPDATE ON revisions
BEGIN
    SELECT RAISE(ABORT, 'revisions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS revisions_immutable_delete
BEFORE DELETE ON revisions
BEGIN
    SELECT RAISE(ABORT, 'revisions are immutable');
END;

CREATE INDEX IF NOT EXISTS idx_revisions_project
ON revisions (project_id, revision);
"""

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS artifacts (
    sha256 TEXT PRIMARY KEY
        CHECK (length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    media_type TEXT NOT NULL CHECK (length(media_type) > 0),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('pdf', 'image', 'text')),
    filename TEXT NOT NULL CHECK (length(filename) > 0),
    created_at TEXT NOT NULL,
    UNIQUE (project_id, sha256),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (sha256) REFERENCES artifacts(sha256)
);

CREATE TRIGGER IF NOT EXISTS artifacts_immutable_update
BEFORE UPDATE ON artifacts
BEGIN
    SELECT RAISE(ABORT, 'artifacts are immutable');
END;

CREATE TRIGGER IF NOT EXISTS artifacts_immutable_delete
BEFORE DELETE ON artifacts
BEGIN
    SELECT RAISE(ABORT, 'artifacts are immutable');
END;

CREATE TRIGGER IF NOT EXISTS sources_immutable_update
BEFORE UPDATE ON sources
BEGIN
    SELECT RAISE(ABORT, 'sources are immutable');
END;

CREATE TRIGGER IF NOT EXISTS sources_immutable_delete
BEFORE DELETE ON sources
BEGIN
    SELECT RAISE(ABORT, 'sources are immutable');
END;

CREATE INDEX IF NOT EXISTS idx_sources_project
ON sources (project_id, created_at, id);
"""

_SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    revision_sha256 TEXT NOT NULL
        CHECK (
            length(revision_sha256) = 64
            AND revision_sha256 NOT GLOB '*[^0-9a-f]*'
        ),
    scope TEXT NOT NULL CHECK (scope IN ('design')),
    approved_by TEXT NOT NULL
        CHECK (
            length(trim(approved_by)) > 0
            AND length(approved_by) <= 120
        ),
    note TEXT CHECK (note IS NULL OR length(note) <= 2000),
    created_at TEXT NOT NULL,
    UNIQUE (project_id, revision, scope),
    FOREIGN KEY (project_id, revision)
        REFERENCES revisions(project_id, revision)
);

CREATE TRIGGER IF NOT EXISTS approvals_immutable_update
BEFORE UPDATE ON approvals
BEGIN
    SELECT RAISE(ABORT, 'approvals are immutable');
END;

CREATE TRIGGER IF NOT EXISTS approvals_immutable_delete
BEFORE DELETE ON approvals
BEGIN
    SELECT RAISE(ABORT, 'approvals are immutable');
END;

CREATE INDEX IF NOT EXISTS idx_approvals_project
ON approvals (project_id, created_at, id);
"""

_SCHEMA_V4 = """
CREATE TRIGGER IF NOT EXISTS revisions_immutable_insert
BEFORE INSERT ON revisions
WHEN EXISTS (
    SELECT 1 FROM revisions
    WHERE project_id = NEW.project_id AND revision = NEW.revision
)
BEGIN
    SELECT RAISE(ABORT, 'revisions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS artifacts_immutable_insert
BEFORE INSERT ON artifacts
WHEN EXISTS (SELECT 1 FROM artifacts WHERE sha256 = NEW.sha256)
BEGIN
    SELECT RAISE(ABORT, 'artifacts are immutable');
END;

CREATE TRIGGER IF NOT EXISTS sources_immutable_insert
BEFORE INSERT ON sources
WHEN EXISTS (SELECT 1 FROM sources WHERE id = NEW.id)
OR EXISTS (
    SELECT 1 FROM sources
    WHERE project_id = NEW.project_id AND sha256 = NEW.sha256
)
BEGIN
    SELECT RAISE(ABORT, 'sources are immutable');
END;

CREATE TRIGGER IF NOT EXISTS approvals_immutable_insert
BEFORE INSERT ON approvals
WHEN EXISTS (SELECT 1 FROM approvals WHERE id = NEW.id)
OR EXISTS (
    SELECT 1 FROM approvals
    WHERE project_id = NEW.project_id
        AND revision = NEW.revision
        AND scope = NEW.scope
)
BEGIN
    SELECT RAISE(ABORT, 'approvals are immutable');
END;
"""

_SOURCE_SELECT = """
SELECT s.id, s.project_id, s.sha256, s.kind, s.filename, s.created_at,
       a.byte_size
FROM sources AS s
JOIN artifacts AS a ON a.sha256 = s.sha256
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class ProjectRecord:
    id: str
    name: str
    current_revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class RevisionRecord:
    project_id: str
    revision: int
    spec_json: str
    sha256: str
    created_at: str


@dataclass(frozen=True)
class ArtifactRecord:
    sha256: str
    byte_size: int
    media_type: str
    created_at: str


@dataclass(frozen=True)
class SourceRecord:
    id: str
    project_id: str
    sha256: str
    kind: str
    filename: str
    byte_size: int
    media_type: str
    created_at: str


@dataclass(frozen=True)
class ApprovalRecord:
    id: str
    project_id: str
    revision: int
    revision_sha256: str
    scope: str
    approved_by: str
    note: str | None
    created_at: str


class ProjectStore:
    """Thread-safe-enough SQLite store using one connection per operation.

    SQLite connections are opened and closed inside each call, so the store can
    be shared by FastAPI's test client or request threads. Writers use
    ``BEGIN IMMEDIATE`` and an explicit revision check to prevent lost updates.
    """

    def __init__(self, data_dir: str | os.PathLike[str] | None = None) -> None:
        if data_dir is None:
            data_dir = os.environ.get("AUTOSOLID_DATA_DIR", ".autosolid")
        self.data_dir = Path(data_dir).expanduser().resolve()
        self._database_path = self.data_dir / DATABASE_FILENAME
        self._closed = False
        self._initialized = False
        self._init_lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "ProjectStore":
        return cls()

    @property
    def database_path(self) -> Path:
        return self._database_path

    def close(self) -> None:
        self._closed = True

    def __enter__(self) -> "ProjectStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise StoreClosedError()

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self._initialize()
            self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self._database_path),
            timeout=BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA recursive_triggers = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        self._ensure_open()
        self._ensure_initialized()
        connection = self._connect()
        transaction_open = False
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
                transaction_open = True
            yield connection
        except BaseException:
            if transaction_open:
                connection.execute("ROLLBACK")
            raise
        else:
            if transaction_open:
                connection.execute("COMMIT")
        finally:
            connection.close()

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if version == 0:
                connection.executescript(_SCHEMA_V1)
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                    "VALUES (?, ?)",
                    (1, _utc_now()),
                )
                connection.execute("PRAGMA user_version = 1")
                connection.execute("COMMIT")
                version = 1

            if version == 1:
                connection.executescript(_SCHEMA_V2)
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                    "VALUES (?, ?)",
                    (2, _utc_now()),
                )
                connection.execute("PRAGMA user_version = 2")
                connection.execute("COMMIT")
                version = 2

            if version == 2:
                connection.executescript(_SCHEMA_V3)
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                    "VALUES (?, ?)",
                    (3, _utc_now()),
                )
                connection.execute("PRAGMA user_version = 3")
                connection.execute("COMMIT")
                version = 3

            if version == 3:
                connection.executescript(_SCHEMA_V4)
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                    "VALUES (?, ?)",
                    (4, _utc_now()),
                )
                connection.execute("PRAGMA user_version = 4")
                connection.execute("COMMIT")
                version = 4

            if version != SCHEMA_VERSION:
                raise StoreError(
                    "La versión del esquema SQLite no es compatible."
                )
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    @staticmethod
    def _project_from_row(row: sqlite3.Row) -> ProjectRecord:
        return ProjectRecord(
            id=row["id"],
            name=row["name"],
            current_revision=int(row["current_revision"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _revision_from_row(row: sqlite3.Row) -> RevisionRecord:
        return RevisionRecord(
            project_id=row["project_id"],
            revision=int(row["revision"]),
            spec_json=row["spec_json"],
            sha256=row["sha256"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _source_from_row(row: sqlite3.Row) -> SourceRecord:
        return SourceRecord(
            id=row["id"],
            project_id=row["project_id"],
            sha256=row["sha256"],
            kind=row["kind"],
            filename=row["filename"],
            byte_size=int(row["byte_size"]),
            media_type=source_media_type(row["filename"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _approval_from_row(row: sqlite3.Row) -> ApprovalRecord:
        return ApprovalRecord(
            id=row["id"],
            project_id=row["project_id"],
            revision=int(row["revision"]),
            revision_sha256=row["revision_sha256"],
            scope=row["scope"],
            approved_by=row["approved_by"],
            note=row["note"],
            created_at=row["created_at"],
        )

    def create_project(self, name: str) -> ProjectRecord:
        normalized_name = validate_project_name(name)
        project_id = f"prj_{uuid.uuid4().hex}"
        timestamp = _utc_now()
        with self._connection(write=True) as connection:
            connection.execute(
                "INSERT INTO projects(id, name, current_revision, created_at, updated_at) "
                "VALUES (?, ?, 0, ?, ?)",
                (project_id, normalized_name, timestamp, timestamp),
            )
        return ProjectRecord(
            id=project_id,
            name=normalized_name,
            current_revision=0,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def list_projects(self) -> list[ProjectRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, name, current_revision, created_at, updated_at "
                "FROM projects ORDER BY created_at ASC, id ASC"
            ).fetchall()
        return [self._project_from_row(row) for row in rows]

    def get_project(self, project_id: str) -> ProjectRecord:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT id, name, current_revision, created_at, updated_at "
                "FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        if row is None:
            raise ProjectNotFoundError(project_id)
        return self._project_from_row(row)

    def save_revision(
        self,
        project_id: str,
        expected_revision: int,
        revision: int,
        spec_json: str,
        sha256: str,
    ) -> RevisionRecord:
        timestamp = _utc_now()
        with self._connection(write=True) as connection:
            project_row = connection.execute(
                "SELECT current_revision FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if project_row is None:
                raise ProjectNotFoundError(project_id)

            current_revision = int(project_row["current_revision"])
            if current_revision != expected_revision:
                raise RevisionConflictError(expected_revision, current_revision)

            try:
                connection.execute(
                    "INSERT INTO revisions(project_id, revision, spec_json, sha256, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (project_id, revision, spec_json, sha256, timestamp),
                )
            except sqlite3.IntegrityError as error:
                raise RevisionConflictError(
                    expected_revision, current_revision
                ) from error

            updated = connection.execute(
                "UPDATE projects SET current_revision = ?, updated_at = ? "
                "WHERE id = ? AND current_revision = ?",
                (revision, timestamp, project_id, expected_revision),
            )
            if updated.rowcount != 1:
                raise RevisionConflictError(expected_revision, current_revision)

        return RevisionRecord(
            project_id=project_id,
            revision=revision,
            spec_json=spec_json,
            sha256=sha256,
            created_at=timestamp,
        )

    def get_cadspec(self, project_id: str) -> RevisionRecord:
        self.get_project(project_id)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT project_id, revision, spec_json, sha256, created_at "
                "FROM revisions WHERE project_id = ? "
                "ORDER BY revision DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        if row is None:
            raise CadspecNotFoundError(project_id)
        return self._revision_from_row(row)

    def get_revision(self, project_id: str, revision: int) -> RevisionRecord:
        self.get_project(project_id)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT project_id, revision, spec_json, sha256, created_at "
                "FROM revisions WHERE project_id = ? AND revision = ?",
                (project_id, revision),
            ).fetchone()
        if row is None:
            raise CadspecNotFoundError(project_id)
        return self._revision_from_row(row)

    def list_revisions(self, project_id: str) -> list[RevisionRecord]:
        self.get_project(project_id)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT project_id, revision, spec_json, sha256, created_at "
                "FROM revisions WHERE project_id = ? ORDER BY revision ASC",
                (project_id,),
            ).fetchall()
        return [self._revision_from_row(row) for row in rows]

    def save_source(
        self,
        project_id: str,
        sha256: str,
        kind: str,
        filename: str,
        byte_size: int,
        media_type: str,
    ) -> tuple[SourceRecord, bool]:
        """Attach immutable source metadata, returning ``(record, created)``."""

        timestamp = _utc_now()
        with self._connection(write=True) as connection:
            project_row = connection.execute(
                "SELECT id FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if project_row is None:
                raise ProjectNotFoundError(project_id)

            artifact_row = connection.execute(
                "SELECT sha256, byte_size, media_type, created_at "
                "FROM artifacts WHERE sha256 = ?",
                (sha256,),
            ).fetchone()
            if artifact_row is None:
                connection.execute(
                    "INSERT INTO artifacts(sha256, byte_size, media_type, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (sha256, byte_size, media_type, timestamp),
                )
            elif int(artifact_row["byte_size"]) != byte_size:
                raise StoreError(
                    "Los metadatos del artefacto no coinciden con su contenido."
                )

            existing = connection.execute(
                f"{_SOURCE_SELECT} WHERE s.project_id = ? AND s.sha256 = ?",
                (project_id, sha256),
            ).fetchone()
            if existing is not None:
                if existing["kind"] != kind:
                    raise StoreError(
                        "El contenido ya existe con otro tipo de fuente."
                    )
                return self._source_from_row(existing), False

            source_id = f"src_{uuid.uuid4().hex}"
            try:
                connection.execute(
                    "INSERT INTO sources(id, project_id, sha256, kind, filename, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        source_id,
                        project_id,
                        sha256,
                        kind,
                        filename,
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise StoreError(
                    "No se pudo registrar la fuente en el almacén."
                ) from error

            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (timestamp, project_id),
            )

        return (
            SourceRecord(
                id=source_id,
                project_id=project_id,
                sha256=sha256,
                kind=kind,
                filename=filename,
                byte_size=byte_size,
                media_type=media_type,
                created_at=timestamp,
            ),
            True,
        )

    def list_sources(self, project_id: str) -> list[SourceRecord]:
        self.get_project(project_id)
        with self._connection() as connection:
            rows = connection.execute(
                f"{_SOURCE_SELECT} WHERE s.project_id = ? "
                "ORDER BY s.created_at ASC, s.id ASC",
                (project_id,),
            ).fetchall()
        return [self._source_from_row(row) for row in rows]

    def get_source(self, project_id: str, source_id: str) -> SourceRecord:
        self.get_project(project_id)
        with self._connection() as connection:
            row = connection.execute(
                f"{_SOURCE_SELECT} WHERE s.project_id = ? AND s.id = ?",
                (project_id, source_id),
            ).fetchone()
        if row is None:
            raise SourceNotFoundError(project_id, source_id)
        return self._source_from_row(row)

    def get_artifact(self, sha256: str) -> ArtifactRecord:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT sha256, byte_size, media_type, created_at "
                "FROM artifacts WHERE sha256 = ?",
                (sha256,),
            ).fetchone()
        if row is None:
            raise StoreError("El artefacto no está registrado en el almacén.")
        return ArtifactRecord(
            sha256=row["sha256"],
            byte_size=int(row["byte_size"]),
            media_type=row["media_type"],
            created_at=row["created_at"],
        )

    def save_approval(
        self,
        project_id: str,
        revision: int,
        revision_sha256: str,
        scope: str,
        approved_by: str,
        note: str | None,
    ) -> tuple[ApprovalRecord, bool]:
        """Record a design approval, returning ``(record, created)``.

        The current revision and hash are checked again inside the write
        transaction so a concurrent revision cannot leave an incoherent
        approval behind.
        """

        timestamp = _utc_now()
        with self._connection(write=True) as connection:
            project_row = connection.execute(
                "SELECT current_revision FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if project_row is None:
                raise ProjectNotFoundError(project_id)

            current_revision = int(project_row["current_revision"])
            if current_revision != revision:
                raise RevisionConflictError(revision, current_revision)

            revision_row = connection.execute(
                "SELECT sha256 FROM revisions "
                "WHERE project_id = ? AND revision = ?",
                (project_id, revision),
            ).fetchone()
            if revision_row is None:
                raise CadspecNotFoundError(project_id)

            current_sha256 = revision_row["sha256"]
            if current_sha256 != revision_sha256:
                raise ApprovalHashMismatchError(
                    project_id,
                    revision,
                    revision_sha256,
                    current_sha256,
                )

            existing = connection.execute(
                "SELECT id, project_id, revision, revision_sha256, scope, "
                "approved_by, note, created_at "
                "FROM approvals "
                "WHERE project_id = ? AND revision = ? AND scope = ?",
                (project_id, revision, scope),
            ).fetchone()
            if existing is not None:
                if existing["revision_sha256"] != revision_sha256:
                    raise StoreError(
                        "La aprobación existente no coincide con la revisión."
                    )
                return self._approval_from_row(existing), False

            approval_id = f"apr_{uuid.uuid4().hex}"
            try:
                connection.execute(
                    "INSERT INTO approvals("
                    "id, project_id, revision, revision_sha256, scope, "
                    "approved_by, note, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        approval_id,
                        project_id,
                        revision,
                        revision_sha256,
                        scope,
                        approved_by,
                        note,
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise StoreError(
                    "No se pudo registrar la aprobación en el almacén."
                ) from error

            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (timestamp, project_id),
            )

        return (
            ApprovalRecord(
                id=approval_id,
                project_id=project_id,
                revision=revision,
                revision_sha256=revision_sha256,
                scope=scope,
                approved_by=approved_by,
                note=note,
                created_at=timestamp,
            ),
            True,
        )

    def list_approvals(self, project_id: str) -> list[ApprovalRecord]:
        self.get_project(project_id)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, project_id, revision, revision_sha256, scope, "
                "approved_by, note, created_at "
                "FROM approvals WHERE project_id = ? "
                "ORDER BY created_at ASC, id ASC",
                (project_id,),
            ).fetchall()
        return [self._approval_from_row(row) for row in rows]

    def get_approval(self, project_id: str, approval_id: str) -> ApprovalRecord:
        self.get_project(project_id)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT id, project_id, revision, revision_sha256, scope, "
                "approved_by, note, created_at "
                "FROM approvals WHERE project_id = ? AND id = ?",
                (project_id, approval_id),
            ).fetchone()
        if row is None:
            raise ApprovalNotFoundError(project_id, approval_id)
        return self._approval_from_row(row)

    def approval_snapshot(
        self,
        project_id: str,
        approval_id: str | None = None,
    ) -> tuple[ProjectRecord, RevisionRecord | None, list[ApprovalRecord]]:
        with self._connection() as connection:
            connection.execute("BEGIN")
            project_row = connection.execute(
                "SELECT id, name, current_revision, created_at, updated_at "
                "FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if project_row is None:
                raise ProjectNotFoundError(project_id)
            project = self._project_from_row(project_row)

            current_revision = None
            if project.current_revision > 0:
                revision_row = connection.execute(
                    "SELECT project_id, revision, spec_json, sha256, created_at "
                    "FROM revisions WHERE project_id = ? AND revision = ?",
                    (project_id, project.current_revision),
                ).fetchone()
                if revision_row is None:
                    raise CadspecNotFoundError(project_id)
                current_revision = self._revision_from_row(revision_row)

            if approval_id is None:
                rows = connection.execute(
                    "SELECT id, project_id, revision, revision_sha256, scope, "
                    "approved_by, note, created_at "
                    "FROM approvals WHERE project_id = ? "
                    "ORDER BY created_at ASC, id ASC",
                    (project_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id, project_id, revision, revision_sha256, scope, "
                    "approved_by, note, created_at "
                    "FROM approvals WHERE project_id = ? AND id = ?",
                    (project_id, approval_id),
                ).fetchall()
                if not rows:
                    raise ApprovalNotFoundError(project_id, approval_id)
            approvals = [self._approval_from_row(row) for row in rows]
        return project, current_revision, approvals
