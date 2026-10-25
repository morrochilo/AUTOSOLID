import json
import os
import subprocess
import sys
from pathlib import Path

import anyio
import jsonschema
import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from autosolid.cad.models import Question
from autosolid.mcp import (
    TOOL_DEFINITIONS,
    TOOL_NAMES,
    create_server,
    dispatch,
    main,
)
from autosolid.projects import ProjectService, ProjectStore, StoreClosedError
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


def create_project(service: ProjectService, name: str = "Pieza") -> str:
    outcome = call(service, "autosolid_project_create", {"name": name})
    assert outcome.is_error is False
    return outcome.payload["project"]["id"]


def test_tool_catalog_has_strict_input_and_output_schemas():
    assert TOOL_NAMES == (
        "autosolid_project_create",
        "autosolid_project_list",
        "autosolid_project_get",
        "autosolid_design_get",
        "autosolid_design_validate",
        "autosolid_design_update",
        "autosolid_source_list",
        "autosolid_source_get",
        "autosolid_source_read_text",
        "autosolid_approval_list",
        "autosolid_approval_get",
    )
    for definition in TOOL_DEFINITIONS:
        input_schema = definition.input_schema()
        output_schema = definition.output_schema()
        assert input_schema["type"] == "object"
        assert input_schema["additionalProperties"] is False
        assert "properties" in input_schema
        assert output_schema["type"] == "object"
        assert output_schema["additionalProperties"] is False

    schemas = {
        definition.name: definition.input_schema() for definition in TOOL_DEFINITIONS
    }
    assert set(schemas["autosolid_project_create"]["required"]) == {"name"}
    assert set(schemas["autosolid_project_get"]["required"]) == {"project_id"}
    assert set(schemas["autosolid_design_get"]["required"]) == {"project_id"}
    assert set(schemas["autosolid_design_validate"]["required"]) == {
        "project_id",
        "spec",
    }
    assert set(schemas["autosolid_design_update"]["required"]) == {
        "project_id",
        "expected_revision",
        "spec",
    }
    assert set(schemas["autosolid_source_list"]["required"]) == {"project_id"}
    assert set(schemas["autosolid_source_get"]["required"]) == {
        "project_id",
        "source_id",
    }
    assert set(schemas["autosolid_source_read_text"]["required"]) == {
        "project_id",
        "source_id",
    }
    assert set(schemas["autosolid_approval_list"]["required"]) == {
        "project_id"
    }
    assert set(schemas["autosolid_approval_get"]["required"]) == {
        "project_id",
        "approval_id",
    }


def test_tool_catalog_declares_titles_and_side_effect_annotations():
    definitions = {definition.name: definition for definition in TOOL_DEFINITIONS}
    assert all(definition.title for definition in definitions.values())

    for name in (
        "autosolid_project_list",
        "autosolid_project_get",
        "autosolid_design_get",
        "autosolid_design_validate",
        "autosolid_source_list",
        "autosolid_source_get",
        "autosolid_source_read_text",
        "autosolid_approval_list",
        "autosolid_approval_get",
    ):
        assert definitions[name].read_only is True
        assert definitions[name].idempotent is True
        assert definitions[name].destructive is False

    for name in ("autosolid_project_create", "autosolid_design_update"):
        assert definitions[name].read_only is False
        assert definitions[name].destructive is False


def test_server_initialization_metadata(tmp_path):
    store = ProjectStore(tmp_path / "data")
    server = create_server(store=store)
    options = server.create_initialization_options()
    assert options.server_name == "autosolid"
    assert options.server_version == "0.1.0"
    assert "AUTOSOLID_DATA_DIR" in options.instructions
    assert "expected_revision" in options.instructions
    assert "no confiable" in options.instructions
    assert "aprobación" in options.instructions
    store.close()


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == "AUTOSOLID MCP 0.1.0"


def test_project_tools_cover_success_and_expected_errors(service):
    created = call(service, "autosolid_project_create", {"name": "  Bancada  "})
    assert created.is_error is False
    assert set(created.payload) == {"ok", "project"}
    project = created.payload["project"]
    assert project["id"].startswith("prj_")
    assert project["name"] == "Bancada"
    assert project["current_revision"] == 0

    listed = call(service, "autosolid_project_list", {})
    assert listed.is_error is False
    assert [item["id"] for item in listed.payload["projects"]] == [project["id"]]
    assert call(service, "autosolid_project_list", None).is_error is False

    fetched = call(
        service, "autosolid_project_get", {"project_id": project["id"]}
    )
    assert fetched.is_error is False
    assert fetched.payload["project"] == project

    assert_error(
        call(service, "autosolid_project_get", {"project_id": "prj_missing"}),
        "PROJECT_NOT_FOUND",
    )
    assert_error(
        call(service, "autosolid_project_create", {"name": "   "}),
        "INVALID_PROJECT_NAME",
    )


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("autosolid_project_create", {}),
        ("autosolid_project_create", {"name": "Pieza", "extra": 1}),
        ("autosolid_project_create", {"name": 123}),
        ("autosolid_project_list", {"extra": 1}),
        ("autosolid_project_get", {"project_id": 1}),
        ("autosolid_design_validate", {"project_id": "prj_x", "spec": "bad"}),
        (
            "autosolid_design_update",
            {"project_id": "prj_x", "spec": {}},
        ),
        (
            "autosolid_design_update",
            {"project_id": "prj_x", "expected_revision": -1, "spec": {}},
        ),
        (
            "autosolid_design_update",
            {"project_id": "prj_x", "expected_revision": 0.0, "spec": {}},
        ),
    ],
)
def test_invalid_arguments_are_structured_and_do_not_touch_project(
    service, name, arguments
):
    assert_error(call(service, name, arguments), "INVALID_ARGUMENTS")
    assert service.list_projects() == []


def test_unknown_tool_returns_structured_error(service):
    error = assert_error(call(service, "autosolid_unknown", {}), "UNKNOWN_TOOL")
    assert error["details"] == {"tool": "autosolid_unknown"}


def test_design_get_is_missing_until_first_update(service):
    project_id = create_project(service)
    assert_error(
        call(service, "autosolid_design_get", {"project_id": project_id}),
        "CADSPEC_NOT_FOUND",
    )
    assert_error(
        call(service, "autosolid_design_get", {"project_id": "prj_missing"}),
        "PROJECT_NOT_FOUND",
    )


def test_design_validate_is_read_only(service):
    project_id = create_project(service)
    valid_payload = payload_for(revolve_spec(), project_id)

    validated = call(
        service,
        "autosolid_design_validate",
        {"project_id": project_id, "spec": valid_payload},
    )
    assert validated.is_error is False
    assert validated.payload["ok"] is True
    assert validated.payload["valid"] is True
    assert validated.payload["diagnostics"] == []
    assert validated.payload["current_revision"] == 0
    assert service.list_revisions(project_id) == []
    assert_error(
        call(service, "autosolid_design_get", {"project_id": project_id}),
        "CADSPEC_NOT_FOUND",
    )

    invalid = call(
        service,
        "autosolid_design_validate",
        {
            "project_id": project_id,
            "spec": {"project_id": project_id, "unexpected": True},
        },
    )
    assert invalid.is_error is False
    assert invalid.payload["valid"] is False
    assert invalid.payload["diagnostics"][0]["code"] == "SCHEMA_INVALID"
    assert set(invalid.payload["diagnostics"][0]) == {
        "code",
        "severity",
        "path",
        "message",
    }


def test_design_update_persists_revision_and_decimals(service):
    project_id = create_project(service)
    spec = payload_for(revolve_spec(), project_id)

    updated = call(
        service,
        "autosolid_design_update",
        {"project_id": project_id, "expected_revision": 0, "spec": spec},
    )
    assert updated.is_error is False
    assert updated.payload["ok"] is True
    assert updated.payload["revision"] == 1
    assert updated.payload["project_id"] == project_id
    assert len(updated.payload["sha256"]) == 64
    assert (
        updated.payload["spec"]["parameters"]["outer_diameter"]["value"]
        == "50.000"
    )

    fetched = call(
        service, "autosolid_design_get", {"project_id": project_id}
    )
    assert fetched.is_error is False
    assert fetched.payload["revision"] == 1
    assert fetched.payload["sha256"] == updated.payload["sha256"]
    assert fetched.payload["spec"] == updated.payload["spec"]
    assert service.get_project(project_id).current_revision == 1


def test_design_update_reports_conflicts_and_invalid_specs(service):
    project_id = create_project(service)
    spec = payload_for(revolve_spec(), project_id)
    assert not call(
        service,
        "autosolid_design_update",
        {"project_id": project_id, "expected_revision": 0, "spec": spec},
    ).is_error

    conflict = assert_error(
        call(
            service,
            "autosolid_design_update",
            {"project_id": project_id, "expected_revision": 0, "spec": spec},
        ),
        "REVISION_CONFLICT",
    )
    assert conflict["details"] == {
        "expected_revision": 0,
        "current_revision": 1,
    }

    mismatch = assert_error(
        call(
            service,
            "autosolid_design_update",
            {
                "project_id": project_id,
                "expected_revision": 1,
                "spec": payload_for(revolve_spec(), "prj_other"),
            },
        ),
        "SPEC_INVALID",
    )
    assert any(
        item["code"] == "PROJECT_ID_MISMATCH"
        for item in mismatch["details"]
    )
    assert service.get_project(project_id).current_revision == 1

    critical = revolve_spec(
        open_questions=[
            Question(
                id="q_critical",
                text="¿Falta una cota?",
                severity="critical",
            )
        ]
    )
    critical_error = assert_error(
        call(
            service,
            "autosolid_design_update",
            {
                "project_id": project_id,
                "expected_revision": 1,
                "spec": payload_for(critical, project_id),
            },
        ),
        "SPEC_INVALID",
    )
    assert "QUESTION_CRITICAL_OPEN" in {
        item["code"] for item in critical_error["details"]
    }
    assert service.get_project(project_id).current_revision == 1


def test_success_and_error_payloads_match_declared_output_schemas(service):
    definitions = {definition.name: definition for definition in TOOL_DEFINITIONS}
    project_id = create_project(service)
    spec = payload_for(revolve_spec(), project_id)

    outcomes = [
        ("autosolid_project_list", call(service, "autosolid_project_list", {})),
        (
            "autosolid_design_validate",
            call(
                service,
                "autosolid_design_validate",
                {"project_id": project_id, "spec": spec},
            ),
        ),
        (
            "autosolid_design_get",
            call(service, "autosolid_design_get", {"project_id": "prj_missing"}),
        ),
    ]
    for name, outcome in outcomes:
        jsonschema.validate(
            instance=outcome.payload,
            schema=definitions[name].output_schema(),
        )


def test_unicode_is_preserved_in_arguments_and_responses(service):
    created = call(
        service,
        "autosolid_project_create",
        {"name": "Bancada Ñandú"},
    )
    assert created.is_error is False
    assert created.payload["project"]["name"] == "Bancada Ñandú"

    encoded = json.dumps(created.payload, ensure_ascii=False)
    assert "Ñandú" in encoded


def test_concurrent_design_updates_respect_optimistic_lock(tmp_path):
    store = ProjectStore(tmp_path / "data")
    server = create_server(store=store)
    results: list = []

    async def scenario():
        async with create_connected_server_and_client_session(server) as session:
            created = await session.call_tool(
                "autosolid_project_create", {"name": "Concurrente"}
            )
            project_id = created.structuredContent["project"]["id"]
            payload = payload_for(revolve_spec(), project_id)

            async def update():
                results.append(
                    await session.call_tool(
                        "autosolid_design_update",
                        {
                            "project_id": project_id,
                            "expected_revision": 0,
                            "spec": payload,
                        },
                    )
                )

            async with anyio.create_task_group() as task_group:
                task_group.start_soon(update)
                task_group.start_soon(update)

    anyio.run(scenario)
    assert len(results) == 2
    successes = [result for result in results if result.isError is False]
    conflicts = [result for result in results if result.isError is True]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert successes[0].structuredContent["revision"] == 1
    assert (
        conflicts[0].structuredContent["error"]["code"] == "REVISION_CONFLICT"
    )
    with pytest.raises(StoreClosedError):
        store.list_projects()


def test_unexpected_errors_do_not_leak_paths(service, tmp_path):
    def fail(_: str):
        raise RuntimeError(f"secret path {tmp_path}")

    service.create_project = fail
    outcome = call(service, "autosolid_project_create", {"name": "Pieza"})
    error = assert_error(outcome, "INTERNAL_ERROR")
    encoded = json.dumps(outcome.payload)
    assert str(tmp_path) not in encoded
    assert "RuntimeError" not in encoded
    assert "Traceback" not in encoded
    assert "secret" not in encoded
    assert error["message"] == "Se produjo un error interno."


def test_create_server_rejects_ambiguous_dependencies(tmp_path):
    store = ProjectStore(tmp_path / "data")
    service = ProjectService(store)
    with pytest.raises(ValueError):
        create_server(service=service, store=store)
    store.close()


def test_in_memory_protocol_lists_tools_and_persists(tmp_path):
    store = ProjectStore(tmp_path / "data")
    server = create_server(store=store)
    holder: list[str] = []

    async def scenario():
        async with create_connected_server_and_client_session(server) as session:
            listed = await session.list_tools()
            assert tuple(tool.name for tool in listed.tools) == TOOL_NAMES
            assert all(
                tool.inputSchema["additionalProperties"] is False
                for tool in listed.tools
            )
            tools = {tool.name: tool for tool in listed.tools}
            assert all(tool.title for tool in tools.values())
            assert tools["autosolid_design_get"].annotations.readOnlyHint is True
            assert (
                tools["autosolid_design_update"].annotations.readOnlyHint is False
            )
            assert (
                tools["autosolid_project_create"].annotations.destructiveHint
                is False
            )

            empty_list = await session.call_tool("autosolid_project_list")
            assert empty_list.isError is False
            assert empty_list.structuredContent["projects"] == []

            created = await session.call_tool(
                "autosolid_project_create", {"name": "Protocolo"}
            )
            assert created.isError is False
            assert created.structuredContent["ok"] is True
            project_id = created.structuredContent["project"]["id"]
            holder.append(project_id)
            assert json.loads(created.content[0].text) == created.structuredContent

            invalid = await session.call_tool(
                "autosolid_project_get",
                {"project_id": "prj_missing"},
            )
            assert invalid.isError is True
            assert invalid.structuredContent["error"]["code"] == "PROJECT_NOT_FOUND"

            invalid_arguments = await session.call_tool(
                "autosolid_design_update",
                {"project_id": project_id, "spec": {}},
            )
            assert invalid_arguments.isError is True
            assert (
                invalid_arguments.structuredContent["error"]["code"]
                == "INVALID_ARGUMENTS"
            )

            payload = payload_for(revolve_spec(), project_id)
            validated = await session.call_tool(
                "autosolid_design_validate",
                {"project_id": project_id, "spec": payload},
            )
            assert validated.isError is False
            assert validated.structuredContent["valid"] is True
            assert validated.structuredContent["diagnostics"] == []

            missing_spec = await session.call_tool(
                "autosolid_design_get", {"project_id": project_id}
            )
            assert missing_spec.isError is True
            assert (
                missing_spec.structuredContent["error"]["code"]
                == "CADSPEC_NOT_FOUND"
            )

            updated = await session.call_tool(
                "autosolid_design_update",
                {
                    "project_id": project_id,
                    "expected_revision": 0,
                    "spec": payload,
                },
            )
            assert updated.isError is False
            assert updated.structuredContent["revision"] == 1
            assert (
                updated.structuredContent["spec"]["parameters"]["outer_diameter"][
                    "value"
                ]
                == "50.000"
            )
            assert json.loads(updated.content[0].text) == updated.structuredContent

            conflict = await session.call_tool(
                "autosolid_design_update",
                {
                    "project_id": project_id,
                    "expected_revision": 0,
                    "spec": payload,
                },
            )
            assert conflict.isError is True
            assert (
                conflict.structuredContent["error"]["code"]
                == "REVISION_CONFLICT"
            )

            invalid_spec = await session.call_tool(
                "autosolid_design_update",
                {
                    "project_id": project_id,
                    "expected_revision": 1,
                    "spec": {"project_id": project_id, "unexpected": True},
                },
            )
            assert invalid_spec.isError is True
            assert invalid_spec.structuredContent["error"]["code"] == "SPEC_INVALID"

            fetched = await session.call_tool(
                "autosolid_design_get", {"project_id": project_id}
            )
            assert fetched.isError is False
            assert (
                fetched.structuredContent["sha256"]
                == updated.structuredContent["sha256"]
            )
            assert fetched.structuredContent["revision"] == 1

    anyio.run(scenario)
    assert holder
    with pytest.raises(StoreClosedError):
        store.list_projects()


def test_module_start_and_eof_do_not_write_to_stdout(tmp_path):
    root = Path(__file__).resolve().parents[1]
    data_dir = tmp_path / "silent-data"
    environment = dict(os.environ)
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(root / "src") + (
        os.pathsep + existing if existing else ""
    )
    environment["AUTOSOLID_DATA_DIR"] = str(data_dir)

    completed = subprocess.run(
        [sys.executable, "-m", "autosolid.mcp"],
        input="",
        capture_output=True,
        text=True,
        env=environment,
        cwd=str(root),
        timeout=30,
    )
    assert completed.returncode == 0
    assert completed.stdout == ""
    assert completed.stderr == ""
    assert data_dir.exists() is False


def test_stdio_protocol_starts_module_and_uses_environment(tmp_path):
    root = Path(__file__).resolve().parents[1]
    data_dir = tmp_path / "stdio-data"
    environment = dict(os.environ)
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(root / "src") + (
        os.pathsep + existing if existing else ""
    )
    environment["AUTOSOLID_DATA_DIR"] = str(data_dir)
    holder: list[str] = []

    async def scenario():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "autosolid.mcp"],
            env=environment,
            cwd=str(root),
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert tuple(tool.name for tool in listed.tools) == TOOL_NAMES
                assert all(
                    tool.inputSchema["additionalProperties"] is False
                    for tool in listed.tools
                )

                created = await session.call_tool(
                    "autosolid_project_create", {"name": "Stdio"}
                )
                assert created.isError is False
                project_id = created.structuredContent["project"]["id"]
                holder.append(project_id)

                payload = payload_for(revolve_spec(), project_id)
                updated = await session.call_tool(
                    "autosolid_design_update",
                    {
                        "project_id": project_id,
                        "expected_revision": 0,
                        "spec": payload,
                    },
                )
                assert updated.isError is False
                assert updated.structuredContent["revision"] == 1

                fetched = await session.call_tool(
                    "autosolid_design_get", {"project_id": project_id}
                )
                assert fetched.isError is False
                assert (
                    fetched.structuredContent["sha256"]
                    == updated.structuredContent["sha256"]
                )

    anyio.run(scenario)
    assert holder
    assert (data_dir / "autosolid.db").exists()
