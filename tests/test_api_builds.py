from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from autosolid.api import create_app
from autosolid.build import BuildExecutionError, BuildExecutionResult
from autosolid.projects import ProjectService, ProjectStore
from tests.builders import revolve_spec

API = "/api/v1"


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value = self.value + timedelta(seconds=seconds)


class RecordingRunner:
    def __init__(self, *, outcomes: list[Exception | None] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.calls = 0

    def build(self, spec_path, output_path, *, output_root):
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome is not None:
            raise outcome
        output_path.write_bytes(b"SIMULATED-SLDPRT\n")
        return BuildExecutionResult(
            revision="simulated",
            volume_m3=0.000008,
            expected_volume_m3=0.000008,
            volume_difference_m3=0.0,
            errors=0,
            warnings=0,
        )


def payload_for(spec, project_id: str) -> dict:
    payload = spec.model_dump(mode="json")
    payload["project_id"] = project_id
    return payload


def create_project(client: TestClient, name: str = "Build API") -> dict:
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
    }


def create_build_approval(
    client: TestClient,
    project_id: str,
    saved: dict,
    *,
    destination: str = "parts/block-012.sldprt",
    **overrides,
) -> dict:
    payload = {
        "revision": saved["revision"],
        "sha256": saved["sha256"],
        "approved_by": "Ana Revisora",
        "destination": destination,
    }
    payload.update(overrides)
    response = client.post(
        f"{API}/projects/{project_id}/build-approvals",
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def request_build(
    client: TestClient,
    project_id: str,
    approval: dict,
    *,
    idempotency_key: str = "idem-api-0001",
    destination: str | None = None,
):
    return client.post(
        f"{API}/projects/{project_id}/builds",
        json={
            "approval_id": approval["id"],
            "destination": (
                approval["destination"] if destination is None else destination
            ),
            "idempotency_key": idempotency_key,
        },
    )


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    return body["error"]


def wait_for_terminal(client: TestClient, project_id: str, job_id: str) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(f"{API}/projects/{project_id}/builds/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["state"] in {"completed", "failed"}:
            return job
        time.sleep(0.02)
    raise AssertionError("El trabajo no terminó en el plazo de la prueba.")


@pytest.fixture
def client_and_env(tmp_path):
    store = ProjectStore(tmp_path / "data")
    clock = Clock()
    runner = RecordingRunner()
    service = ProjectService(
        store,
        build_output_dir=tmp_path / "output",
        build_runner=runner,
        now=clock,
    )
    app = create_app(store, service=service)
    with TestClient(app) as client:
        yield client, service, clock, runner, tmp_path / "output"


def test_create_build_approval_and_get_it(client_and_env):
    client, _, _, _, _ = client_and_env
    project = create_project(client)
    saved = save_revision(client, project["id"])

    approval = create_build_approval(client, project["id"], saved)

    assert approval["id"].startswith("bapr_")
    assert approval["scope"] == "build"
    assert approval["revision"] == saved["revision"]
    assert approval["revision_sha256"] == saved["sha256"]
    assert approval["destination"] == "parts/block-012.sldprt"
    assert len(approval["destination_hash"]) == 64
    assert approval["status"] == "valid"
    assert approval["consumed_at"] is None
    assert approval["job_id"] is None
    assert approval["note"] is None

    listed = client.get(
        f"{API}/projects/{project['id']}/build-approvals"
    ).json()
    assert listed == [approval]
    fetched = client.get(
        f"{API}/projects/{project['id']}/build-approvals/{approval['id']}"
    )
    assert fetched.status_code == 200
    assert fetched.json() == approval


def test_request_build_completes_and_records_artifact(client_and_env):
    client, _, _, runner, output_dir = client_and_env
    project = create_project(client)
    saved = save_revision(client, project["id"])
    approval = create_build_approval(client, project["id"], saved)

    response = request_build(client, project["id"], approval)
    assert response.status_code == 202, response.text
    job = response.json()
    assert response.headers["location"] == (
        f"{API}/projects/{project['id']}/builds/{job['id']}"
    )
    assert job["state"] in {"queued", "running", "completed"}

    completed = wait_for_terminal(client, project["id"], job["id"])
    assert completed["state"] == "completed"
    assert completed["attempt"] == 1
    assert completed["error"] is None
    assert completed["artifact"]["name"] == approval["destination"]
    assert len(completed["artifact"]["sha256"]) == 64
    assert completed["artifact"]["byte_size"] == len(b"SIMULATED-SLDPRT\n")
    assert (output_dir / approval["destination"]).is_file()
    assert runner.calls == 1

    fetched = client.get(
        f"{API}/projects/{project['id']}/builds/{job['id']}"
    ).json()
    assert fetched == completed
    listed = client.get(f"{API}/projects/{project['id']}/builds").json()
    assert listed == [completed]
    used = client.get(
        f"{API}/projects/{project['id']}/build-approvals/{approval['id']}"
    ).json()
    assert used["status"] == "used"
    assert used["job_id"] == job["id"]
    assert used["consumed_at"] is not None


def test_idempotent_request_returns_the_same_job(client_and_env):
    client, _, _, runner, _ = client_and_env
    project = create_project(client)
    saved = save_revision(client, project["id"])
    approval = create_build_approval(client, project["id"], saved)

    first = request_build(client, project["id"], approval)
    second = request_build(client, project["id"], approval)
    assert first.status_code == 202
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    wait_for_terminal(client, project["id"], first.json()["id"])
    assert runner.calls == 1


def test_invalid_build_approval_fields_return_stable_error(client_and_env):
    client, _, _, _, _ = client_and_env
    project = create_project(client)
    saved = save_revision(client, project["id"])

    response = client.post(
        f"{API}/projects/{project['id']}/build-approvals",
        json={
            "revision": saved["revision"],
            "sha256": saved["sha256"],
            "approved_by": "   ",
            "destination": "parts/block-012.sldprt",
        },
    )
    error = assert_error(response, 422, "INVALID_BUILD_APPROVAL")
    assert error["details"] == {"reason": "approved_by"}


def test_unsafe_destination_returns_stable_error(client_and_env):
    client, _, _, _, _ = client_and_env
    project = create_project(client)
    saved = save_revision(client, project["id"])

    response = client.post(
        f"{API}/projects/{project['id']}/build-approvals",
        json={
            "revision": saved["revision"],
            "sha256": saved["sha256"],
            "approved_by": "Ana",
            "destination": "C:/tmp/escape.sldprt",
        },
    )
    error = assert_error(response, 422, "INVALID_BUILD_DESTINATION")
    assert error["details"] == {"reason": "absolute"}


def test_expired_approval_returns_stable_error(client_and_env):
    client, _, clock, runner, _ = client_and_env
    project = create_project(client)
    saved = save_revision(client, project["id"])
    approval = create_build_approval(
        client,
        project["id"],
        saved,
        expires_in_seconds=30,
    )
    clock.advance(31)

    error = assert_error(
        request_build(client, project["id"], approval),
        409,
        "BUILD_APPROVAL_EXPIRED",
    )
    assert error["details"]["approval_id"] == approval["id"]
    assert runner.calls == 0


def test_consumed_approval_returns_stable_error(client_and_env):
    client, _, _, _, _ = client_and_env
    project = create_project(client)
    saved = save_revision(client, project["id"])
    approval = create_build_approval(client, project["id"], saved)
    assert request_build(
        client, project["id"], approval, idempotency_key="idem-api-used-01"
    ).status_code == 202

    error = assert_error(
        request_build(
            client, project["id"], approval, idempotency_key="idem-api-used-02"
        ),
        409,
        "BUILD_APPROVAL_CONSUMED",
    )
    assert error["details"]["approval_id"] == approval["id"]


def test_destination_mismatch_returns_stable_error(client_and_env):
    client, _, _, runner, _ = client_and_env
    project = create_project(client)
    saved = save_revision(client, project["id"])
    approval = create_build_approval(client, project["id"], saved)

    error = assert_error(
        request_build(
            client,
            project["id"],
            approval,
            destination="parts/other.sldprt",
        ),
        409,
        "BUILD_DESTINATION_MISMATCH",
    )
    assert error["details"]["approval_id"] == approval["id"]
    assert runner.calls == 0


def test_stale_approval_returns_stable_error(client_and_env):
    client, _, _, _, _ = client_and_env
    project = create_project(client)
    saved = save_revision(client, project["id"])
    approval = create_build_approval(client, project["id"], saved)
    save_revision(client, project["id"], expected=saved["revision"])

    error = assert_error(
        request_build(client, project["id"], approval),
        409,
        "BUILD_APPROVAL_STALE",
    )
    assert error["details"]["revision"] == saved["revision"]
    assert error["details"]["current_revision"] == saved["revision"] + 1


def test_build_approval_with_wrong_hash_returns_stale(client_and_env):
    client, _, _, _, _ = client_and_env
    project = create_project(client)
    saved = save_revision(client, project["id"])

    response = client.post(
        f"{API}/projects/{project['id']}/build-approvals",
        json={
            "revision": saved["revision"],
            "sha256": "0" * 64,
            "approved_by": "Ana",
            "destination": "parts/block-012.sldprt",
        },
    )
    assert_error(response, 409, "BUILD_APPROVAL_STALE")


def test_missing_build_approval_and_job_return_404(client_and_env):
    client, _, _, _, _ = client_and_env
    project = create_project(client)
    save_revision(client, project["id"])

    assert_error(
        client.get(
            f"{API}/projects/{project['id']}/build-approvals/bapr_missing"
        ),
        404,
        "BUILD_APPROVAL_NOT_FOUND",
    )
    assert_error(
        client.get(f"{API}/projects/{project['id']}/builds/job_missing"),
        404,
        "BUILD_JOB_NOT_FOUND",
    )


def test_retry_endpoint_requeues_a_failed_job(client_and_env):
    client, service, _, _, _ = client_and_env
    project = create_project(client)
    saved = save_revision(client, project["id"])
    approval = create_build_approval(client, project["id"], saved)
    service._runner = RecordingRunner(
        outcomes=[BuildExecutionError("RUNNER_TIMEOUT", "timeout")]
    )

    response = request_build(
        client, project["id"], approval, idempotency_key="idem-api-retry-01"
    )
    assert response.status_code == 202
    job_id = response.json()["id"]
    failed = wait_for_terminal(client, project["id"], job_id)
    assert failed["state"] == "failed"
    assert failed["error"]["code"] == "RUNNER_TIMEOUT"

    retry = client.post(
        f"{API}/projects/{project['id']}/builds/{job_id}/retry"
    )
    assert retry.status_code == 202, retry.text
    assert retry.json()["attempt"] == 2
    completed = wait_for_terminal(client, project["id"], job_id)
    assert completed["state"] == "completed"
    assert completed["error"] is None
    assert completed["artifact"]["name"] == approval["destination"]

    again = client.post(
        f"{API}/projects/{project['id']}/builds/{job_id}/retry"
    )
    assert again.status_code == 200
    assert again.json()["state"] == "completed"


def test_responses_do_not_leak_absolute_paths(client_and_env):
    client, _, _, _, output_dir = client_and_env
    project = create_project(client)
    saved = save_revision(client, project["id"])
    approval = create_build_approval(client, project["id"], saved)
    job_id = request_build(client, project["id"], approval).json()["id"]
    completed = wait_for_terminal(client, project["id"], job_id)

    encoded = repr(completed)
    assert str(output_dir) not in encoded
    assert "autosolid.db" not in encoded
    assert completed["destination"] == approval["destination"]
    assert completed["artifact"]["name"] == approval["destination"]
