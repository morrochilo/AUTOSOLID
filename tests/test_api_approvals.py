import hashlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from autosolid.api import create_app
from autosolid.cad.models import Question
from autosolid.projects import ProjectStore
from tests.builders import revolve_spec

API = "/api/v1"
TIMESTAMP = "2026-10-24T00:00:00.000000+00:00"


def payload_for(spec, project_id: str, revision: int | None = None):
    payload = spec.model_dump(mode="json")
    payload["project_id"] = project_id
    if revision is not None:
        payload["revision"] = revision
    return payload


def create_project(client: TestClient, name: str = "Aprobaciones") -> dict:
    response = client.post(f"{API}/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


def save_revision(client: TestClient, project_id: str, expected: int = 0) -> dict:
    response = client.put(
        f"{API}/projects/{project_id}/cadspec",
        json={
            "spec": payload_for(revolve_spec(), project_id),
            "expected_revision": expected,
        },
    )
    assert response.status_code == 200, response.text
    return {
        "revision": int(response.headers["x-cadspec-revision"]),
        "sha256": response.headers["x-cadspec-sha256"],
        "spec": response.json(),
    }


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    return body["error"]


@pytest.fixture
def client_and_app(tmp_path):
    store = ProjectStore(tmp_path / "data")
    app = create_app(store)
    with TestClient(app) as client:
        yield client, store


def approve(client, project_id, revision_value, sha256_value, **overrides):
    payload = {
        "revision": revision_value,
        "sha256": sha256_value,
        "approved_by": "Ana Revisora",
    }
    payload.update(overrides)
    return client.post(f"{API}/projects/{project_id}/approvals", json=payload)


def test_create_get_and_list_design_approval(client_and_app):
    client, _ = client_and_app
    project = create_project(client)
    saved = save_revision(client, project["id"])

    response = approve(
        client,
        project["id"],
        saved["revision"],
        saved["sha256"],
        note="  Revisado contra el plano.  ",
    )

    assert response.status_code == 201
    approval = response.json()
    assert set(approval) == {
        "id",
        "project_id",
        "revision",
        "revision_sha256",
        "scope",
        "approved_by",
        "note",
        "created_at",
        "status",
    }
    assert approval["id"].startswith("apr_")
    assert approval["project_id"] == project["id"]
    assert approval["revision"] == saved["revision"]
    assert approval["revision_sha256"] == saved["sha256"]
    assert approval["scope"] == "design"
    assert approval["approved_by"] == "Ana Revisora"
    assert approval["note"] == "Revisado contra el plano."
    assert approval["status"] == "valid"
    assert approval["created_at"]
    assert response.headers["location"] == (
        f"{API}/projects/{project['id']}/approvals/{approval['id']}"
    )

    fetched = client.get(
        f"{API}/projects/{project['id']}/approvals/{approval['id']}"
    )
    assert fetched.status_code == 200
    assert fetched.json() == approval

    listed = client.get(f"{API}/projects/{project['id']}/approvals")
    assert listed.status_code == 200
    assert listed.json() == [approval]


def test_duplicate_approval_returns_existing_record(client_and_app):
    client, _ = client_and_app
    project = create_project(client)
    saved = save_revision(client, project["id"])

    first = approve(client, project["id"], saved["revision"], saved["sha256"])
    second = approve(
        client,
        project["id"],
        saved["revision"],
        saved["sha256"],
        approved_by="Otra persona",
        note="Otra nota",
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()
    assert second.headers["location"] == first.headers["location"]


def test_new_revision_marks_previous_approval_stale(client_and_app):
    client, _ = client_and_app
    project = create_project(client)
    first_revision = save_revision(client, project["id"])
    approval = approve(
        client,
        project["id"],
        first_revision["revision"],
        first_revision["sha256"],
    ).json()
    assert approval["status"] == "valid"

    second_revision = save_revision(client, project["id"], expected=1)

    listed = client.get(f"{API}/projects/{project['id']}/approvals")
    assert listed.status_code == 200
    assert [item["status"] for item in listed.json()] == ["stale"]

    fetched = client.get(
        f"{API}/projects/{project['id']}/approvals/{approval['id']}"
    )
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "stale"

    second = approve(
        client,
        project["id"],
        second_revision["revision"],
        second_revision["sha256"],
    )
    assert second.status_code == 201
    assert second.json()["status"] == "valid"

    statuses = {
        item["id"]: item["status"]
        for item in client.get(
            f"{API}/projects/{project['id']}/approvals"
        ).json()
    }
    assert statuses == {approval["id"]: "stale", second.json()["id"]: "valid"}


def test_approval_rejects_a_non_current_revision(client_and_app):
    client, _ = client_and_app
    project = create_project(client)
    first_revision = save_revision(client, project["id"])
    second_revision = save_revision(client, project["id"], expected=1)

    response = approve(
        client,
        project["id"],
        first_revision["revision"],
        first_revision["sha256"],
    )
    error = assert_error(response, 409, "REVISION_CONFLICT")
    assert error["details"] == {
        "expected_revision": 1,
        "current_revision": 2,
    }

    response = approve(
        client,
        project["id"],
        second_revision["revision"],
        "0" * 64,
    )
    error = assert_error(response, 409, "APPROVAL_HASH_MISMATCH")
    assert error["details"]["provided_sha256"] == "0" * 64
    assert error["details"]["current_sha256"] == second_revision["sha256"]

    listed = client.get(f"{API}/projects/{project['id']}/approvals")
    assert listed.json() == []


def test_approval_requires_a_saved_revision(client_and_app):
    client, _ = client_and_app
    project = create_project(client)

    response = approve(client, project["id"], 1, "a" * 64)
    error = assert_error(response, 409, "REVISION_CONFLICT")
    assert error["details"] == {
        "expected_revision": 1,
        "current_revision": 0,
    }


@pytest.mark.parametrize(
    ("overrides", "status", "code"),
    [
        ({"revision": 0}, 422, "REQUEST_INVALID"),
        ({"revision": "1"}, 422, "REQUEST_INVALID"),
        ({"sha256": "a" * 63}, 422, "REQUEST_INVALID"),
        ({"sha256": "A" * 64}, 422, "INVALID_APPROVAL"),
        ({"scope": "construction"}, 422, "REQUEST_INVALID"),
        ({"approved_by": ""}, 422, "REQUEST_INVALID"),
        ({"approved_by": "x" * 121}, 422, "REQUEST_INVALID"),
        ({"note": "x" * 2_001}, 422, "REQUEST_INVALID"),
        ({"unexpected": True}, 422, "REQUEST_INVALID"),
    ],
)
def test_invalid_approval_requests_are_rejected(
    client_and_app, overrides, status, code
):
    client, _ = client_and_app
    project = create_project(client)
    saved = save_revision(client, project["id"])

    response = approve(
        client,
        project["id"],
        saved["revision"],
        saved["sha256"],
        **overrides,
    )
    assert_error(response, status, code)
    assert client.get(f"{API}/projects/{project['id']}/approvals").json() == []


def test_approval_unknown_project_or_approval_is_not_found(client_and_app):
    client, _ = client_and_app
    project = create_project(client)
    save_revision(client, project["id"])

    missing_project = approve(client, "prj_missing", 1, "a" * 64)
    assert_error(missing_project, 404, "PROJECT_NOT_FOUND")

    missing_approval = client.get(
        f"{API}/projects/{project['id']}/approvals/apr_missing"
    )
    error = assert_error(missing_approval, 404, "APPROVAL_NOT_FOUND")
    assert error["details"] == {
        "project_id": project["id"],
        "approval_id": "apr_missing",
    }

    listed = client.get(f"{API}/projects/{project['id']}/approvals")
    assert listed.status_code == 200
    assert listed.json() == []


def test_approval_is_blocked_by_invalid_stored_revision(client_and_app):
    client, store = client_and_app
    project = create_project(client)
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
        update={"project_id": project["id"], "revision": 1}
    ).model_dump_json()
    sha256 = hashlib.sha256(spec_json.encode("utf-8")).hexdigest()

    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "INSERT INTO revisions(project_id, revision, spec_json, sha256, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (project["id"], 1, spec_json, sha256, TIMESTAMP),
        )
        connection.execute(
            "UPDATE projects SET current_revision = 1 WHERE id = ?",
            (project["id"],),
        )
        connection.commit()

    response = approve(client, project["id"], 1, sha256)
    error = assert_error(response, 409, "APPROVAL_BLOCKED")
    assert isinstance(error["details"], list)
    assert "QUESTION_CRITICAL_OPEN" in {
        item["code"] for item in error["details"]
    }
    assert client.get(f"{API}/projects/{project['id']}/approvals").json() == []


def test_approval_error_details_do_not_leak_paths(client_and_app, tmp_path):
    client, _ = client_and_app
    project = create_project(client)
    saved = save_revision(client, project["id"])

    response = approve(client, project["id"], saved["revision"], "0" * 64)
    assert_error(response, 409, "APPROVAL_HASH_MISMATCH")

    encoded = response.text
    assert str(tmp_path) not in encoded
    assert "artifacts" not in encoded
    assert "autosolid.db" not in encoded
