import pytest

from autosolid.mcp import TOOLS_BY_NAME, dispatch
from autosolid.projects import ProjectService, ProjectStore
from tests.builders import revolve_spec


@pytest.fixture
def service(tmp_path):
    store = ProjectStore(tmp_path / "data")
    yield ProjectService(store)
    store.close()


def payload_for(spec, project_id: str) -> dict:
    payload = spec.model_dump(mode="json")
    payload["project_id"] = project_id
    return payload


def call(service: ProjectService, name: str, arguments: dict | None):
    return dispatch(service, name, arguments)


def assert_error(outcome, code: str) -> dict:
    assert outcome.is_error is True
    assert outcome.payload["ok"] is False
    assert set(outcome.payload) == {"ok", "error"}
    error = outcome.payload["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    assert isinstance(error["message"], str)
    return error


def create_project_and_revision(service: ProjectService, name: str = "MCP"):
    project = service.create_project(name)
    stored = service.save_cadspec(
        project.id,
        0,
        payload_for(revolve_spec(), project.id),
    )
    return project, stored


def save_next_revision(service: ProjectService, project_id: str) -> object:
    project = service.get_project(project_id)
    return service.save_cadspec(
        project_id,
        project.current_revision,
        payload_for(revolve_spec(), project_id),
    )


def test_approval_tools_are_read_only_and_exist():
    assert "autosolid_approval_list" in TOOLS_BY_NAME
    assert "autosolid_approval_get" in TOOLS_BY_NAME
    for name in ("autosolid_approval_list", "autosolid_approval_get"):
        definition = TOOLS_BY_NAME[name]
        assert definition.read_only is True
        assert definition.idempotent is True
        assert definition.destructive is False

    for name in (
        "autosolid_approval_create",
        "autosolid_approval_approve",
        "autosolid_approval_revoke",
        "autosolid_approval_consume",
    ):
        assert name not in TOOLS_BY_NAME
        assert_error(call(None, name, {}), "UNKNOWN_TOOL")


def test_list_and_get_design_approval(service):
    project, stored = create_project_and_revision(service)

    empty = call(
        service, "autosolid_approval_list", {"project_id": project.id}
    )
    assert empty.is_error is False
    assert empty.payload == {
        "ok": True,
        "project_id": project.id,
        "approvals": [],
    }

    approval, _ = service.approve_revision(
        project.id,
        stored.revision,
        stored.sha256,
        "Ana Revisora",
        note="Revisado contra el plano.",
    )

    listed = call(service, "autosolid_approval_list", {"project_id": project.id})
    assert listed.is_error is False
    assert listed.payload["ok"] is True
    assert listed.payload["project_id"] == project.id
    assert listed.payload["approvals"] == [
        {
            "id": approval.id,
            "project_id": project.id,
            "revision": stored.revision,
            "revision_sha256": stored.sha256,
            "scope": "design",
            "approved_by": "Ana Revisora",
            "note": "Revisado contra el plano.",
            "created_at": approval.created_at,
            "status": "valid",
        }
    ]

    fetched = call(
        service,
        "autosolid_approval_get",
        {"project_id": project.id, "approval_id": approval.id},
    )
    assert fetched.is_error is False
    assert fetched.payload["ok"] is True
    assert fetched.payload["approval"] == listed.payload["approvals"][0]

    definition = TOOLS_BY_NAME["autosolid_approval_list"]
    definition.output_model.model_validate(listed.payload)


def test_approval_becomes_stale_after_a_new_revision(service):
    project, stored = create_project_and_revision(service)
    approval, _ = service.approve_revision(
        project.id, stored.revision, stored.sha256, "Ana"
    )
    new_revision = save_next_revision(service, project.id)

    listed = call(service, "autosolid_approval_list", {"project_id": project.id})
    assert listed.is_error is False
    assert [item["status"] for item in listed.payload["approvals"]] == ["stale"]

    fetched = call(
        service,
        "autosolid_approval_get",
        {"project_id": project.id, "approval_id": approval.id},
    )
    assert fetched.is_error is False
    assert fetched.payload["approval"]["status"] == "stale"
    assert (
        fetched.payload["approval"]["revision_sha256"] == stored.sha256
    )
    assert new_revision.revision == 2


def test_approval_tools_report_stable_errors(service):
    project, stored = create_project_and_revision(service)
    approval, _ = service.approve_revision(
        project.id, stored.revision, stored.sha256, "Ana"
    )
    other = service.create_project("Otro")
    service.save_cadspec(
        other.id,
        0,
        payload_for(revolve_spec(), other.id),
    )

    error = assert_error(
        call(service, "autosolid_approval_list", {"project_id": "prj_missing"}),
        "PROJECT_NOT_FOUND",
    )
    assert error["details"] == {"project_id": "prj_missing"}

    error = assert_error(
        call(
            service,
            "autosolid_approval_get",
            {"project_id": other.id, "approval_id": approval.id},
        ),
        "APPROVAL_NOT_FOUND",
    )
    assert error["details"] == {
        "project_id": other.id,
        "approval_id": approval.id,
    }

    assert_error(
        call(
            service,
            "autosolid_approval_get",
            {"project_id": project.id},
        ),
        "INVALID_ARGUMENTS",
    )
    assert_error(
        call(
            service,
            "autosolid_approval_list",
            {"project_id": project.id, "unexpected": True},
        ),
        "INVALID_ARGUMENTS",
    )
    assert_error(
        call(service, "autosolid_approval_list", {"project_id": ""}),
        "INVALID_ARGUMENTS",
    )
    assert_error(
        call(service, "autosolid_approval_list", {"project_id": 3}),
        "INVALID_ARGUMENTS",
    )


def test_approval_tools_do_not_mutate_revisions(service):
    project, stored = create_project_and_revision(service)
    before = service.get_project(project.id)

    call(service, "autosolid_approval_list", {"project_id": project.id})

    after = service.get_project(project.id)
    assert after == before
    assert service.list_approvals(project.id) == []
    assert service.get_cadspec(project.id).sha256 == stored.sha256
