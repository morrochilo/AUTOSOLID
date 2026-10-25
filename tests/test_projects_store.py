import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from autosolid.cad.models import Question
from autosolid.projects import (
    SCHEMA_VERSION,
    CadspecNotFoundError,
    InvalidProjectNameError,
    InvalidSpecError,
    ProjectService,
    ProjectStore,
    RevisionConflictError,
    StoreClosedError,
)
from tests.builders import revolve_spec


def payload_for(spec, project_id: str, revision: int | None = None):
    payload = spec.model_dump(mode="json")
    payload["project_id"] = project_id
    if revision is not None:
        payload["revision"] = revision
    return payload


def test_store_creates_lists_and_persists_projects(tmp_path):
    store = ProjectStore(tmp_path / "data")
    first = store.create_project("  Pieza A  ")
    second = store.create_project("Pieza B")

    assert first.id.startswith("prj_")
    assert first.name == "Pieza A"
    assert first.current_revision == 0
    assert [project.id for project in store.list_projects()] == [first.id, second.id]
    assert store.get_project(first.id) == first

    store.close()
    reopened = ProjectStore(tmp_path / "data")
    assert [project.id for project in reopened.list_projects()] == [first.id, second.id]
    assert reopened.get_project(first.id).name == "Pieza A"
    reopened.close()


@pytest.mark.parametrize(
    "name",
    ["", "   ", "\t", "control\x00name", "x" * 201],
)
def test_invalid_project_names_are_rejected(tmp_path, name):
    store = ProjectStore(tmp_path / "data")
    with pytest.raises(InvalidProjectNameError):
        store.create_project(name)
    assert store.list_projects() == []


def test_schema_version_and_migration_are_recorded(tmp_path):
    store = ProjectStore(tmp_path / "data")
    assert store.list_projects() == []
    with sqlite3.connect(store.database_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        migrations = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert version == SCHEMA_VERSION
    assert migrations == [(1,), (2,), (3,), (4,)]
    store.close()

    reopened = ProjectStore(tmp_path / "data")
    with sqlite3.connect(reopened.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()[0] == 4
    reopened.close()


def test_closed_store_rejects_operations(tmp_path):
    store = ProjectStore(tmp_path / "data")
    store.create_project("Pieza")
    store.close()
    with pytest.raises(StoreClosedError):
        store.list_projects()


def test_service_saves_immutable_revisions_with_hash_and_decimals(tmp_path):
    store = ProjectStore(tmp_path / "data")
    service = ProjectService(store)
    project = service.create_project("Revolución")
    payload = payload_for(revolve_spec(), project.id, revision=0)

    outcome = service.validate_cadspec(project.id, payload)
    assert outcome.valid is True
    assert outcome.diagnostics == []
    assert outcome.current_revision == 0
    assert service.list_revisions(project.id) == []
    with pytest.raises(CadspecNotFoundError):
        service.get_cadspec(project.id)

    first = service.save_cadspec(project.id, 0, payload)
    assert first.revision == 1
    assert first.spec["revision"] == 1
    assert first.spec["project_id"] == project.id
    assert first.spec["parameters"]["outer_diameter"]["value"] == "50.000"
    assert len(first.sha256) == 64

    first_record = store.get_revision(project.id, 1)
    encoded = first_record.spec_json.encode("utf-8")
    assert first_record.sha256 == hashlib.sha256(encoded).hexdigest()
    assert first.sha256 == first_record.sha256
    assert service.get_project(project.id).current_revision == 1

    raw_second = payload_for(revolve_spec(), project.id, revision=999)
    second = service.save_cadspec(project.id, 1, raw_second)
    assert second.revision == 2
    assert second.spec["revision"] == 2

    unchanged = store.get_revision(project.id, 1)
    assert unchanged.spec_json == first_record.spec_json
    assert unchanged.sha256 == first_record.sha256
    assert service.get_revision(project.id, 1).spec["revision"] == 1
    assert [item.revision for item in service.list_revisions(project.id)] == [1, 2]
    store.close()


def test_sqlite_trigger_blocks_revision_updates(tmp_path):
    store = ProjectStore(tmp_path / "data")
    service = ProjectService(store)
    project = service.create_project("Inmutable")
    saved = service.save_cadspec(
        project.id, 0, payload_for(revolve_spec(), project.id)
    )

    with sqlite3.connect(store.database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE revisions SET spec_json = ? WHERE project_id = ? AND revision = ?",
                ("{}", project.id, saved.revision),
            )
    store.close()


def test_invalid_or_critical_specs_are_not_persisted(tmp_path):
    store = ProjectStore(tmp_path / "data")
    service = ProjectService(store)
    project = service.create_project("Inválida")

    invalid_schema = {"project_id": project.id, "unexpected": True}
    with pytest.raises(InvalidSpecError) as schema_error:
        service.save_cadspec(project.id, 0, invalid_schema)
    assert schema_error.value.diagnostics[0].code == "SCHEMA_INVALID"

    critical = revolve_spec(
        open_questions=[
            Question(
                id="q_critical",
                text="¿Cuál es el diámetro?",
                severity="critical",
            )
        ]
    )
    with pytest.raises(InvalidSpecError) as critical_error:
        service.save_cadspec(project.id, 0, payload_for(critical, project.id))
    assert "QUESTION_CRITICAL_OPEN" in {
        diagnostic.code for diagnostic in critical_error.value.diagnostics
    }

    mismatch = payload_for(revolve_spec(), "prj_other")
    with pytest.raises(InvalidSpecError) as mismatch_error:
        service.save_cadspec(project.id, 0, mismatch)
    assert "PROJECT_ID_MISMATCH" in {
        diagnostic.code for diagnostic in mismatch_error.value.diagnostics
    }

    assert service.get_project(project.id).current_revision == 0
    assert service.list_revisions(project.id) == []
    with pytest.raises(CadspecNotFoundError):
        service.get_cadspec(project.id)
    store.close()


def test_validate_never_persists_or_changes_revision(tmp_path):
    store = ProjectStore(tmp_path / "data")
    service = ProjectService(store)
    project = service.create_project("Validar")
    payload = payload_for(revolve_spec(), project.id)

    outcome = service.validate_cadspec(project.id, payload)
    assert outcome.valid is True
    assert service.get_project(project.id).current_revision == 0
    assert service.list_revisions(project.id) == []

    invalid = service.validate_cadspec(
        project.id, {"project_id": project.id, "unknown": 1}
    )
    assert invalid.valid is False
    assert invalid.diagnostics[0].code == "SCHEMA_INVALID"
    store.close()


def test_two_updates_with_same_revision_only_one_wins(tmp_path):
    store = ProjectStore(tmp_path / "data")
    service = ProjectService(store)
    project = service.create_project("Concurrente")
    payload = payload_for(revolve_spec(), project.id)
    barrier = Barrier(2)

    def attempt():
        barrier.wait()
        try:
            return service.save_cadspec(project.id, 0, payload)
        except RevisionConflictError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt(), range(2)))

    successes = [result for result in results if not isinstance(result, Exception)]
    conflicts = [
        result for result in results if isinstance(result, RevisionConflictError)
    ]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert conflicts[0].current_revision == 1
    assert service.get_project(project.id).current_revision == 1
    assert len(service.list_revisions(project.id)) == 1
    store.close()


def test_data_directory_can_come_from_environment(tmp_path, monkeypatch):
    data_dir = tmp_path / "environment"
    monkeypatch.setenv("AUTOSOLID_DATA_DIR", str(data_dir))
    store = ProjectStore.from_env()
    assert store.database_path == data_dir.resolve() / "autosolid.db"
    store.create_project("Entorno")
    store.close()
    assert (data_dir / "autosolid.db").exists()


def test_stored_json_round_trip_keeps_decimal_strings(tmp_path):
    store = ProjectStore(tmp_path / "data")
    service = ProjectService(store)
    project = service.create_project("Decimales")
    saved = service.save_cadspec(
        project.id, 0, payload_for(revolve_spec(), project.id)
    )
    raw = json.loads(
        store.get_revision(project.id, saved.revision).spec_json
    )
    assert raw["parameters"]["outer_diameter"]["value"] == "50.000"
    assert raw["sketches"][0]["dimensions"][0]["from"] == [0.0, 0.0]
    store.close()
