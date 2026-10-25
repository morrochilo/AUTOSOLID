import hashlib
import sqlite3

import pytest

from autosolid.artifacts import ArtifactStore, ArtifactStoreError
from autosolid.projects import (
    SCHEMA_VERSION,
    InvalidSourceError,
    ProjectNotFoundError,
    ProjectService,
    ProjectStore,
    SourceNotFoundError,
    SourceTooLargeError,
    StoreError,
)
from autosolid.projects.store import _SCHEMA_V1


def pdf_bytes(marker: bytes = b"1") -> bytes:
    return b"%PDF-1.7\n%" + marker + b"\n%%EOF\n"


def text_bytes(value: str = "Cota 40 mm") -> bytes:
    return value.encode("utf-8")


@pytest.fixture
def service(tmp_path):
    store = ProjectStore(tmp_path / "data")
    project = store.create_project("Fuentes")
    yield ProjectService(store), store, project
    store.close()


def test_add_list_read_and_persist_source(service, tmp_path):
    project_service, store, project = service
    data = pdf_bytes()
    source, created = project_service.add_source(
        project.id,
        "  Plano principal.PDF  ",
        data,
    )

    assert created is True
    assert source.id.startswith("src_")
    assert source.project_id == project.id
    assert source.filename == "Plano principal.PDF"
    assert source.kind == "pdf"
    assert source.media_type == "application/pdf"
    assert source.byte_size == len(data)
    assert source.sha256 == hashlib.sha256(data).hexdigest()

    assert project_service.list_sources(project.id) == [source]
    assert project_service.get_source(project.id, source.id) == source
    stored = project_service.read_source(project.id, source.id)
    assert stored.source == source
    assert stored.data == data

    artifact_path = project_service.artifacts.path_for(source.sha256)
    assert artifact_path.read_bytes() == data
    assert project_service.list_revisions(project.id) == []

    store.close()
    reopened = ProjectService(ProjectStore(tmp_path / "data"))
    assert reopened.get_source(project.id, source.id) == source
    assert reopened.read_source(project.id, source.id).data == data
    reopened.store.close()


def test_duplicate_content_is_idempotent_per_project(service):
    project_service, _, project = service
    first, first_created = project_service.add_source(
        project.id, "plano.pdf", pdf_bytes()
    )
    second, second_created = project_service.add_source(
        project.id, "copia.pdf", pdf_bytes()
    )

    assert first_created is True
    assert second_created is False
    assert second == first
    assert len(project_service.list_sources(project.id)) == 1


def test_same_content_in_two_projects_shares_blob_but_not_source_ids(service):
    project_service, store, first_project = service
    second_project = store.create_project("Otra pieza")
    data = text_bytes()

    first, _ = project_service.add_source(first_project.id, "nota.txt", data)
    second, _ = project_service.add_source(second_project.id, "nota.txt", data)

    assert first.sha256 == second.sha256
    assert first.id != second.id
    assert first.project_id != second.project_id
    files = [
        path
        for path in project_service.artifacts.root.rglob("*")
        if path.is_file()
    ]
    assert len(files) == 1


@pytest.mark.parametrize(
    ("filename", "data", "kind", "reason"),
    [
        ("plano.exe", b"%PDF-1.7\n", None, "unsupported_extension"),
        ("plano.pdf", b"no es un pdf", None, "signature"),
        ("foto.png", b"\xff\xd8\xffrest", None, "signature"),
        ("nota.txt", b"\xff\xfe\x00", None, "encoding"),
        ("nota.txt", b"texto\x00oculto", None, "encoding"),
        ("vacio.pdf", b"", None, "empty"),
        ("plano.pdf", b"%PDF-1.7\n", "image", "kind_mismatch"),
        ("plano.pdf", b"%PDF-1.7\n", "video", "unsupported_kind"),
    ],
)
def test_invalid_sources_are_rejected_without_persistence(
    service, filename, data, kind, reason
):
    project_service, _, project = service
    with pytest.raises(InvalidSourceError) as error:
        project_service.add_source(project.id, filename, data, kind=kind)
    assert error.value.reason == reason
    assert project_service.list_sources(project.id) == []
    assert not project_service.artifacts.root.exists()


@pytest.mark.parametrize(
    "filename",
    [
        "",
        "   ",
        "../plano.pdf",
        "carpeta\\plano.pdf",
        "plano\x00.pdf",
        "x" * 201 + ".pdf",
        ".",
        "..",
    ],
)
def test_invalid_filenames_are_rejected(service, filename):
    project_service, _, project = service
    with pytest.raises(InvalidSourceError) as error:
        project_service.add_source(project.id, filename, pdf_bytes())
    assert error.value.reason == "filename"
    assert project_service.list_sources(project.id) == []


def test_source_size_limit_is_enforced_before_writing(tmp_path):
    store = ProjectStore(tmp_path / "data")
    project = store.create_project("Límite")
    project_service = ProjectService(store, max_source_bytes=16)

    with pytest.raises(SourceTooLargeError) as error:
        project_service.add_source(project.id, "plano.pdf", pdf_bytes(b"x" * 32))

    assert error.value.limit_bytes == 16
    assert error.value.actual_bytes == len(pdf_bytes(b"x" * 32))
    assert project_service.list_sources(project.id) == []
    assert not project_service.artifacts.root.exists()
    store.close()


def test_supported_images_and_text_are_stored(service):
    project_service, _, project = service
    samples = [
        ("foto.png", b"\x89PNG\r\n\x1a\nrest", "image", "image/png"),
        ("foto.jpg", b"\xff\xd8\xffrest", "image", "image/jpeg"),
        ("foto.webp", b"RIFF\x04\x00\x00\x00WEBPrest", "image", "image/webp"),
        ("nota.md", text_bytes("# Nota"), "text", "text/plain"),
        ("datos.json", text_bytes('{"cota": 40}'), "text", "text/plain"),
    ]

    for filename, data, kind, media_type in samples:
        source, created = project_service.add_source(
            project.id, filename, data
        )
        assert created is True
        assert source.kind == kind
        assert source.media_type == media_type
        assert project_service.read_source(project.id, source.id).data == data


def test_missing_projects_and_sources_have_stable_errors(service):
    project_service, _, project = service
    with pytest.raises(ProjectNotFoundError):
        project_service.add_source("prj_missing", "plano.pdf", pdf_bytes())
    with pytest.raises(ProjectNotFoundError):
        project_service.list_sources("prj_missing")
    with pytest.raises(SourceNotFoundError):
        project_service.get_source(project.id, "src_missing")
    with pytest.raises(SourceNotFoundError):
        project_service.read_source(project.id, "src_missing")


def test_corrupt_artifact_is_detected_and_can_be_repaired(service, tmp_path):
    project_service, _, project = service
    data = pdf_bytes()
    source, _ = project_service.add_source(project.id, "plano.pdf", data)
    artifact_path = project_service.artifacts.path_for(source.sha256)
    artifact_path.write_bytes(b"%PDF-1.7\ncorrupto\n")

    with pytest.raises(StoreError) as error:
        project_service.read_source(project.id, source.id)
    assert str(tmp_path) not in str(error.value)

    repaired, created = project_service.add_source(
        project.id, "plano.pdf", data
    )
    assert created is False
    assert repaired == source
    assert project_service.read_source(project.id, source.id).data == data


def test_source_metadata_is_immutable(service):
    project_service, store, project = service
    source, _ = project_service.add_source(project.id, "plano.pdf", pdf_bytes())

    with sqlite3.connect(store.database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE sources SET filename = ? WHERE id = ?",
                ("otro.pdf", source.id),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "DELETE FROM sources WHERE id = ?", (source.id,)
            )


def test_v1_database_migrates_to_current_schema(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database_path = data_dir / "autosolid.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(_SCHEMA_V1)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (1, 'old')"
        )
        connection.execute("PRAGMA user_version = 1")
        connection.commit()

    store = ProjectStore(data_dir)
    project = store.create_project("Migrado")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall() == [(1,), (2,), (3,), (4,)]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"artifacts", "sources", "approvals"}.issubset(tables)
    assert store.list_sources(project.id) == []
    assert store.list_approvals(project.id) == []
    store.close()


def test_artifact_store_rejects_invalid_identifiers(tmp_path):
    artifacts = ArtifactStore(tmp_path / "data")
    with pytest.raises(ArtifactStoreError):
        artifacts.path_for("../escape")
    with pytest.raises(ArtifactStoreError):
        artifacts.read("0" * 64)
