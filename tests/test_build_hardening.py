from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import autosolid.projects.service as service_module
from autosolid.build import (
    BuildExecutionError,
    BuildExecutionResult,
    DestinationError,
    ResolvedDestination,
    SerialJobQueue,
    SubprocessSolidWorksRunner,
    resolve_destination,
)
from autosolid.build.runner import _finite_number
from autosolid.projects import (
    BuildDestinationError,
    ProjectService,
    ProjectStore,
)
from tests.builders import revolve_spec

SIMULATED_AGENT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "autosolid"
    / "build"
    / "simulated_agent.py"
)


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


class BlockingRunner(RecordingRunner):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def build(self, spec_path, output_path, *, output_root):
        self.started.set()
        if not self.release.wait(timeout=10):
            raise AssertionError("La prueba no liberó el runner bloqueado.")
        return super().build(
            spec_path,
            output_path,
            output_root=output_root,
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


def save_revision(service: ProjectService, project_id: str):
    project = service.get_project(project_id)
    return service.save_cadspec(
        project_id,
        project.current_revision,
        payload_for(revolve_spec(), project_id),
    )


def prepare_build(
    service: ProjectService,
    *,
    destination: str = "parts/block-013.sldprt",
):
    project = service.create_project("Endurecimiento build")
    saved = save_revision(service, project.id)
    approval = service.create_build_approval(
        project.id,
        saved.revision,
        saved.sha256,
        "Ana Revisora",
        destination,
    )
    return project, approval


def wait_until(predicate, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("La condición no se cumplió dentro del plazo.")


def test_windows_destination_aliases_share_one_hash(tmp_path):
    if os.name != "nt":
        pytest.skip("Los alias con punto/espacio final son específicos de Windows.")

    root = tmp_path / "output"
    first = resolve_destination(root, "parts./Block.sldprt")
    second = resolve_destination(root, "parts/Block.sldprt")
    third = resolve_destination(root, "parts/Block.sldprt.")
    fourth = resolve_destination(root, "parts/Block.sldprt ")

    assert first.relative == "parts/Block.sldprt"
    assert {
        first.destination_hash,
        second.destination_hash,
        third.destination_hash,
        fourth.destination_hash,
    } == {first.destination_hash}


@pytest.mark.parametrize(
    "destination",
    [
        "CON.sldprt",
        "prn.sldprt",
        "AUX.sldprt",
        "nul.sldprt",
        "COM1.sldprt",
        "lpt9.sldprt",
        "parts/CON.sldprt",
        "parts/Prn.part.sldprt",
    ],
)
def test_windows_reserved_device_names_are_rejected(tmp_path, destination):
    root = tmp_path / "output"

    with pytest.raises(DestinationError) as error:
        resolve_destination(root, destination)
    assert error.value.reason == "reserved"


def _create_directory_link(target: Path, link: Path) -> bool:
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            check=False,
        )
        return completed.returncode == 0 and link.exists()
    return False


def test_symlink_out_of_the_output_root_is_rejected(tmp_path):
    root = tmp_path / "output"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "linked"
    if not _create_directory_link(outside, link):
        pytest.skip("La plataforma no permite enlaces de directorio.")

    with pytest.raises(DestinationError) as error:
        resolve_destination(root, "linked/escape.sldprt")
    assert error.value.reason == "escape"


def test_destination_is_rechecked_just_before_publish(
    build_env, tmp_path, monkeypatch
):
    service, store, clock, runner, output_dir = build_env
    project, approval = prepare_build(service)
    service._queue.stop()
    job, _ = service.request_build(
        project.id,
        approval.id,
        approval.destination,
        "idem-recheck-001",
    )

    original = service._resolve_destination
    calls = {"count": 0}

    def swapped(destination, *, require_absent):
        result = original(destination, require_absent=require_absent)
        calls["count"] += 1
        if calls["count"] == 2:
            # Simulate the destination being redirected after the initial check.
            return ResolvedDestination(
                root=result.root,
                path=tmp_path / "outside" / "escape.sldprt",
                relative=result.relative,
                destination_hash=result.destination_hash,
            )
        return result

    monkeypatch.setattr(service, "_resolve_destination", swapped)
    service._process_build_job(job.id)

    failed = service.get_build_job(project.id, job.id)
    assert failed.state == "failed"
    assert failed.error_code == "DESTINATION_CHANGED"
    assert not (output_dir / approval.destination).exists()
    assert not (tmp_path / "outside" / "escape.sldprt").exists()
    # The agent may have produced a private staging file, but publication was
    # stopped after the destination recheck.
    assert len(runner.calls) == 1


def test_failed_move_never_deletes_a_foreign_destination(tmp_path, monkeypatch):
    source = tmp_path / "missing-staging.sldprt"
    target = tmp_path / "parts" / "block.sldprt"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"created by another process")

    def no_hard_links(*args, **kwargs):
        raise OSError("hard links unavailable")

    monkeypatch.setattr(os, "link", no_hard_links)

    with pytest.raises(BuildExecutionError) as error:
        ProjectService._move_without_overwrite(source, target)

    assert error.value.code == "OUTPUT_WRITE_FAILED"
    assert target.read_bytes() == b"created by another process"


def test_move_uses_only_an_exclusive_hard_link(tmp_path, monkeypatch):
    source = tmp_path / "staging.sldprt"
    source.write_bytes(b"valid artifact")
    target = tmp_path / "parts" / "block.sldprt"
    target.parent.mkdir(parents=True)
    links: list[tuple[Path, Path]] = []
    real_link = os.link

    def recording_link(src, dst, *args, **kwargs):
        links.append((Path(src), Path(dst)))
        return real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "link", recording_link)

    ProjectService._move_without_overwrite(source, target)

    assert links == [(source, target)]
    assert target.read_bytes() == b"valid artifact"
    assert not source.exists()


def test_hard_link_failure_does_not_fall_back_to_copying(tmp_path, monkeypatch):
    source = tmp_path / "staging.sldprt"
    source.write_bytes(b"valid artifact")
    target = tmp_path / "parts" / "block.sldprt"
    target.parent.mkdir(parents=True)

    def no_hard_links(*args, **kwargs):
        raise OSError("hard links unavailable")

    def unexpected_copy(*args, **kwargs):
        raise AssertionError(
            "La publicación no debe copiar directamente al destino."
        )

    monkeypatch.setattr(os, "link", no_hard_links)
    monkeypatch.setattr(shutil, "copyfileobj", unexpected_copy)

    with pytest.raises(BuildExecutionError) as error:
        ProjectService._move_without_overwrite(source, target)

    assert error.value.code == "OUTPUT_WRITE_FAILED"
    assert not target.exists()
    assert source.read_bytes() == b"valid artifact"


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (OSError("hard links unavailable"), "OUTPUT_WRITE_FAILED"),
        (NotImplementedError("hard links unavailable"), "OUTPUT_WRITE_FAILED"),
        (FileExistsError("destination exists"), "DESTINATION_EXISTS"),
        (RuntimeError("publication interrupted"), None),
    ],
)
def test_no_publish_failure_path_unlinks_the_destination(
    tmp_path, monkeypatch, failure, expected_code
):
    source = tmp_path / "staging.sldprt"
    source.write_bytes(b"valid artifact")
    target = tmp_path / "parts" / "block.sldprt"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"created by another process")
    unlinked: list[Path] = []
    real_unlink_quiet = service_module._unlink_quiet

    def recording_unlink(path):
        unlinked.append(Path(path))
        return real_unlink_quiet(path)

    def failing_link(*args, **kwargs):
        raise failure

    monkeypatch.setattr(os, "link", failing_link)
    monkeypatch.setattr(service_module, "_unlink_quiet", recording_unlink)

    if expected_code is None:
        with pytest.raises(RuntimeError):
            ProjectService._move_without_overwrite(source, target)
    else:
        with pytest.raises(BuildExecutionError) as error:
            ProjectService._move_without_overwrite(source, target)
        assert error.value.code == expected_code

    assert target.read_bytes() == b"created by another process"
    assert target not in unlinked


def test_hard_link_failure_leaves_no_destination_for_a_build(
    build_env, monkeypatch
):
    service, store, clock, runner, output_dir = build_env
    project, approval = prepare_build(service)

    def no_hard_links(*args, **kwargs):
        raise OSError("hard links unavailable")

    monkeypatch.setattr(os, "link", no_hard_links)
    job, _ = service.request_build(
        project.id,
        approval.id,
        approval.destination,
        "idem-no-hard-links-01",
    )
    failed = service.wait_for_job(project.id, job.id)

    assert failed.state == "failed"
    assert failed.error_code == "OUTPUT_WRITE_FAILED"
    assert not (output_dir / approval.destination).exists()


def test_link_failure_keeps_a_foreign_file_created_at_publish_time(
    build_env, monkeypatch
):
    service, store, clock, runner, output_dir = build_env
    project, approval = prepare_build(service)
    destination = output_dir / approval.destination
    foreign = b"created by another process"

    def racing_link(source, target, *args, **kwargs):
        Path(target).write_bytes(foreign)
        raise OSError("hard links unavailable")

    monkeypatch.setattr(os, "link", racing_link)
    job, _ = service.request_build(
        project.id,
        approval.id,
        approval.destination,
        "idem-link-race-001",
    )
    failed = service.wait_for_job(project.id, job.id)

    assert failed.state == "failed"
    assert failed.error_code == "OUTPUT_WRITE_FAILED"
    assert destination.read_bytes() == foreign


def test_runtime_error_during_publication_leaves_no_partial_file(
    build_env, monkeypatch
):
    service, store, clock, runner, output_dir = build_env
    project, approval = prepare_build(service)

    def interrupted_link(*args, **kwargs):
        raise RuntimeError("publication interrupted")

    monkeypatch.setattr(os, "link", interrupted_link)
    job, _ = service.request_build(
        project.id,
        approval.id,
        approval.destination,
        "idem-runtime-publish-01",
    )
    failed = service.wait_for_job(project.id, job.id)

    assert failed.state == "failed"
    assert failed.error_code == "INTERNAL_ERROR"
    assert not (output_dir / approval.destination).exists()


def test_finish_failure_is_recovered_on_startup_without_rebuild(
    build_env, monkeypatch
):
    service, store, clock, runner, output_dir = build_env
    project, approval = prepare_build(service)
    original_finish = store.finish_build_job

    def failing_finish(*args, **kwargs):
        if kwargs.get("state") == "completed":
            raise RuntimeError("persistencia temporalmente no disponible")
        return original_finish(*args, **kwargs)

    monkeypatch.setattr(store, "finish_build_job", failing_finish)
    job, _ = service.request_build(
        project.id,
        approval.id,
        approval.destination,
        "idem-finish-fail-01",
    )
    destination = output_dir / approval.destination

    wait_until(
        lambda: destination.is_file()
        and store.get_build_job(project.id, job.id).artifact_sha256 is not None
    )
    service.shutdown()
    monkeypatch.setattr(store, "finish_build_job", original_finish)

    pending = store.get_build_job(project.id, job.id)
    assert pending.state == "running"
    expected = destination.read_bytes()

    resumed = ProjectService(
        store,
        build_output_dir=output_dir,
        build_runner=runner,
        now=clock,
    )
    try:
        resumed.recover_incomplete_build_jobs()
        completed = resumed.get_build_job(project.id, job.id)
    finally:
        resumed.shutdown()

    assert completed.state == "completed"
    assert completed.artifact_sha256 == hashlib.sha256(expected).hexdigest()
    assert completed.artifact_byte_size == len(expected)
    assert destination.read_bytes() == expected
    assert len(runner.calls) == 1


def test_retry_of_a_running_published_job_does_not_rebuild(
    build_env, monkeypatch
):
    service, store, clock, runner, output_dir = build_env
    project, approval = prepare_build(service)
    original_finish = store.finish_build_job

    def failing_finish(*args, **kwargs):
        if kwargs.get("state") == "completed":
            raise RuntimeError("persistencia temporalmente no disponible")
        return original_finish(*args, **kwargs)

    monkeypatch.setattr(store, "finish_build_job", failing_finish)
    job, _ = service.request_build(
        project.id,
        approval.id,
        approval.destination,
        "idem-finish-retry-01",
    )
    destination = output_dir / approval.destination
    wait_until(
        lambda: destination.is_file()
        and store.get_build_job(project.id, job.id).artifact_sha256 is not None
    )
    service.shutdown()
    monkeypatch.setattr(store, "finish_build_job", original_finish)

    retried, changed = service.retry_build_job(project.id, job.id)

    assert changed is False
    assert retried.state == "completed"
    assert len(runner.calls) == 1
    assert destination.read_bytes() == runner.content


def test_hash_failure_does_not_publish_and_retry_rebuilds(
    build_env, monkeypatch
):
    service, store, clock, runner, output_dir = build_env
    project, approval = prepare_build(service)
    original_digest = service_module._file_digest

    def failing_digest(path):
        raise OSError("no se pudo calcular el hash")

    monkeypatch.setattr(service_module, "_file_digest", failing_digest)
    job, _ = service.request_build(
        project.id,
        approval.id,
        approval.destination,
        "idem-hash-fail-01",
    )
    failed = service.wait_for_job(project.id, job.id)
    assert failed.state == "failed"
    assert failed.error_code == "OUTPUT_WRITE_FAILED"
    assert not (output_dir / approval.destination).exists()

    monkeypatch.setattr(service_module, "_file_digest", original_digest)
    retried, changed = service.retry_build_job(project.id, job.id)
    assert changed is True
    completed = service.wait_for_job(project.id, job.id)
    assert completed.state == "completed"
    assert len(runner.calls) == 2
    assert (output_dir / approval.destination).read_bytes() == runner.content


def test_publish_failure_does_not_publish_and_retry_rebuilds(
    build_env, monkeypatch
):
    service, store, clock, runner, output_dir = build_env
    project, approval = prepare_build(service)
    original_move = ProjectService._move_without_overwrite

    def failing_move(source, target):
        raise BuildExecutionError(
            "OUTPUT_WRITE_FAILED",
            "No se pudo publicar el archivo.",
        )

    monkeypatch.setattr(
        ProjectService,
        "_move_without_overwrite",
        staticmethod(failing_move),
    )
    job, _ = service.request_build(
        project.id,
        approval.id,
        approval.destination,
        "idem-publish-fail-01",
    )
    failed = service.wait_for_job(project.id, job.id)
    assert failed.state == "failed"
    assert failed.error_code == "OUTPUT_WRITE_FAILED"
    assert not (output_dir / approval.destination).exists()

    monkeypatch.setattr(
        ProjectService,
        "_move_without_overwrite",
        staticmethod(original_move),
    )
    _, changed = service.retry_build_job(project.id, job.id)
    assert changed is True
    completed = service.wait_for_job(project.id, job.id)
    assert completed.state == "completed"
    assert len(runner.calls) == 2


def test_running_job_without_artifact_is_a_recoverable_failure(build_env):
    service, store, clock, runner, output_dir = build_env
    project, approval = prepare_build(service)
    service._queue.stop()
    job, _ = service.request_build(
        project.id,
        approval.id,
        approval.destination,
        "idem-running-empty-01",
    )
    started = store.start_build_job(
        job.id,
        now=clock().isoformat(timespec="microseconds"),
    )
    assert started is not None and started.state == "running"

    service.recover_incomplete_build_jobs()
    failed = service.get_build_job(project.id, job.id)
    assert failed.state == "failed"
    assert failed.error_code == "OUTPUT_RECOVERY_FAILED"
    assert not (output_dir / approval.destination).exists()

    resumed = ProjectService(
        store,
        build_output_dir=output_dir,
        build_runner=runner,
        now=clock,
    )
    try:
        _, changed = resumed.retry_build_job(project.id, job.id)
        assert changed is True
        completed = resumed.wait_for_job(project.id, job.id)
    finally:
        resumed.shutdown()
    assert completed.state == "completed"
    assert (output_dir / approval.destination).is_file()


def test_partial_or_mismatched_artifact_is_not_rebuilt(build_env):
    service, store, clock, runner, output_dir = build_env
    project, approval = prepare_build(service)
    service._queue.stop()
    job, _ = service.request_build(
        project.id,
        approval.id,
        approval.destination,
        "idem-partial-recovery-01",
    )
    store.start_build_job(
        job.id,
        now=clock().isoformat(timespec="microseconds"),
    )
    expected = b"the expected complete artifact"
    store.record_build_job_artifact(
        job.id,
        now=clock().isoformat(timespec="microseconds"),
        artifact_name=approval.destination,
        artifact_sha256=hashlib.sha256(expected).hexdigest(),
        artifact_byte_size=len(expected),
    )
    destination = output_dir / approval.destination
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"partial file from another writer")

    service.recover_incomplete_build_jobs()
    failed = service.get_build_job(project.id, job.id)
    assert failed.state == "failed"
    assert failed.error_code == "OUTPUT_RECOVERY_FAILED"

    with pytest.raises(BuildDestinationError) as error:
        service.retry_build_job(project.id, job.id)
    assert error.value.reason == "exists"
    assert destination.read_bytes() == b"partial file from another writer"
    assert runner.calls == []


def test_build_jobs_insert_or_replace_is_blocked(build_env):
    service, store, clock, runner, output_dir = build_env
    project, approval = prepare_build(service)
    job, _ = service.request_build(
        project.id,
        approval.id,
        approval.destination,
        "idem-immutable-job-01",
    )
    service.wait_for_job(project.id, job.id)

    with sqlite3.connect(store.database_path) as connection:
        connection.execute("PRAGMA recursive_triggers = OFF")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT OR REPLACE INTO build_jobs "
                "SELECT * FROM build_jobs WHERE id = ?",
                (job.id,),
            )
        row = connection.execute(
            "SELECT id, state, destination FROM build_jobs WHERE id = ?",
            (job.id,),
        ).fetchone()
    assert row == (job.id, "completed", approval.destination)


def test_existing_database_receives_the_build_jobs_insert_trigger(build_env):
    service, store, clock, runner, output_dir = build_env
    project, _ = prepare_build(service)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DROP TRIGGER IF EXISTS build_jobs_immutable_insert")
        missing = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'trigger' AND name = 'build_jobs_immutable_insert'"
        ).fetchone()
    assert missing is None

    reopened = ProjectStore(store.data_dir)
    try:
        reopened.get_project(project.id)
        with sqlite3.connect(store.database_path) as connection:
            trigger = connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'trigger' "
                "AND name = 'build_jobs_immutable_insert'"
            ).fetchone()
    finally:
        reopened.close()
    assert trigger == ("build_jobs_immutable_insert",)


def test_stop_waits_for_the_active_job_and_does_not_start_queued_work():
    started = threading.Event()
    release = threading.Event()
    processed: list[str] = []

    def processor(job_id: str) -> None:
        if job_id == "slow":
            started.set()
            assert release.wait(timeout=10)
        processed.append(job_id)

    queue = SerialJobQueue(processor)
    assert queue.submit("slow") is True
    assert started.wait(timeout=5)
    assert queue.submit("queued-after-stop") is True

    stopper = threading.Thread(target=queue.stop)
    stopper.start()
    time.sleep(0.1)
    assert stopper.is_alive()
    release.set()
    stopper.join(timeout=5)

    assert not stopper.is_alive()
    assert processed == ["slow"]


def test_service_shutdown_waits_for_a_slow_runner(build_env):
    service, store, clock, _, output_dir = build_env
    blocking = BlockingRunner()
    service._runner = blocking
    project, approval = prepare_build(service)
    job, _ = service.request_build(
        project.id,
        approval.id,
        approval.destination,
        "idem-slow-shutdown-1",
    )
    assert blocking.started.wait(timeout=5)

    stopper = threading.Thread(target=service.shutdown)
    stopper.start()
    time.sleep(0.1)
    assert stopper.is_alive()
    blocking.release.set()
    stopper.join(timeout=10)

    assert not stopper.is_alive()
    completed = store.get_build_job(project.id, job.id)
    assert completed.state == "completed"
    assert (output_dir / approval.destination).is_file()
    # The service never closes the durable store; the API does it after stop.
    assert store.get_project(project.id).id == project.id


def test_huge_json_integer_is_a_stable_runner_error(tmp_path):
    root = tmp_path / "output"
    root.mkdir()
    spec = tmp_path / "spec.json"
    spec.write_text("{}", encoding="utf-8")
    runner = SubprocessSolidWorksRunner(
        sys.executable,
        arguments_prefix=(str(SIMULATED_AGENT),),
        timeout_seconds=10,
        environment={"AUTOSOLID_SIMULATED_MODE": "overflow_number"},
    )

    with pytest.raises(BuildExecutionError) as error:
        runner.build(spec, root / "part.sldprt", output_root=root)
    assert error.value.code == "RUNNER_OUTPUT_INVALID"
    assert not (root / "part.sldprt").exists()


def test_finite_number_rejects_overflow_directly():
    with pytest.raises(BuildExecutionError) as error:
        _finite_number(10**400)
    assert error.value.code == "RUNNER_OUTPUT_INVALID"


def test_timeout_kills_the_agent_tree_but_not_a_foreign_process(tmp_path):
    marker = tmp_path / "agent-child-marker.txt"
    foreign_marker = tmp_path / "foreign-marker.txt"
    script = tmp_path / "spawner.py"
    script.write_text(
        "import os, subprocess, sys, time\n"
        "code = (\n"
        "    \"import os, pathlib, time; time.sleep(1.5); \"\n"
        "    \"pathlib.Path(os.environ['CHILD_MARKER']).write_text('alive')\"\n"
        ")\n"
        "subprocess.Popen(\n"
        "    [sys.executable, '-c', code],\n"
        "    stdout=subprocess.DEVNULL,\n"
        "    stderr=subprocess.DEVNULL,\n"
        "    env=os.environ.copy(),\n"
        ")\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    foreign = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import pathlib, time; time.sleep(1.2); "
                f"pathlib.Path({str(foreign_marker)!r}).write_text('alive')"
            ),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    root = tmp_path / "output"
    root.mkdir()
    spec = tmp_path / "spec.json"
    spec.write_text("{}", encoding="utf-8")
    runner = SubprocessSolidWorksRunner(
        sys.executable,
        arguments_prefix=(str(script),),
        timeout_seconds=0.5,
        environment={"CHILD_MARKER": str(marker)},
    )
    try:
        with pytest.raises(BuildExecutionError) as error:
            runner.build(spec, root / "part.sldprt", output_root=root)
        assert error.value.code == "RUNNER_TIMEOUT"
        assert not (root / "part.sldprt").exists()
        time.sleep(2.2)
        assert not marker.exists()
        assert foreign_marker.exists()
    finally:
        if foreign.poll() is None:
            foreign.terminate()
        foreign.wait(timeout=5)
