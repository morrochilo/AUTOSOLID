import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from autosolid.projects import ProjectService, ProjectStore
from tests.builders import revolve_spec


def _approved_project(service, project_id):
    spec = revolve_spec().model_dump(mode="json")
    spec["project_id"] = project_id
    stored = service.save_cadspec(project_id, 0, spec)
    approval, created = service.approve_revision(
        project_id, 1, stored.sha256, "Revisor"
    )
    assert created is True
    return spec, stored, approval


def test_audit_approval_status_uses_one_snapshot(tmp_path):
    store = ProjectStore(tmp_path / "data")
    service = ProjectService(store)
    project = service.create_project("Carrera")
    spec, _, _ = _approved_project(service, project.id)

    original_snapshot = store.approval_snapshot
    paused = Event()
    resume = Event()

    def list_after_snapshot(project_id, approval_id=None):
        result = original_snapshot(project_id, approval_id)
        if approval_id is None:
            paused.set()
            assert resume.wait(timeout=5)
        return result

    store.approval_snapshot = list_after_snapshot
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(service.list_approvals, project.id)
            assert paused.wait(timeout=5)
            second = service.save_cadspec(project.id, 1, spec)
            service.approve_revision(project.id, 2, second.sha256, "Revisor 2")
            resume.set()
            raced = future.result(timeout=5)
        statuses = [(item.revision, item.status) for item in raced]
        assert statuses != [(1, "valid"), (2, "stale")]
        fresh = service.list_approvals(project.id)
        assert [(item.revision, item.status) for item in fresh] == [
            (1, "stale"),
            (2, "valid"),
        ]
    finally:
        resume.set()
        store.approval_snapshot = original_snapshot
        store.close()


def test_audit_insert_or_replace_cannot_rewrite_approval(tmp_path):
    store = ProjectStore(tmp_path / "data")
    service = ProjectService(store)
    project = service.create_project("Inmutable")
    _, _, approval = _approved_project(service, project.id)

    connection = sqlite3.connect(store.database_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT OR REPLACE INTO approvals("
                "id, project_id, revision, revision_sha256, scope, "
                "approved_by, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    approval.id,
                    project.id,
                    approval.revision,
                    approval.revision_sha256,
                    approval.scope,
                    "Sustituido",
                    None,
                    approval.created_at,
                ),
            )
    finally:
        connection.close()
        store.close()


@pytest.mark.parametrize(
    ("first_name", "second_name"),
    [("plano.pdf", "nota.txt"), ("nota.txt", "plano.pdf")],
)
def test_audit_blob_deduplication_is_independent_of_filename(
    tmp_path, first_name, second_name
):
    store = ProjectStore(tmp_path / "data")
    service = ProjectService(store)
    first_project = service.create_project("Primero")
    second_project = service.create_project("Segundo")
    content = b"%PDF-1.7\ntexto visible\n"

    first, _ = service.add_source(first_project.id, first_name, content)
    second, _ = service.add_source(second_project.id, second_name, content)

    assert first.sha256 == second.sha256
    assert first.id != second.id
    store.close()


def test_audit_insert_or_replace_is_blocked_in_every_append_only_table(tmp_path):
    store = ProjectStore(tmp_path / "data")
    service = ProjectService(store)
    project = service.create_project("Todas las tablas")
    spec, revision, _ = _approved_project(service, project.id)
    source, _ = service.add_source(project.id, "plano.pdf", b"%PDF-1.7\ntexto\n")
    artifact = store.get_artifact(source.sha256)

    statements = [
        (
            "INSERT OR REPLACE INTO revisions("
            "project_id, revision, spec_json, sha256, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (project.id, 1, "{}", revision.sha256, revision.created_at),
        ),
        (
            "INSERT OR REPLACE INTO artifacts("
            "sha256, byte_size, media_type, created_at) VALUES (?, ?, ?, ?)",
            (source.sha256, source.byte_size, source.media_type, artifact.created_at),
        ),
        (
            "INSERT OR REPLACE INTO sources("
            "id, project_id, sha256, kind, filename, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                source.id,
                project.id,
                source.sha256,
                source.kind,
                source.filename,
                source.created_at,
            ),
        ),
    ]
    connection = sqlite3.connect(store.database_path)
    try:
        for sql, parameters in statements:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(sql, parameters)
    finally:
        connection.close()
        store.close()
