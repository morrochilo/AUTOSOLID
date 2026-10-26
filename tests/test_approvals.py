import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from autosolid.cad.models import Question
from autosolid.projects import (
    SCHEMA_VERSION,
    ApprovalBlockedError,
    ApprovalHashMismatchError,
    ApprovalNotFoundError,
    InvalidApprovalError,
    ProjectNotFoundError,
    ProjectService,
    ProjectStore,
    RevisionConflictError,
    StoreError,
)
from autosolid.projects.store import _SCHEMA_V1, _SCHEMA_V2
from tests.builders import revolve_spec

TIMESTAMP = "2026-10-24T00:00:00.000000+00:00"


def payload_for(spec, project_id: str) -> dict:
    payload = spec.model_dump(mode="json")
    payload["project_id"] = project_id
    return payload


@pytest.fixture
def service(tmp_path):
    store = ProjectStore(tmp_path / "data")
    yield ProjectService(store), store
    store.close()


def save_revision(project_service: ProjectService, project_id: str, spec=None):
    project = project_service.get_project(project_id)
    payload = payload_for(
        revolve_spec() if spec is None else spec,
        project_id,
    )
    return project_service.save_cadspec(
        project_id,
        project.current_revision,
        payload,
    )


def test_approve_current_revision_returns_valid_record(service):
    project_service, _ = service
    project = project_service.create_project("Aprobar")
    saved = save_revision(project_service, project.id)

    approval, created = project_service.approve_revision(
        project.id,
        saved.revision,
        saved.sha256,
        "Ana Revisora",
        note="Revisado contra el plano.",
    )

    assert created is True
    assert approval.id.startswith("apr_")
    assert approval.project_id == project.id
    assert approval.revision == saved.revision
    assert approval.revision_sha256 == saved.sha256
    assert approval.scope == "design"
    assert approval.approved_by == "Ana Revisora"
    assert approval.note == "Revisado contra el plano."
    assert approval.status == "valid"
    assert approval.created_at

    assert project_service.list_approvals(project.id) == [approval]
    assert project_service.get_approval(project.id, approval.id) == approval
    assert project_service.get_project(project.id).current_revision == saved.revision
    assert project_service.get_cadspec(project.id).sha256 == saved.sha256


def test_duplicate_approval_is_idempotent(service):
    project_service, _ = service
    project = project_service.create_project("Duplicada")
    saved = save_revision(project_service, project.id)

    first, created = project_service.approve_revision(
        project.id, saved.revision, saved.sha256, "Ana"
    )
    second, created_again = project_service.approve_revision(
        project.id,
        saved.revision,
        saved.sha256,
        "Otra persona",
        note="Otra nota",
    )

    assert created is True
    assert created_again is False
    assert second == first
    assert project_service.list_approvals(project.id) == [first]


def test_new_revision_invalidates_the_previous_approval(service):
    project_service, _ = service
    project = project_service.create_project("Invalidación")
    first_revision = save_revision(project_service, project.id)
    first_approval, _ = project_service.approve_revision(
        project.id,
        first_revision.revision,
        first_revision.sha256,
        "Ana",
    )
    assert first_approval.status == "valid"

    second_revision = save_revision(project_service, project.id)
    stale = project_service.get_approval(project.id, first_approval.id)
    assert stale.status == "stale"
    assert project_service.list_approvals(project.id)[0].status == "stale"

    second_approval, created = project_service.approve_revision(
        project.id,
        second_revision.revision,
        second_revision.sha256,
        "Luis",
    )
    assert created is True
    assert second_approval.status == "valid"

    statuses = {
        approval.id: approval.status
        for approval in project_service.list_approvals(project.id)
    }
    assert statuses == {
        first_approval.id: "stale",
        second_approval.id: "valid",
    }


def test_approval_requires_the_current_revision_and_matching_hash(service):
    project_service, _ = service
    project = project_service.create_project("Carrera")
    first_revision = save_revision(project_service, project.id)
    second_revision = save_revision(project_service, project.id)

    with pytest.raises(RevisionConflictError) as conflict:
        project_service.approve_revision(
            project.id,
            first_revision.revision,
            first_revision.sha256,
            "Ana",
        )
    assert conflict.value.expected_revision == 1
    assert conflict.value.current_revision == 2

    wrong_hash = "0" * 64
    with pytest.raises(ApprovalHashMismatchError) as mismatch:
        project_service.approve_revision(
            project.id,
            second_revision.revision,
            wrong_hash,
            "Ana",
        )
    assert mismatch.value.provided_sha256 == wrong_hash
    assert mismatch.value.current_sha256 == second_revision.sha256
    assert project_service.list_approvals(project.id) == []


def test_approval_requires_a_saved_revision(service):
    project_service, _ = service
    project = project_service.create_project("Sin revisión")

    with pytest.raises(RevisionConflictError) as conflict:
        project_service.approve_revision(project.id, 1, "a" * 64, "Ana")
    assert conflict.value.expected_revision == 1
    assert conflict.value.current_revision == 0
    assert project_service.list_approvals(project.id) == []


@pytest.mark.parametrize(
    ("reason", "overrides"),
    [
        ("revision", {"revision": 0}),
        ("revision", {"revision": -1}),
        ("revision", {"revision": True}),
        ("revision", {"revision": 1.0}),
        ("revision", {"revision": "1"}),
        ("sha256", {"sha256": "a" * 63}),
        ("sha256", {"sha256": "A" * 64}),
        ("sha256", {"sha256": None}),
        ("sha256", {"sha256": 5}),
        ("scope", {"scope": "construction"}),
        ("scope", {"scope": None}),
        ("approved_by", {"approved_by": ""}),
        ("approved_by", {"approved_by": "   "}),
        ("approved_by", {"approved_by": 5}),
        ("approved_by", {"approved_by": "x" * 121}),
        ("approved_by", {"approved_by": "Nombre\x00inválido"}),
        ("note", {"note": 5}),
        ("note", {"note": "x" * 2_001}),
        ("note", {"note": "Nota\x00inválida"}),
    ],
)
def test_invalid_approval_fields_are_rejected(service, reason, overrides):
    project_service, _ = service
    project = project_service.create_project("Campos")
    saved = save_revision(project_service, project.id)
    arguments = {
        "revision": saved.revision,
        "sha256": saved.sha256,
        "approved_by": "Ana",
    }
    arguments.update(overrides)

    with pytest.raises(InvalidApprovalError) as error:
        project_service.approve_revision(project.id, **arguments)
    assert error.value.reason == reason
    assert project_service.list_approvals(project.id) == []


def test_approval_revalidates_the_stored_revision(service):
    project_service, store = service
    project = project_service.create_project("Bloqueada")
    spec = revolve_spec(
        open_questions=[
            Question(
                id="q_critical",
                text="¿Falta una cota?",
                severity="critical",
            )
        ]
    )
    spec_json = spec.model_copy(
        update={"project_id": project.id, "revision": 1}
    ).model_dump_json()
    sha256 = hashlib.sha256(spec_json.encode("utf-8")).hexdigest()

    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "INSERT INTO revisions(project_id, revision, spec_json, sha256, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (project.id, 1, spec_json, sha256, TIMESTAMP),
        )
        connection.execute(
            "UPDATE projects SET current_revision = 1 WHERE id = ?",
            (project.id,),
        )
        connection.commit()

    with pytest.raises(ApprovalBlockedError) as blocked:
        project_service.approve_revision(project.id, 1, sha256, "Ana")
    assert "QUESTION_CRITICAL_OPEN" in {
        diagnostic.code for diagnostic in blocked.value.diagnostics
    }
    assert project_service.list_approvals(project.id) == []


def test_corrupt_stored_revision_is_rejected_before_approval(service):
    project_service, store = service
    project = project_service.create_project("Corrupta")
    spec = revolve_spec()
    spec_json = spec.model_copy(
        update={"project_id": project.id, "revision": 1}
    ).model_dump_json()

    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "INSERT INTO revisions(project_id, revision, spec_json, sha256, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (project.id, 1, spec_json, "0" * 64, TIMESTAMP),
        )
        connection.execute(
            "UPDATE projects SET current_revision = 1 WHERE id = ?",
            (project.id,),
        )
        connection.commit()

    with pytest.raises(StoreError):
        project_service.approve_revision(project.id, 1, "0" * 64, "Ana")


def test_approval_records_are_immutable_in_sqlite(service):
    project_service, store = service
    project = project_service.create_project("Inmutable")
    saved = save_revision(project_service, project.id)
    approval, _ = project_service.approve_revision(
        project.id, saved.revision, saved.sha256, "Ana"
    )

    with sqlite3.connect(store.database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE approvals SET approved_by = ? WHERE id = ?",
                ("Otra", approval.id),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "DELETE FROM approvals WHERE id = ?", (approval.id,)
            )


def test_approvals_are_isolated_by_project(service):
    project_service, _ = service
    first = project_service.create_project("Primero")
    second = project_service.create_project("Segundo")
    first_revision = save_revision(project_service, first.id)
    save_revision(project_service, second.id)
    approval, _ = project_service.approve_revision(
        first.id,
        first_revision.revision,
        first_revision.sha256,
        "Ana",
    )

    assert project_service.list_approvals(second.id) == []
    with pytest.raises(ApprovalNotFoundError):
        project_service.get_approval(second.id, approval.id)
    with pytest.raises(ProjectNotFoundError):
        project_service.get_approval("prj_missing", approval.id)


def test_concurrent_duplicate_approvals_create_one_record(service):
    project_service, _ = service
    project = project_service.create_project("Concurrente")
    saved = save_revision(project_service, project.id)
    barrier = Barrier(2)

    def attempt():
        barrier.wait()
        return project_service.approve_revision(
            project.id,
            saved.revision,
            saved.sha256,
            "Ana",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt(), range(2)))

    assert sorted(created for _, created in results) == [False, True]
    assert len({approval.id for approval, _ in results}) == 1
    assert len(project_service.list_approvals(project.id)) == 1


def test_approvals_survive_reopening_the_store(service, tmp_path):
    project_service, store = service
    project = project_service.create_project("Persistente")
    saved = save_revision(project_service, project.id)
    approval, _ = project_service.approve_revision(
        project.id, saved.revision, saved.sha256, "Ana"
    )
    store.close()

    reopened_store = ProjectStore(tmp_path / "data")
    reopened_service = ProjectService(reopened_store)
    try:
        assert reopened_service.get_approval(project.id, approval.id) == approval
        assert reopened_service.list_approvals(project.id) == [approval]
    finally:
        reopened_store.close()


def test_v2_database_migrates_to_current_schema(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database_path = data_dir / "autosolid.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(_SCHEMA_V1)
        connection.executescript(_SCHEMA_V2)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (1, 'old')"
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (2, 'old')"
        )
        connection.execute("PRAGMA user_version = 2")
        connection.commit()

    store = ProjectStore(data_dir)
    project = store.create_project("Migrado v2")
    try:
        with sqlite3.connect(database_path) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
            assert connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall() == [(1,), (2,), (3,), (4,), (5,)]
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert "approvals" in tables
        assert store.list_approvals(project.id) == []
    finally:
        store.close()


def test_approval_json_details_do_not_contain_paths(service, tmp_path):
    project_service, _ = service
    project = project_service.create_project("Rutas")
    saved = save_revision(project_service, project.id)

    try:
        project_service.approve_revision(
            project.id,
            saved.revision,
            "0" * 64,
            "Ana",
        )
    except ApprovalHashMismatchError as error:
        encoded = json.dumps(
            {
                "project_id": error.project_id,
                "revision": error.revision,
                "provided_sha256": error.provided_sha256,
                "current_sha256": error.current_sha256,
            }
        )
    else:  # pragma: no cover - the call above must fail
        raise AssertionError("La aprobación con hash incorrecto no falló.")
    assert str(tmp_path) not in encoded
    assert "artifacts" not in encoded
    assert "autosolid.db" not in encoded
