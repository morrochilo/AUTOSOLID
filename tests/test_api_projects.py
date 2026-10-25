import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autosolid.api import create_app
from autosolid.api.cli import build_parser
from autosolid.cad.models import Question
from autosolid.projects import ProjectStore
from tests.builders import revolve_spec

API = "/api/v1"


def payload_for(spec, project_id: str, revision: int | None = None):
    payload = spec.model_dump(mode="json")
    payload["project_id"] = project_id
    if revision is not None:
        payload["revision"] = revision
    return payload


def create_project(client: TestClient, name: str = "Pieza") -> dict:
    response = client.post(f"{API}/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


def assert_error(response, status: int, code: str):
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    return body["error"]


@pytest.fixture
def client_and_store(tmp_path):
    store = ProjectStore(tmp_path / "data")
    app = create_app(store)
    with TestClient(app) as client:
        yield client, store


def test_health_returns_status_without_machine_information(client_and_store):
    client, _ = client_and_store
    response = client.get(f"{API}/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "machine" not in response.text
    assert "python" not in response.text.lower()


def test_create_list_and_get_project(client_and_store):
    client, _ = client_and_store
    project = create_project(client, "  Bancada  ")
    assert project["id"].startswith("prj_")
    assert project["name"] == "Bancada"
    assert project["current_revision"] == 0

    listed = client.get(f"{API}/projects")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [project["id"]]

    fetched = client.get(f"{API}/projects/{project['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == project

    assert_error(
        client.get(f"{API}/projects/prj_missing"), 404, "PROJECT_NOT_FOUND"
    )


def test_project_name_and_request_errors_are_stable(client_and_store):
    client, _ = client_and_store
    assert_error(
        client.post(f"{API}/projects", json={"name": "   "}),
        422,
        "INVALID_PROJECT_NAME",
    )
    assert_error(
        client.post(f"{API}/projects", json={}),
        422,
        "REQUEST_INVALID",
    )
    assert_error(
        client.post(f"{API}/projects", json={"name": "Pieza", "extra": 1}),
        422,
        "REQUEST_INVALID",
    )


def test_cadspec_is_missing_until_first_save(client_and_store):
    client, _ = client_and_store
    project = create_project(client)
    assert_error(
        client.get(f"{API}/projects/{project['id']}/cadspec"),
        404,
        "CADSPEC_NOT_FOUND",
    )
    assert_error(
        client.get(f"{API}/projects/prj_missing/cadspec"),
        404,
        "PROJECT_NOT_FOUND",
    )


def test_validate_is_read_only_and_returns_diagnostics(client_and_store):
    client, store = client_and_store
    project = create_project(client)
    payload = payload_for(revolve_spec(), project["id"])

    response = client.post(
        f"{API}/projects/{project['id']}/cadspec/validate", json=payload
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["diagnostics"] == []
    assert body["current_revision"] == 0
    assert store.list_revisions(project["id"]) == []
    assert_error(
        client.get(f"{API}/projects/{project['id']}/cadspec"),
        404,
        "CADSPEC_NOT_FOUND",
    )

    invalid = client.post(
        f"{API}/projects/{project['id']}/cadspec/validate",
        json={"project_id": project["id"], "unexpected": True},
    )
    assert invalid.status_code == 200
    invalid_body = invalid.json()
    assert invalid_body["valid"] is False
    diagnostic = invalid_body["diagnostics"][0]
    assert diagnostic["code"] == "SCHEMA_INVALID"
    assert set(diagnostic) == {"code", "severity", "path", "message"}

    mismatch = client.post(
        f"{API}/projects/{project['id']}/cadspec/validate",
        json=payload_for(revolve_spec(), "prj_other"),
    )
    assert mismatch.status_code == 200
    assert "PROJECT_ID_MISMATCH" in {
        item["code"] for item in mismatch.json()["diagnostics"]
    }
    assert store.get_project(project["id"]).current_revision == 0


def test_save_cadspec_creates_revision_and_preserves_decimals(client_and_store):
    client, _ = client_and_store
    project = create_project(client)
    payload = payload_for(revolve_spec(), project["id"], revision=999)

    response = client.put(
        f"{API}/projects/{project['id']}/cadspec",
        json={"expected_revision": 0, "spec": payload},
    )
    assert response.status_code == 200
    saved = response.json()
    saved_hash = response.headers["x-cadspec-sha256"]
    assert saved["revision"] == 1
    assert saved["project_id"] == project["id"]
    assert saved["schema_version"] == "0.1.0"
    assert saved["parameters"]["outer_diameter"]["value"] == "50.000"
    assert len(saved_hash) == 64
    assert response.headers["etag"] == f'"{saved_hash}"'

    fetched = client.get(f"{API}/projects/{project['id']}/cadspec")
    assert fetched.status_code == 200
    assert fetched.headers["x-cadspec-sha256"] == saved_hash
    assert fetched.headers["x-cadspec-revision"] == "1"
    assert fetched.json() == saved

    updated = client.get(f"{API}/projects/{project['id']}")
    assert updated.json()["current_revision"] == 1

    second = client.put(
        f"{API}/projects/{project['id']}/cadspec?expected_revision=1",
        json=payload_for(revolve_spec(), project["id"]),
    )
    assert second.status_code == 200
    assert second.json()["revision"] == 2


def test_top_level_expected_revision_is_supported(client_and_store):
    client, _ = client_and_store
    project = create_project(client)
    payload = payload_for(revolve_spec(), project["id"])
    payload["expected_revision"] = 0

    response = client.put(
        f"{API}/projects/{project['id']}/cadspec", json=payload
    )
    assert response.status_code == 200
    assert response.json()["revision"] == 1


def test_invalid_specs_are_rejected_without_persistence(client_and_store):
    client, store = client_and_store
    project = create_project(client)

    invalid = client.put(
        f"{API}/projects/{project['id']}/cadspec",
        json={
            "expected_revision": 0,
            "spec": {"project_id": project["id"], "unexpected": True},
        },
    )
    error = assert_error(invalid, 422, "SPEC_INVALID")
    assert error["details"][0]["code"] == "SCHEMA_INVALID"

    critical_spec = revolve_spec(
        open_questions=[
            Question(
                id="q_critical",
                text="¿Falta una cota?",
                severity="critical",
            )
        ]
    )
    critical = client.put(
        f"{API}/projects/{project['id']}/cadspec",
        json={
            "expected_revision": 0,
            "spec": payload_for(critical_spec, project["id"]),
        },
    )
    error = assert_error(critical, 422, "SPEC_INVALID")
    assert "QUESTION_CRITICAL_OPEN" in {
        item["code"] for item in error["details"]
    }

    mismatch = client.put(
        f"{API}/projects/{project['id']}/cadspec",
        json={
            "expected_revision": 0,
            "spec": payload_for(revolve_spec(), "prj_other"),
        },
    )
    error = assert_error(mismatch, 422, "SPEC_INVALID")
    assert "PROJECT_ID_MISMATCH" in {
        item["code"] for item in error["details"]
    }

    assert store.get_project(project["id"]).current_revision == 0
    assert store.list_revisions(project["id"]) == []
    assert_error(
        client.get(f"{API}/projects/{project['id']}/cadspec"),
        404,
        "CADSPEC_NOT_FOUND",
    )


def test_revision_conflict_returns_409(client_and_store):
    client, _ = client_and_store
    project = create_project(client)
    payload = payload_for(revolve_spec(), project["id"])
    first = client.put(
        f"{API}/projects/{project['id']}/cadspec",
        json={"expected_revision": 0, "spec": payload},
    )
    assert first.status_code == 200

    conflict = client.put(
        f"{API}/projects/{project['id']}/cadspec",
        json={"expected_revision": 0, "spec": payload},
    )
    error = assert_error(conflict, 409, "REVISION_CONFLICT")
    assert error["details"] == {
        "expected_revision": 0,
        "current_revision": 1,
    }
    project_after = client.get(f"{API}/projects/{project['id']}").json()
    assert project_after["current_revision"] == 1


def test_update_envelope_errors_are_stable(client_and_store):
    client, _ = client_and_store
    project = create_project(client)
    payload = payload_for(revolve_spec(), project["id"])

    missing = client.put(
        f"{API}/projects/{project['id']}/cadspec", json=payload
    )
    assert_error(missing, 422, "MISSING_EXPECTED_REVISION")

    extra = client.put(
        f"{API}/projects/{project['id']}/cadspec",
        json={"expected_revision": 0, "spec": payload, "extra": 1},
    )
    assert_error(extra, 422, "REQUEST_INVALID")


def test_errors_do_not_expose_internal_paths(client_and_store, tmp_path):
    client, _ = client_and_store
    project = create_project(client)
    responses = [
        client.get(f"{API}/projects/prj_missing"),
        client.get(f"{API}/projects/{project['id']}/cadspec"),
        client.put(
            f"{API}/projects/{project['id']}/cadspec",
            json={"expected_revision": 0, "spec": {"unexpected": True}},
        ),
        client.post(f"{API}/projects", json={"name": 123}),
    ]
    assert responses[-1].status_code == 422
    for response in responses:
        assert str(tmp_path) not in response.text
        assert "Traceback" not in response.text
        assert "autosolid.db" not in response.text


def test_unexpected_errors_hide_details(tmp_path):
    store = ProjectStore(tmp_path / "data")
    app = create_app(store)

    def fail(_: str):
        raise RuntimeError(f"secret path {tmp_path}")

    app.state.service.create_project = fail
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(f"{API}/projects", json={"name": "Pieza"})
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert str(tmp_path) not in response.text
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text


def test_project_and_cadspec_survive_store_and_app_recreation(tmp_path):
    data_dir = tmp_path / "data"
    first_store = ProjectStore(data_dir)
    first_app = create_app(first_store)
    with TestClient(first_app) as client:
        project = create_project(client, "Persistente")
        save_response = client.put(
            f"{API}/projects/{project['id']}/cadspec",
            json={
                "expected_revision": 0,
                "spec": payload_for(revolve_spec(), project["id"]),
            },
        )
        saved = save_response.json()
        saved_hash = save_response.headers["x-cadspec-sha256"]

    second_store = ProjectStore(data_dir)
    second_app = create_app(second_store)
    with TestClient(second_app) as client:
        fetched_project = client.get(f"{API}/projects/{project['id']}")
        assert fetched_project.status_code == 200
        assert fetched_project.json()["current_revision"] == 1
        fetched_spec = client.get(f"{API}/projects/{project['id']}/cadspec")
        assert fetched_spec.status_code == 200
        assert fetched_spec.headers["x-cadspec-sha256"] == saved_hash
        assert fetched_spec.json() == saved


def test_api_data_directory_can_come_from_environment(tmp_path, monkeypatch):
    data_dir = tmp_path / "environment"
    monkeypatch.setenv("AUTOSOLID_DATA_DIR", str(data_dir))
    app = create_app()
    assert app.state.store.database_path == data_dir.resolve() / "autosolid.db"
    with TestClient(app) as client:
        assert client.get(f"{API}/health").status_code == 200
        assert client.post(f"{API}/projects", json={"name": "Entorno"}).status_code == 201
    assert (data_dir / "autosolid.db").exists()


def test_cli_defaults_to_loopback_and_module_imports():
    parser = build_parser()
    assert parser.parse_args([]).host == "127.0.0.1"
    assert parser.parse_args(["--host", "0.0.0.0"]).host == "0.0.0.0"

    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(root / "src") + (
        os.pathsep + existing if existing else ""
    )
    result = subprocess.run(
        [sys.executable, "-m", "autosolid.api", "--help"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
    )
    assert result.returncode == 0
    assert "127.0.0.1" in result.stdout
