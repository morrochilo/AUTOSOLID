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
    CadspecNotFoundError,
    ProjectNotFoundError,
    RevisionConflictError,
    StoreClosedError,
    StoreError,
)
from .naming import validate_project_name

SCHEMA_VERSION = 1
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
                    (SCHEMA_VERSION, _utc_now()),
                )
                connection.execute("PRAGMA user_version = 1")
                connection.execute("COMMIT")
            elif version != SCHEMA_VERSION:
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
