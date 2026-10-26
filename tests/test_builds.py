from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest

from autosolid.build import (
    BuildExecutionError,
    BuildExecutionResult,
    SubprocessSolidWorksRunner,
    UnavailableSolidWorksRunner,
    resolve_destination,
)
from autosolid.projects import (
    BuildApprovalConsumedError,
    BuildApprovalExpiredError,
    BuildApprovalStaleError,
    BuildDestinationError,
    BuildDestinationMismatchError,
    BuildJobConflictError,
    InvalidBuildApprovalError,
    InvalidBuildRequestError,
    ProjectService,
    ProjectStore,
    SCHEMA_VERSION,
)
from autosolid.projects.store import _SCHEMA_V1, _SCHEMA_V2, _SCHEMA_V3, _SCHEMA_V4
from tests.builders import revolve_spec

SIMULATED_AGENT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "autosolid"
    / "build"
    / "simulated_agent.py"
)
TIMESTAMP = "2026-10-24T00:00:00.000000+00:00"


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value = self.value + timedelta(seconds=seconds)


class RecordingRunner:
    def __init__(
        self,
        *,
        content: bytes = b"SIMULATED-SLDPRT\n",
        outcomes: list[Exception | None] | None = None,
    ) -> None:
        self.content = content
        self.outcomes = list(outcomes or [])
        self.calls: list[tuple[Path, Path, Path]] = []

    def build(
        self,
        spec_path: Path,
        output_path: Path,
        *,
        output_root: Path,
    ) -> BuildExecutionResult:
        self.calls.append((Path(spec_path), Path(output_path), Path(output_root)))
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome is not None:
            raise outcome
        output_path.write_bytes(self.content)
        return BuildExecutionResult(
            revision="simulated",
            volume_m3=0.000008,
            expected_volume_m3=0.000008,
            volume_difference_m3=0.0,
            errors=0,
            warnings=0,
        )


@pytest.fixture
def build_env(tmp_path):
    store = ProjectStore(tmp_path / "data")
    output_dir = tmp_path / "output"
    clock = Clock()
    runner = RecordingRunner()
    service = ProjectService(
        store,
        build_output_dir=output_dir,
        build_runner=runner,
        now=clock,
    )
    yield service, store, clock, runner, output_dir
    service.shutdown()
    store.close()


def payload_for(spec, project_id: str) -> dict:
    payload = spec.model_dump(mode="json")
    payload["project_id"] = project_id
    return payload


def save_revision(project_service: ProjectService, project_id: str):
    project = project_service.get_project(project_id)
    return project_service.save_cadspec(
        project_id,
        project.current_revision,
        payload_for(revolve_spec(), project_id),
    )


def prepare_approval(
    service: ProjectService,
    project_id: str,
    saved,
    *,
    destination: str = "parts/block-012.sldprt",
    expires_in_seconds: int | None = None,
):
    return service.create_build_approval(
        project_id,
        saved.revision,
        saved.sha256,
        "Ana Revisora",
        destination,
        expires_in_seconds=expires_in_seconds,
    )


def test_build_approval_binds_revision_hash_destination_and_expiry(build_env):
    service, _, _, _, _ = build_env
    project = service.create_project("Aprobación build")
    saved = save_revision(service, project.id)

    approval = prepare_approval(service, project.id, saved)

    assert approval.id.startswith("bapr_")
    assert approval.scope == "build"
    assert approval.revision == saved.revision
    assert approval.revision_sha256 == saved.sha256
    assert approval.destination == "parts/block-012.sldprt"
    assert len(approval.destination_hash) == 64
    assert int(approval.destination_hash, 16) >= 0
    assert approval.status == "valid"
    assert approval.expires_at > approval.created_at
    assert approval.consumed_at is None
    assert approval.job_id is None
    assert service.list_build_approvals(project.id) == [approval]
    assert service.get_build_approval(project.id, approval.id) == approval


@pytest.mark.parametrize(
    ("destination", "reason"),
    [
        ("C:/tmp/part.sldprt", "absolute"),
        ("/tmp/part.sldprt", "absolute"),
        ("..\\escape.sldprt", "escape"),
        ("parts/../../escape.sldprt", "escape"),
        ("parts/part.step", "extension"),
        ("parts/part:stream.sldprt", "destination"),
        (".work/part.sldprt", "destination"),
        ("", "destination"),
        ("parts/bad\x00name.sldprt", "destination"),
    ],
)
def test_unsafe_destinations_are_rejected(build_env, destination, reason):
    service, _, _, _, _ = build_env
    project = service.create_project("Destino")
    saved = save_revision(service, project.id)

    with pytest.raises(BuildDestinationError) as error:
        prepare_approval(
            service,
            project.id,
            saved,
            destination=destination,
        )
    assert error.value.reason == reason
    assert service.list_build_approvals(project.id) == []


def test_existing_destination_is_rejected(build_env):
    service, _, _, _, output_dir = build_env
    project = service.create_project("Existente")
    saved = save_revision(service, project.id)
    existing = output_dir / "parts" / "block-012.sldprt"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"already here")

    with pytest.raises(BuildDestinationError) as error:
        prepare_approval(service, project.id, saved)
    assert error.value.reason == "exists"
    assert existing.read_bytes() == b"already here"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"expires_in_seconds": 29}, "expires_in_seconds"),
        ({"expires_in_seconds": 3_601}, "expires_in_seconds"),
        ({"expires_in_seconds": True}, "expires_in_seconds"),
        ({"expires_in_seconds": "900"}, "expires_in_seconds"),
        ({"approved_by": "   "}, "approved_by"),
        ({"note": "x" * 2_001}, "note"),
    ],
)
def test_invalid_build_approval_fields_are_rejected(
    build_env, overrides, reason
):
    service, _, _, _, _ = build_env
    project = service.create_project("Campos build")
    saved = save_revision(service, project.id)
    arguments = {
        "revision": saved.revision,
        "sha256": saved.sha256,
        "approved_by": "Ana",
        "destination": "parts/block-012.sldprt",
    }
    arguments.update(overrides)

    with pytest.raises(InvalidBuildApprovalError) as error:
        service.create_build_approval(
            project.id,
            arguments["revision"],
            arguments["sha256"],
            arguments["approved_by"],
            arguments["destination"],
            expires_in_seconds=arguments.get("expires_in_seconds"),
            note=arguments.get("note"),
        )
    assert error.value.reason == reason
    assert service.list_build_approvals(project.id) == []


@pytest.mark.parametrize(
    "key",
    ["short", "bad key!", "x" * 129, " " * 8, 42],
)
def test_invalid_idempotency_keys_are_rejected(build_env, key):
    service, _, _, runner, _ = build_env
    project = service.create_project("Clave inválida")
    saved = save_revision(service, project.id)
    approval = prepare_approval(service, project.id, saved)

    with pytest.raises(InvalidBuildRequestError) as error:
        service.request_build(
            project.id,
            approval.id,
            approval.destination,
            key,
        )
    assert error.value.reason == "idempotency_key"
    assert service.list_build_jobs(project.id) == []
    assert runner.calls == []
    assert service.get_build_approval(project.id, approval.id).status == "valid"


def test_build_approval_requires_current_revision_and_matching_hash(build_env):
    service, _, _, _, _ = build_env
    project = service.create_project("Carrera")
    first = save_revision(service, project.id)
    second = save_revision(service, project.id)

    with pytest.raises(BuildApprovalStaleError):
        service.create_build_approval(
            project.id,
            first.revision,
            first.sha256,
            "Ana",
            "parts/old.sldprt",
        )
    with pytest.raises(BuildApprovalStaleError):
        service.create_build_approval(
            project.id,
            second.revision,
            "0" * 64,
            "Ana",
            "parts/new.sldprt",
        )
    assert service.list_build_approvals(project.id) == []


def test_expired_approval_is_rejected_when_requested(build_env):
    service, _, clock, runner, _ = build_env
    project = service.create_project("Expirada")
    saved = save_revision(service, project.id)
    approval = prepare_approval(
        service,
        project.id,
        saved,
        expires_in_seconds=30,
    )

    clock.advance(31)
    assert service.get_build_approval(project.id, approval.id).status == "expired"

    with pytest.raises(BuildApprovalExpiredError):
        service.request_build(
            project.id,
            approval.id,
            approval.destination,
            "idem-expired-01",
        )
    assert service.list_build_jobs(project.id) == []
    assert runner.calls == []


def test_stale_approval_after_new_revision_is_rejected(build_env):
    service, _, _, runner, _ = build_env
    project = service.create_project("Obsoleta")
    first = save_revision(service, project.id)
    approval = prepare_approval(service, project.id, first)
    save_revision(service, project.id)

    assert service.get_build_approval(project.id, approval.id).status == "stale"
    with pytest.raises(BuildApprovalStaleError):
        service.request_build(
            project.id,
            approval.id,
            approval.destination,
            "idem-stale-01",
        )
    assert service.list_build_jobs(project.id) == []
    assert runner.calls == []


def test_used_approval_can_only_be_consumed_once(build_env):
    service, _, _, runner, output_dir = build_env
    project = service.create_project("Un solo uso")
    saved = save_revision(service, project.id)
    approval = prepare_approval(service, project.id, saved)

    job, created = service.request_build(
        project.id,
        approval.id,
        approval.destination,
        "idem-one-use-01",
    )
    assert created is True
    assert job.state in {"queued", "running", "completed"}
    completed = service.wait_for_job(project.id, job.id)
    assert completed.state == "completed"
    assert (output_dir / approval.destination).is_file()
    assert len(runner.calls) == 1

    used = service.get_build_approval(project.id, approval.id)
    assert used.status == "used"
    assert used.job_id == job.id
    assert used.consumed_at is not None

    with pytest.raises(BuildApprovalConsumedError):
        service.request_build(
            project.id,
            approval.id,
            approval.destination,
            "idem-one-use-02",
        )
    assert len(service.list_build_jobs(project.id)) == 1
    assert len(runner.calls) == 1


def test_request_rejects_an_unsafe_destination_before_consuming(build_env):
    service, _, _, runner, _ = build_env
    project = service.create_project("Solicitud insegura")
    saved = save_revision(service, project.id)
    approval = prepare_approval(service, project.id, saved)

    with pytest.raises(BuildDestinationError) as error:
        service.request_build(
            project.id,
            approval.id,
            "C:/tmp/escape.sldprt",
            "idem-unsafe-01",
        )
    assert error.value.reason == "absolute"
    assert service.get_build_approval(project.id, approval.id).status == "valid"
    assert service.list_build_jobs(project.id) == []
    assert runner.calls == []


def test_destination_mismatch_does_not_consume_the_approval(build_env):
    service, _, _, runner, _ = build_env
    project = service.create_project("Destino distinto")
    saved = save_revision(service, project.id)
    approval = prepare_approval(service, project.id, saved)

    with pytest.raises(BuildDestinationMismatchError):
        service.request_build(
            project.id,
            approval.id,
            "parts/other.sldprt",
            "idem-mismatch-01",
        )
    assert service.get_build_approval(project.id, approval.id).status == "valid"
    assert service.list_build_jobs(project.id) == []
    assert runner.calls == []


def test_idempotency_key_returns_the_same_job(build_env):
    service, _, _, runner, _ = build_env
    project = service.create_project("Idempotencia")
    saved = save_revision(service, project.id)
    approval = prepare_approval(service, project.id, saved)

    first, created = service.request_build(
        project.id, approval.id, approval.destination, "idem-same-01"
    )
    second, created_again = service.request_build(
        project.id, approval.id, approval.destination, "idem-same-01"
    )

    assert created is True
    assert created_again is False
    assert first.id == second.id
    assert len(service.list_build_jobs(project.id)) == 1
    completed = service.wait_for_job(project.id, first.id)
    assert completed.state == "completed"
    assert len(runner.calls) == 1
    assert service.get_build_approval(project.id, approval.id).status == "used"

    after_completion, created_after = service.request_build(
        project.id, approval.id, approval.destination, "idem-same-01"
    )
    assert created_after is False
    assert after_completion.id == first.id
    assert after_completion.state == "completed"
    assert len(runner.calls) == 1


def test_idempotency_key_conflict_is_rejected(build_env):
    service, _, _, _, _ = build_env
    project = service.create_project("Conflicto")
    saved = save_revision(service, project.id)
    first = prepare_approval(
        service, project.id, saved, destination="parts/first.sldprt"
    )
    second = prepare_approval(
        service, project.id, saved, destination="parts/second.sldprt"
    )
    service.request_build(
        project.id, first.id, first.destination, "idem-conflict-01"
    )

    with pytest.raises(BuildJobConflictError) as error:
        service.request_build(
            project.id, second.id, second.destination, "idem-conflict-01"
        )
    assert error.value.reason == "idempotency_key"
    assert len(service.list_build_jobs(project.id)) == 1


def test_two_concurrent_consumers_create_one_job(build_env):
    service, _, _, runner, _ = build_env
    project = service.create_project("Concurrencia")
    saved = save_revision(service, project.id)
    approval = prepare_approval(service, project.id, saved)
    barrier = Barrier(2)

    def attempt(key: str):
        barrier.wait()
        try:
            job, created = service.request_build(
                project.id,
                approval.id,
                approval.destination,
                key,
            )
            return "ok", job.id, created
        except BuildApprovalConsumedError as error:
            return "consumed", error.approval_id, False

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ["idem-race-a1", "idem-race-b1"]))

    assert sorted(result[0] for result in results) == ["consumed", "ok"]
    jobs = service.list_build_jobs(project.id)
    assert len(jobs) == 1
    assert service.wait_for_job(project.id, jobs[0].id).state == "completed"
    assert len(runner.calls) == 1


def test_two_concurrent_requests_with_same_key_are_idempotent(build_env):
    service, _, _, runner, _ = build_env
    project = service.create_project("Concurrencia idempotente")
    saved = save_revision(service, project.id)
    approval = prepare_approval(service, project.id, saved)
    barrier = Barrier(2)

    def attempt():
        barrier.wait()
        return service.request_build(
            project.id,
            approval.id,
            approval.destination,
            "idem-race-same-01",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt(), range(2)))

    assert sorted(created for _, created in results) == [False, True]
    assert len({job.id for job, _ in results}) == 1
    assert len(service.list_build_jobs(project.id)) == 1
    service.wait_for_job(project.id, results[0][0].id)
    assert len(runner.calls) == 1


def test_completed_job_records_a_new_artifact_without_paths(build_env):
    service, _, _, runner, output_dir = build_env
    project = service.create_project("Artefacto")
    saved = save_revision(service, project.id)
    approval = prepare_approval(service, project.id, saved)

    job, _ = service.request_build(
        project.id, approval.id, approval.destination, "idem-artifact-01"
    )
    completed = service.wait_for_job(project.id, job.id)

    expected = runner.content
    assert completed.state == "completed"
    assert completed.created_at
    assert completed.started_at
    assert completed.finished_at
    assert completed.error_code is None
    assert completed.artifact_name == approval.destination
    assert completed.artifact_sha256 == hashlib.sha256(expected).hexdigest()
    assert completed.artifact_byte_size == len(expected)
    assert completed.destination == approval.destination
    assert str(output_dir) not in repr(completed)
    assert (output_dir / approval.destination).read_bytes() == expected


def test_failed_job_retry_does_not_consume_the_approval_again(build_env):
    service, store, _, _, output_dir = build_env
    project = service.create_project("Reintento")
    saved = save_revision(service, project.id)
    approval = prepare_approval(service, project.id, saved)
    flaky = RecordingRunner(
        outcomes=[
            BuildExecutionError("RUNNER_TIMEOUT", "timeout"),
            None,
        ]
    )
    service._runner = flaky  # narrow test hook for the same in-process queue

    job, _ = service.request_build(
        project.id, approval.id, approval.destination, "idem-retry-01"
    )
    failed = service.wait_for_job(project.id, job.id)
    assert failed.state == "failed"
    assert failed.error_code == "RUNNER_TIMEOUT"
    assert failed.attempt == 1
    assert service.get_build_approval(project.id, approval.id).status == "used"
    assert not (output_dir / approval.destination).exists()

    retried, changed = service.retry_build_job(project.id, job.id)
    assert changed is True
    assert retried.id == job.id
    assert retried.state in {"queued", "running"}
    completed = service.wait_for_job(project.id, job.id)
    assert completed.state == "completed"
    assert completed.attempt == 2
    assert completed.error_code is None
    assert len(flaky.calls) == 2
    assert len(service.list_build_jobs(project.id)) == 1
    assert len(service.list_build_approvals(project.id)) == 1
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM build_consumptions WHERE approval_id = ?",
            (approval.id,),
        ).fetchone()[0] == 1
    assert (output_dir / approval.destination).is_file()

    unchanged, changed_again = service.retry_build_job(project.id, job.id)
    assert changed_again is False
    assert unchanged.state == "completed"
    assert len(flaky.calls) == 2


def test_retry_rejects_a_destination_created_after_failure(build_env):
    service, _, _, _, output_dir = build_env
    project = service.create_project("Reintento ocupado")
    saved = save_revision(service, project.id)
    approval = prepare_approval(service, project.id, saved)
    service._runner = RecordingRunner(
        outcomes=[BuildExecutionError("RUNNER_TIMEOUT", "timeout")]
    )

    job, _ = service.request_build(
        project.id, approval.id, approval.destination, "idem-retry-02"
    )
    assert service.wait_for_job(project.id, job.id).state == "failed"
    destination = output_dir / approval.destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"someone else")

    with pytest.raises(BuildDestinationError) as error:
        service.retry_build_job(project.id, job.id)
    assert error.value.reason == "exists"
    assert destination.read_bytes() == b"someone else"


def test_job_fails_stale_if_revision_changes_before_execution(build_env):
    service, store, clock, runner, _ = build_env
    project = service.create_project("Cambio en cola")
    saved = save_revision(service, project.id)
    approval = prepare_approval(service, project.id, saved)

    service._queue.stop()
    job, _ = service.request_build(
        project.id, approval.id, approval.destination, "idem-stale-worker-1"
    )
    save_revision(service, project.id)

    service._process_build_job(job.id)
    failed = service.get_build_job(project.id, job.id)
    assert failed.state == "failed"
    assert failed.error_code == "APPROVAL_STALE"
    assert runner.calls == []


def test_retry_resumes_a_durable_queued_job_after_queue_restart(build_env):
    service, store, clock, runner, output_dir = build_env
    project = service.create_project("Cola persistente")
    saved = save_revision(service, project.id)
    approval = prepare_approval(service, project.id, saved)

    service._queue.stop()
    job, _ = service.request_build(
        project.id, approval.id, approval.destination, "idem-queue-restart-1"
    )
    assert job.state == "queued"

    resumed_service = ProjectService(
        store,
        build_output_dir=output_dir,
        build_runner=runner,
        now=clock,
    )
    try:
        resumed, changed = resumed_service.retry_build_job(project.id, job.id)
        assert changed is False
        assert resumed.state == "queued"
        completed = resumed_service.wait_for_job(project.id, job.id)
        assert completed.state == "completed"
        assert completed.attempt == 1
        assert len(runner.calls) == 1
        assert (output_dir / approval.destination).is_file()
    finally:
        resumed_service.shutdown()


def test_build_records_are_append_only_in_sqlite(build_env):
    service, store, _, _, _ = build_env
    project = service.create_project("Append only")
    saved = save_revision(service, project.id)
    approval = prepare_approval(service, project.id, saved)
    job, _ = service.request_build(
        project.id, approval.id, approval.destination, "idem-append-01"
    )
    service.wait_for_job(project.id, job.id)

    with sqlite3.connect(store.database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE build_approvals SET approved_by = 'Otra' WHERE id = ?",
                (approval.id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "DELETE FROM build_approvals WHERE id = ?", (approval.id,)
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE build_consumptions SET consumed_at = 'other' "
                "WHERE approval_id = ?",
                (approval.id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM build_jobs WHERE id = ?", (job.id,))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE build_jobs SET destination = 'other.sldprt' WHERE id = ?",
                (job.id,),
            )
        original = connection.execute(
            "SELECT approved_by, destination, expires_at FROM build_approvals "
            "WHERE id = ?",
            (approval.id,),
        ).fetchone()
        consumption = connection.execute(
            "SELECT approval_id, job_id FROM build_consumptions "
            "WHERE approval_id = ?",
            (approval.id,),
        ).fetchone()
    assert original == ("Ana Revisora", approval.destination, approval.expires_at)
    assert consumption == (approval.id, job.id)


def test_v4_database_migrates_to_v5_and_preserves_approvals(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database_path = data_dir / "autosolid.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(_SCHEMA_V1)
        connection.executescript(_SCHEMA_V2)
        connection.executescript(_SCHEMA_V3)
        connection.executescript(_SCHEMA_V4)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (1, 'old')"
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (2, 'old')"
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (3, 'old')"
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (4, 'old')"
        )
        connection.execute("PRAGMA user_version = 4")
        connection.execute(
            "INSERT INTO projects(id, name, current_revision, created_at, updated_at) "
            "VALUES ('prj_v4', 'Migrado', 1, ?, ?)",
            (TIMESTAMP, TIMESTAMP),
        )
        spec_json = revolve_spec().model_copy(
            update={"project_id": "prj_v4", "revision": 1}
        ).model_dump_json()
        sha256 = hashlib.sha256(spec_json.encode("utf-8")).hexdigest()
        connection.execute(
            "INSERT INTO revisions(project_id, revision, spec_json, sha256, created_at) "
            "VALUES ('prj_v4', 1, ?, ?, ?)",
            (spec_json, sha256, TIMESTAMP),
        )
        connection.execute(
            "INSERT INTO approvals("
            "id, project_id, revision, revision_sha256, scope, approved_by, note, "
            "created_at) VALUES ('apr_old', 'prj_v4', 1, ?, 'design', 'Ana', "
            "NULL, ?)",
            (sha256, TIMESTAMP),
        )
        connection.commit()

    store = ProjectStore(data_dir)
    try:
        assert store.get_project("prj_v4").name == "Migrado"
        assert store.get_revision("prj_v4", 1).sha256 == sha256
        assert store.list_approvals("prj_v4")[0].id == "apr_old"
        assert store.list_build_approvals("prj_v4") == []
        with sqlite3.connect(database_path) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == (
                SCHEMA_VERSION
            )
            assert connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall() == [(1,), (2,), (3,), (4,), (5,)]
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert {"build_approvals", "build_jobs", "build_consumptions"} <= tables
    finally:
        store.close()


def _simulated_runner(
    mode: str,
    *,
    timeout: float = 10.0,
    max_output_bytes: int = 16 * 1024,
    delay: float | None = None,
    difference: float | None = None,
) -> SubprocessSolidWorksRunner:
    environment = {"AUTOSOLID_SIMULATED_MODE": mode}
    if delay is not None:
        environment["AUTOSOLID_SIMULATED_DELAY"] = str(delay)
    if difference is not None:
        environment["AUTOSOLID_SIMULATED_VOLUME_DIFFERENCE"] = str(difference)
    return SubprocessSolidWorksRunner(
        sys.executable,
        arguments_prefix=(str(SIMULATED_AGENT),),
        timeout_seconds=timeout,
        max_output_bytes=max_output_bytes,
        environment=environment,
    )


def _runner_paths(tmp_path):
    root = tmp_path / "runner-output"
    root.mkdir()
    spec = tmp_path / "spec.json"
    spec.write_text("{}", encoding="utf-8")
    return root, spec, root / "part.sldprt"


def test_subprocess_runner_accepts_the_simulated_contract(tmp_path):
    root, spec, output = _runner_paths(tmp_path)
    runner = _simulated_runner("ok")

    result = runner.build(spec, output, output_root=root)

    assert result.volume_m3 == pytest.approx(0.000008)
    assert result.volume_difference_m3 == 0.0
    assert result.errors == 0
    assert output.read_bytes().startswith(b"SIMULATED-SLDPRT")


def test_subprocess_runner_rejects_invalid_json(tmp_path):
    root, spec, output = _runner_paths(tmp_path)
    runner = _simulated_runner("invalid_json")

    with pytest.raises(BuildExecutionError) as error:
        runner.build(spec, output, output_root=root)
    assert error.value.code == "RUNNER_OUTPUT_INVALID"
    assert not output.exists()


def test_subprocess_runner_enforces_timeout(tmp_path):
    root, spec, output = _runner_paths(tmp_path)
    runner = _simulated_runner("timeout", timeout=0.3, delay=30)

    with pytest.raises(BuildExecutionError) as error:
        runner.build(spec, output, output_root=root)
    assert error.value.code == "RUNNER_TIMEOUT"


def test_subprocess_runner_rejects_volume_difference(tmp_path):
    root, spec, output = _runner_paths(tmp_path)
    runner = _simulated_runner("volume_mismatch", difference=1e-3)

    with pytest.raises(BuildExecutionError) as error:
        runner.build(spec, output, output_root=root)
    assert error.value.code == "VOLUME_MISMATCH"


def test_subprocess_runner_rejects_non_finite_volume(tmp_path):
    root, spec, output = _runner_paths(tmp_path)
    runner = _simulated_runner("non_finite")

    with pytest.raises(BuildExecutionError) as error:
        runner.build(spec, output, output_root=root)
    assert error.value.code == "RUNNER_OUTPUT_INVALID"


def test_subprocess_runner_reports_rebuild_failure(tmp_path):
    root, spec, output = _runner_paths(tmp_path)
    runner = _simulated_runner("rebuild_failed")

    with pytest.raises(BuildExecutionError) as error:
        runner.build(spec, output, output_root=root)
    assert error.value.code == "RUNNER_REBUILD_FAILED"


def test_subprocess_runner_requires_the_output_file(tmp_path):
    root, spec, output = _runner_paths(tmp_path)
    runner = _simulated_runner("no_output")

    with pytest.raises(BuildExecutionError) as error:
        runner.build(spec, output, output_root=root)
    assert error.value.code == "OUTPUT_MISSING"
    assert not output.exists()


def test_subprocess_runner_rejects_output_outside_authorized_root(tmp_path):
    root, spec, output = _runner_paths(tmp_path)
    outside = tmp_path / "outside.sldprt"
    runner = _simulated_runner("ok")

    with pytest.raises(BuildExecutionError) as error:
        runner.build(spec, outside, output_root=root)
    assert error.value.code == "OUTPUT_OUTSIDE_ROOT"
    assert not outside.exists()


def test_subprocess_runner_bounds_captured_output(tmp_path):
    root, spec, output = _runner_paths(tmp_path)
    runner = _simulated_runner("huge_output", max_output_bytes=4096)

    with pytest.raises(BuildExecutionError) as error:
        runner.build(spec, output, output_root=root)
    assert error.value.code == "RUNNER_OUTPUT_TOO_LARGE"


def test_service_reports_a_missing_runner_without_creating_a_file(tmp_path):
    store = ProjectStore(tmp_path / "data")
    root = tmp_path / "output"
    clock = Clock()
    service = ProjectService(
        store,
        build_output_dir=root,
        build_runner=UnavailableSolidWorksRunner(),
        now=clock,
    )
    try:
        project = service.create_project("Sin runner")
        saved = save_revision(service, project.id)
        approval = prepare_approval(service, project.id, saved)
        job, _ = service.request_build(
            project.id, approval.id, approval.destination, "idem-no-runner-01"
        )
        failed = service.wait_for_job(project.id, job.id)
        assert failed.state == "failed"
        assert failed.error_code == "SOLIDWORKS_NOT_CONFIGURED"
        assert not (root / approval.destination).exists()
    finally:
        service.shutdown()
        store.close()


def test_service_completes_a_job_with_the_simulated_subprocess(tmp_path):
    store = ProjectStore(tmp_path / "data")
    root = tmp_path / "output"
    clock = Clock()
    service = ProjectService(
        store,
        build_output_dir=root,
        build_runner=_simulated_runner("ok"),
        now=clock,
    )
    try:
        project = service.create_project("Runner simulado")
        saved = save_revision(service, project.id)
        approval = prepare_approval(service, project.id, saved)
        job, _ = service.request_build(
            project.id, approval.id, approval.destination, "idem-sim-01"
        )
        completed = service.wait_for_job(project.id, job.id)
        assert completed.state == "completed"
        assert completed.artifact_name == approval.destination
        assert (root / approval.destination).is_file()
        assert completed.error_code is None
    finally:
        service.shutdown()
        store.close()


def test_destination_resolution_hash_follows_platform_case_rules(tmp_path):
    root = tmp_path / "output"
    first = resolve_destination(root, "Parts/Block.sldprt")
    second = resolve_destination(root, "parts/block.sldprt")
    if os.name == "nt":
        assert first.destination_hash == second.destination_hash
    else:
        assert first.destination_hash != second.destination_hash
    assert first.relative != second.relative


def test_build_approval_json_does_not_contain_the_output_root(build_env):
    service, _, _, _, output_dir = build_env
    project = service.create_project("Privacidad")
    saved = save_revision(service, project.id)
    approval = prepare_approval(service, project.id, saved)
    job, _ = service.request_build(
        project.id, approval.id, approval.destination, "idem-privacy-01"
    )
    completed = service.wait_for_job(project.id, job.id)

    encoded = json.dumps(
        {
            "approval": approval.__dict__,
            "job": completed.__dict__,
        },
        default=str,
    )
    assert str(output_dir) not in encoded
    assert str(Path.home()) not in encoded
