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
    BuildApprovalConsumedError,
    BuildApprovalExpiredError,
    BuildApprovalNotFoundError,
    BuildApprovalStaleError,
    BuildDestinationMismatchError,
    BuildJobConflictError,
    BuildJobNotFoundError,
    CadspecNotFoundError,
    ProjectNotFoundError,
    RevisionConflictError,
    SourceNotFoundError,
    StoreClosedError,
    StoreError,
)
from .naming import validate_project_name
from .sources import source_media_type

SCHEMA_VERSION = 5
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

_SCHEMA_V5 = """
CREATE TABLE IF NOT EXISTS build_approvals (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    revision_sha256 TEXT NOT NULL
        CHECK (
            length(revision_sha256) = 64
            AND revision_sha256 NOT GLOB '*[^0-9a-f]*'
        ),
    scope TEXT NOT NULL CHECK (scope IN ('build')),
    approved_by TEXT NOT NULL
        CHECK (
            length(trim(approved_by)) > 0
            AND length(approved_by) <= 120
        ),
    note TEXT CHECK (note IS NULL OR length(note) <= 2000),
    destination TEXT NOT NULL
        CHECK (length(destination) > 0 AND length(destination) <= 512),
    destination_hash TEXT NOT NULL
        CHECK (
            length(destination_hash) = 64
            AND destination_hash NOT GLOB '*[^0-9a-f]*'
        ),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL CHECK (expires_at > created_at),
    FOREIGN KEY (project_id, revision)
        REFERENCES revisions(project_id, revision)
);

CREATE TRIGGER IF NOT EXISTS build_approvals_immutable_update
BEFORE UPDATE ON build_approvals
BEGIN
    SELECT RAISE(ABORT, 'build approvals are immutable');
END;

CREATE TRIGGER IF NOT EXISTS build_approvals_immutable_delete
BEFORE DELETE ON build_approvals
BEGIN
    SELECT RAISE(ABORT, 'build approvals are immutable');
END;

CREATE TRIGGER IF NOT EXISTS build_approvals_immutable_insert
BEFORE INSERT ON build_approvals
WHEN EXISTS (SELECT 1 FROM build_approvals WHERE id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'build approvals are immutable');
END;

CREATE TABLE IF NOT EXISTS build_jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    revision_sha256 TEXT NOT NULL
        CHECK (
            length(revision_sha256) = 64
            AND revision_sha256 NOT GLOB '*[^0-9a-f]*'
        ),
    approval_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL
        CHECK (length(idempotency_key) BETWEEN 8 AND 128),
    destination TEXT NOT NULL
        CHECK (length(destination) > 0 AND length(destination) <= 512),
    destination_hash TEXT NOT NULL
        CHECK (
            length(destination_hash) = 64
            AND destination_hash NOT GLOB '*[^0-9a-f]*'
        ),
    state TEXT NOT NULL
        CHECK (state IN ('queued', 'running', 'completed', 'failed')),
    attempt INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    error_code TEXT
        CHECK (error_code IS NULL OR length(error_code) BETWEEN 1 AND 80),
    error_message TEXT
        CHECK (error_message IS NULL OR length(error_message) <= 500),
    artifact_name TEXT
        CHECK (artifact_name IS NULL OR length(artifact_name) <= 512),
    artifact_sha256 TEXT
        CHECK (
            artifact_sha256 IS NULL
            OR (
                length(artifact_sha256) = 64
                AND artifact_sha256 NOT GLOB '*[^0-9a-f]*'
            )
        ),
    artifact_byte_size INTEGER
        CHECK (artifact_byte_size IS NULL OR artifact_byte_size >= 0),
    UNIQUE (project_id, idempotency_key),
    FOREIGN KEY (project_id, revision)
        REFERENCES revisions(project_id, revision),
    FOREIGN KEY (approval_id) REFERENCES build_approvals(id)
);

CREATE TRIGGER IF NOT EXISTS build_jobs_immutable_identity
BEFORE UPDATE ON build_jobs
WHEN OLD.id != NEW.id
    OR OLD.project_id != NEW.project_id
    OR OLD.revision != NEW.revision
    OR OLD.revision_sha256 != NEW.revision_sha256
    OR OLD.approval_id != NEW.approval_id
    OR OLD.idempotency_key != NEW.idempotency_key
    OR OLD.destination != NEW.destination
    OR OLD.destination_hash != NEW.destination_hash
    OR OLD.created_at != NEW.created_at
BEGIN
    SELECT RAISE(ABORT, 'build job identity is immutable');
END;

CREATE TRIGGER IF NOT EXISTS build_jobs_immutable_insert
BEFORE INSERT ON build_jobs
WHEN EXISTS (SELECT 1 FROM build_jobs WHERE id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'build jobs are append-only');
END;

CREATE TRIGGER IF NOT EXISTS build_jobs_immutable_delete
BEFORE DELETE ON build_jobs
BEGIN
    SELECT RAISE(ABORT, 'build jobs are append-only');
END;

CREATE TABLE IF NOT EXISTS build_consumptions (
    approval_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE,
    consumed_at TEXT NOT NULL,
    FOREIGN KEY (approval_id) REFERENCES build_approvals(id),
    FOREIGN KEY (job_id) REFERENCES build_jobs(id)
);

CREATE TRIGGER IF NOT EXISTS build_consumptions_immutable_update
BEFORE UPDATE ON build_consumptions
BEGIN
    SELECT RAISE(ABORT, 'build consumptions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS build_consumptions_immutable_delete
BEFORE DELETE ON build_consumptions
BEGIN
    SELECT RAISE(ABORT, 'build consumptions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS build_consumptions_immutable_insert
BEFORE INSERT ON build_consumptions
WHEN EXISTS (
    SELECT 1 FROM build_consumptions WHERE approval_id = NEW.approval_id
)
OR EXISTS (SELECT 1 FROM build_consumptions WHERE job_id = NEW.job_id)
BEGIN
    SELECT RAISE(ABORT, 'build consumptions are immutable');
END;

CREATE INDEX IF NOT EXISTS idx_build_approvals_project
ON build_approvals (project_id, created_at, id);

CREATE INDEX IF NOT EXISTS idx_build_jobs_project
ON build_jobs (project_id, created_at, id);

CREATE INDEX IF NOT EXISTS idx_build_jobs_state
ON build_jobs (state, created_at, id);
"""

# Applied to every compatible database, including versions created before the
# anti-duplicate trigger existed. It is idempotent and does not change the file
# format version.
_SCHEMA_V5_HARDENING = """
CREATE TRIGGER IF NOT EXISTS build_jobs_immutable_insert
BEFORE INSERT ON build_jobs
WHEN EXISTS (SELECT 1 FROM build_jobs WHERE id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'build jobs are append-only');
END;
"""

_SOURCE_SELECT = """
SELECT s.id, s.project_id, s.sha256, s.kind, s.filename, s.created_at,
       a.byte_size
FROM sources AS s
JOIN artifacts AS a ON a.sha256 = s.sha256
"""

_BUILD_APPROVAL_SELECT = """
SELECT id, project_id, revision, revision_sha256, scope, approved_by, note,
       destination, destination_hash, created_at, expires_at
FROM build_approvals
"""

_BUILD_JOB_SELECT = """
SELECT id, project_id, revision, revision_sha256, approval_id,
       idempotency_key, destination, destination_hash, state, attempt,
       created_at, updated_at, started_at, finished_at, error_code,
       error_message, artifact_name, artifact_sha256, artifact_byte_size
FROM build_jobs
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def format_timestamp(value: datetime) -> str:
    """Return a canonical UTC timestamp with microsecond precision."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


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


@dataclass(frozen=True)
class BuildApprovalRecord:
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


@dataclass(frozen=True)
class BuildConsumptionRecord:
    approval_id: str
    job_id: str
    consumed_at: str


@dataclass(frozen=True)
class BuildJobRecord:
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

            if version == 4:
                connection.executescript(_SCHEMA_V5)
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                    "VALUES (?, ?)",
                    (5, _utc_now()),
                )
                connection.execute("PRAGMA user_version = 5")
                connection.execute("COMMIT")
                version = 5

            if version != SCHEMA_VERSION:
                raise StoreError(
                    "La versión del esquema SQLite no es compatible."
                )
            connection.executescript(_SCHEMA_V5_HARDENING)
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

    @staticmethod
    def _build_approval_from_row(row: sqlite3.Row) -> BuildApprovalRecord:
        return BuildApprovalRecord(
            id=row["id"],
            project_id=row["project_id"],
            revision=int(row["revision"]),
            revision_sha256=row["revision_sha256"],
            scope=row["scope"],
            approved_by=row["approved_by"],
            note=row["note"],
            destination=row["destination"],
            destination_hash=row["destination_hash"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
        )

    @staticmethod
    def _build_job_from_row(row: sqlite3.Row) -> BuildJobRecord:
        return BuildJobRecord(
            id=row["id"],
            project_id=row["project_id"],
            revision=int(row["revision"]),
            revision_sha256=row["revision_sha256"],
            approval_id=row["approval_id"],
            idempotency_key=row["idempotency_key"],
            destination=row["destination"],
            destination_hash=row["destination_hash"],
            state=row["state"],
            attempt=int(row["attempt"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            artifact_name=row["artifact_name"],
            artifact_sha256=row["artifact_sha256"],
            artifact_byte_size=(
                None
                if row["artifact_byte_size"] is None
                else int(row["artifact_byte_size"])
            ),
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

    # -- Build approvals, atomic consumption and job records ---------------

    def save_build_approval(
        self,
        *,
        project_id: str,
        revision: int,
        revision_sha256: str,
        approved_by: str,
        note: str | None,
        destination: str,
        destination_hash: str,
        created_at: str,
        expires_at: str,
    ) -> BuildApprovalRecord:
        """Insert an append-only build approval bound to the current revision."""

        with self._connection(write=True) as connection:
            project_row = connection.execute(
                "SELECT current_revision FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if project_row is None:
                raise ProjectNotFoundError(project_id)
            current_revision = int(project_row["current_revision"])
            if current_revision != revision:
                raise BuildApprovalStaleError(
                    project_id,
                    revision,
                    current_revision=current_revision,
                )

            revision_row = connection.execute(
                "SELECT sha256 FROM revisions "
                "WHERE project_id = ? AND revision = ?",
                (project_id, revision),
            ).fetchone()
            if revision_row is None:
                raise CadspecNotFoundError(project_id)
            if revision_row["sha256"] != revision_sha256:
                raise BuildApprovalStaleError(
                    project_id,
                    revision,
                    current_revision=current_revision,
                )

            approval_id = f"bapr_{uuid.uuid4().hex}"
            try:
                connection.execute(
                    "INSERT INTO build_approvals("
                    "id, project_id, revision, revision_sha256, scope, "
                    "approved_by, note, destination, destination_hash, "
                    "created_at, expires_at) "
                    "VALUES (?, ?, ?, ?, 'build', ?, ?, ?, ?, ?, ?)",
                    (
                        approval_id,
                        project_id,
                        revision,
                        revision_sha256,
                        approved_by,
                        note,
                        destination,
                        destination_hash,
                        created_at,
                        expires_at,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise StoreError(
                    "No se pudo registrar la aprobación de construcción."
                ) from error

        return BuildApprovalRecord(
            id=approval_id,
            project_id=project_id,
            revision=revision,
            revision_sha256=revision_sha256,
            scope="build",
            approved_by=approved_by,
            note=note,
            destination=destination,
            destination_hash=destination_hash,
            created_at=created_at,
            expires_at=expires_at,
        )

    def build_approval_snapshot(
        self,
        project_id: str,
        approval_id: str | None = None,
    ) -> tuple[
        ProjectRecord,
        RevisionRecord | None,
        list[BuildApprovalRecord],
        dict[str, BuildConsumptionRecord],
    ]:
        """Read project, current revision, build approvals and consumption."""

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
                    f"{_BUILD_APPROVAL_SELECT} WHERE project_id = ? "
                    "ORDER BY created_at ASC, id ASC",
                    (project_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    f"{_BUILD_APPROVAL_SELECT} WHERE project_id = ? AND id = ?",
                    (project_id, approval_id),
                ).fetchall()
                if not rows:
                    raise BuildApprovalNotFoundError(project_id, approval_id)

            approvals = [self._build_approval_from_row(row) for row in rows]
            consumptions: dict[str, BuildConsumptionRecord] = {}
            if approvals:
                placeholders = ",".join("?" for _ in approvals)
                consumption_rows = connection.execute(
                    "SELECT approval_id, job_id, consumed_at "
                    "FROM build_consumptions "
                    f"WHERE approval_id IN ({placeholders})",
                    tuple(approval.id for approval in approvals),
                ).fetchall()
                consumptions = {
                    row["approval_id"]: BuildConsumptionRecord(
                        approval_id=row["approval_id"],
                        job_id=row["job_id"],
                        consumed_at=row["consumed_at"],
                    )
                    for row in consumption_rows
                }
        return project, current_revision, approvals, consumptions

    def list_build_approvals(self, project_id: str) -> list[BuildApprovalRecord]:
        _, _, approvals, _ = self.build_approval_snapshot(project_id)
        return approvals

    def get_build_approval(
        self,
        project_id: str,
        approval_id: str,
    ) -> BuildApprovalRecord:
        _, _, approvals, _ = self.build_approval_snapshot(project_id, approval_id)
        return approvals[0]

    def get_build_consumption(
        self,
        approval_id: str,
    ) -> BuildConsumptionRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT approval_id, job_id, consumed_at "
                "FROM build_consumptions WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        if row is None:
            return None
        return BuildConsumptionRecord(
            approval_id=row["approval_id"],
            job_id=row["job_id"],
            consumed_at=row["consumed_at"],
        )

    def enqueue_build_job(
        self,
        *,
        project_id: str,
        approval_id: str,
        idempotency_key: str,
        destination: str,
        destination_hash: str,
        now: str,
    ) -> tuple[BuildJobRecord, bool]:
        """Consume a build approval and enqueue one job atomically.

        The approval row is never updated. A ``build_consumptions`` row and a
        ``build_jobs`` row are inserted in the same ``BEGIN IMMEDIATE``
        transaction, so two concurrent consumers cannot both succeed.
        """

        with self._connection(write=True) as connection:
            existing = connection.execute(
                f"{_BUILD_JOB_SELECT} "
                "WHERE project_id = ? AND idempotency_key = ?",
                (project_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                if (
                    existing["approval_id"] != approval_id
                    or existing["destination_hash"] != destination_hash
                ):
                    raise BuildJobConflictError(
                        "La clave de idempotencia ya pertenece a otro trabajo.",
                        reason="idempotency_key",
                    )
                return self._build_job_from_row(existing), False

            project_row = connection.execute(
                "SELECT current_revision FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if project_row is None:
                raise ProjectNotFoundError(project_id)

            approval_row = connection.execute(
                f"{_BUILD_APPROVAL_SELECT} WHERE project_id = ? AND id = ?",
                (project_id, approval_id),
            ).fetchone()
            if approval_row is None:
                raise BuildApprovalNotFoundError(project_id, approval_id)
            approval = self._build_approval_from_row(approval_row)

            current_revision = int(project_row["current_revision"])
            revision_row = connection.execute(
                "SELECT sha256 FROM revisions "
                "WHERE project_id = ? AND revision = ?",
                (project_id, approval.revision),
            ).fetchone()
            if revision_row is None:
                raise CadspecNotFoundError(project_id)
            if (
                current_revision != approval.revision
                or revision_row["sha256"] != approval.revision_sha256
            ):
                raise BuildApprovalStaleError(
                    project_id,
                    approval.revision,
                    current_revision=current_revision,
                )

            if destination_hash != approval.destination_hash:
                raise BuildDestinationMismatchError(project_id, approval_id)

            consumption_row = connection.execute(
                "SELECT approval_id FROM build_consumptions "
                "WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if consumption_row is not None:
                raise BuildApprovalConsumedError(project_id, approval_id)

            if now >= approval.expires_at:
                raise BuildApprovalExpiredError(project_id, approval_id)

            job_id = f"job_{uuid.uuid4().hex}"
            try:
                connection.execute(
                    "INSERT INTO build_jobs("
                    "id, project_id, revision, revision_sha256, approval_id, "
                    "idempotency_key, destination, destination_hash, state, "
                    "attempt, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', 1, ?, ?)",
                    (
                        job_id,
                        project_id,
                        approval.revision,
                        approval.revision_sha256,
                        approval_id,
                        idempotency_key,
                        destination,
                        destination_hash,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    "INSERT INTO build_consumptions("
                    "approval_id, job_id, consumed_at) VALUES (?, ?, ?)",
                    (approval_id, job_id, now),
                )
            except sqlite3.IntegrityError as error:
                raise StoreError(
                    "No se pudo registrar el consumo de la aprobación."
                ) from error

            job_row = connection.execute(
                f"{_BUILD_JOB_SELECT} WHERE id = ?",
                (job_id,),
            ).fetchone()
            if job_row is None:  # pragma: no cover - defensive
                raise StoreError("El trabajo encolado no se pudo leer.")

        return self._build_job_from_row(job_row), True

    def list_build_jobs(self, project_id: str) -> list[BuildJobRecord]:
        self.get_project(project_id)
        with self._connection() as connection:
            rows = connection.execute(
                f"{_BUILD_JOB_SELECT} WHERE project_id = ? "
                "ORDER BY created_at ASC, id ASC",
                (project_id,),
            ).fetchall()
        return [self._build_job_from_row(row) for row in rows]

    def get_build_job(self, project_id: str, job_id: str) -> BuildJobRecord:
        self.get_project(project_id)
        with self._connection() as connection:
            row = connection.execute(
                f"{_BUILD_JOB_SELECT} WHERE project_id = ? AND id = ?",
                (project_id, job_id),
            ).fetchone()
        if row is None:
            raise BuildJobNotFoundError(project_id, job_id)
        return self._build_job_from_row(row)

    def get_build_job_by_idempotency(
        self,
        project_id: str,
        idempotency_key: str,
    ) -> BuildJobRecord | None:
        self.get_project(project_id)
        with self._connection() as connection:
            row = connection.execute(
                f"{_BUILD_JOB_SELECT} "
                "WHERE project_id = ? AND idempotency_key = ?",
                (project_id, idempotency_key),
            ).fetchone()
        return None if row is None else self._build_job_from_row(row)

    def list_build_jobs_in_states(
        self,
        states: tuple[str, ...],
    ) -> list[BuildJobRecord]:
        """List jobs in the requested durable states across all projects."""

        allowed = {"queued", "running", "completed", "failed"}
        if not states or any(state not in allowed for state in states):
            raise ValueError("Estado de trabajo de construcción no válido.")
        placeholders = ",".join("?" for _ in states)
        with self._connection() as connection:
            rows = connection.execute(
                f"{_BUILD_JOB_SELECT} WHERE state IN ({placeholders}) "
                "ORDER BY created_at ASC, id ASC",
                tuple(states),
            ).fetchall()
        return [self._build_job_from_row(row) for row in rows]

    def record_build_job_artifact(
        self,
        job_id: str,
        *,
        now: str,
        artifact_name: str,
        artifact_sha256: str,
        artifact_byte_size: int,
    ) -> BuildJobRecord | None:
        """Persist the prepared artifact metadata before publication.

        Only a ``running`` job can accept prepared metadata. Recording it
        before the file is published makes a later crash or ``finish`` failure
        recoverable: the worker can compare the final file with this hash
        instead of rebuilding it.
        """

        with self._connection(write=True) as connection:
            row = connection.execute(
                f"{_BUILD_JOB_SELECT} WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None or row["state"] != "running":
                return None
            connection.execute(
                "UPDATE build_jobs SET updated_at = ?, artifact_name = ?, "
                "artifact_sha256 = ?, artifact_byte_size = ? "
                "WHERE id = ? AND state = 'running'",
                (
                    now,
                    artifact_name,
                    artifact_sha256,
                    artifact_byte_size,
                    job_id,
                ),
            )
            updated = connection.execute(
                f"{_BUILD_JOB_SELECT} WHERE id = ?",
                (job_id,),
            ).fetchone()
        return None if updated is None else self._build_job_from_row(updated)

    def finalize_recovered_build_job(
        self,
        job_id: str,
        *,
        now: str,
        artifact_sha256: str,
        artifact_byte_size: int | None,
    ) -> BuildJobRecord | None:
        """Mark an already-published artifact as completed without rebuilding.

        The update only succeeds when the durable metadata still matches the
        prepared artifact, so another process cannot silently relabel a
        different or partial file.
        """

        with self._connection(write=True) as connection:
            row = connection.execute(
                f"{_BUILD_JOB_SELECT} WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            if row["state"] not in {"running", "failed"}:
                return self._build_job_from_row(row)
            if (
                row["artifact_sha256"] != artifact_sha256
                or row["artifact_byte_size"] != artifact_byte_size
            ):
                return self._build_job_from_row(row)
            connection.execute(
                "UPDATE build_jobs SET state = 'completed', finished_at = ?, "
                "updated_at = ?, error_code = NULL, error_message = NULL "
                "WHERE id = ? AND state IN ('running', 'failed') "
                "AND artifact_sha256 = ? AND artifact_byte_size IS ?",
                (
                    now,
                    now,
                    job_id,
                    artifact_sha256,
                    artifact_byte_size,
                ),
            )
            updated = connection.execute(
                f"{_BUILD_JOB_SELECT} WHERE id = ?",
                (job_id,),
            ).fetchone()
        return None if updated is None else self._build_job_from_row(updated)

    def start_build_job(self, job_id: str, *, now: str) -> BuildJobRecord | None:
        """Move a queued job to ``running``; return ``None`` if unknown."""

        with self._connection(write=True) as connection:
            row = connection.execute(
                f"{_BUILD_JOB_SELECT} WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            if row["state"] != "queued":
                return None
            connection.execute(
                "UPDATE build_jobs SET state = 'running', started_at = ?, "
                "updated_at = ?, finished_at = NULL, error_code = NULL, "
                "error_message = NULL WHERE id = ? AND state = 'queued'",
                (now, now, job_id),
            )
            updated = connection.execute(
                f"{_BUILD_JOB_SELECT} WHERE id = ?",
                (job_id,),
            ).fetchone()
        return None if updated is None else self._build_job_from_row(updated)

    def finish_build_job(
        self,
        job_id: str,
        *,
        state: str,
        now: str,
        error_code: str | None = None,
        error_message: str | None = None,
        artifact_name: str | None = None,
        artifact_sha256: str | None = None,
        artifact_byte_size: int | None = None,
    ) -> BuildJobRecord:
        if state not in {"completed", "failed"}:
            raise ValueError("Estado final de trabajo no válido.")
        with self._connection(write=True) as connection:
            row = connection.execute(
                f"{_BUILD_JOB_SELECT} WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise StoreError("El trabajo de construcción no existe.")
            if row["state"] != "running":
                return self._build_job_from_row(row)
            connection.execute(
                "UPDATE build_jobs SET state = ?, finished_at = ?, "
                "updated_at = ?, error_code = ?, error_message = ?, "
                "artifact_name = ?, artifact_sha256 = ?, "
                "artifact_byte_size = ? WHERE id = ? AND state = 'running'",
                (
                    state,
                    now,
                    now,
                    error_code,
                    error_message,
                    artifact_name,
                    artifact_sha256,
                    artifact_byte_size,
                    job_id,
                ),
            )
            updated = connection.execute(
                f"{_BUILD_JOB_SELECT} WHERE id = ?",
                (job_id,),
            ).fetchone()
        if updated is None:  # pragma: no cover - defensive
            raise StoreError("El trabajo de construcción no se pudo leer.")
        return self._build_job_from_row(updated)

    def requeue_build_job(
        self,
        project_id: str,
        job_id: str,
        *,
        now: str,
    ) -> tuple[BuildJobRecord, bool]:
        """Requeue a failed job without touching its approval consumption."""

        with self._connection(write=True) as connection:
            row = connection.execute(
                f"{_BUILD_JOB_SELECT} WHERE project_id = ? AND id = ?",
                (project_id, job_id),
            ).fetchone()
            if row is None:
                raise BuildJobNotFoundError(project_id, job_id)
            current = self._build_job_from_row(row)
            if current.state != "failed":
                return current, False

            connection.execute(
                "UPDATE build_jobs SET state = 'queued', attempt = attempt + 1, "
                "updated_at = ?, started_at = NULL, finished_at = NULL, "
                "error_code = NULL, error_message = NULL, artifact_name = NULL, "
                "artifact_sha256 = NULL, artifact_byte_size = NULL "
                "WHERE id = ? AND state = 'failed'",
                (now, job_id),
            )
            updated = connection.execute(
                f"{_BUILD_JOB_SELECT} WHERE id = ?",
                (job_id,),
            ).fetchone()
        if updated is None:  # pragma: no cover - defensive
            raise StoreError("El trabajo de construcción no se pudo leer.")
        return self._build_job_from_row(updated), True
