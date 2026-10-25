import json

import anyio
import jsonschema
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from autosolid.mcp import TOOL_DEFINITIONS, create_server, dispatch
from autosolid.projects import ProjectService, ProjectStore


def pdf_bytes(marker: bytes = b"1") -> bytes:
    return b"%PDF-1.7\n%" + marker + b"\n%%EOF\n"


def text_bytes(value: str = "Cota 40 mm") -> bytes:
    return value.encode("utf-8")


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


@pytest.fixture
def service(tmp_path):
    store = ProjectStore(tmp_path / "data")
    yield ProjectService(store)
    store.close()


def test_source_list_and_get_metadata(service):
    project = service.create_project("Fuentes")
    empty = call(
        service,
        "autosolid_source_list",
        {"project_id": project.id},
    )
    assert empty.is_error is False
    assert empty.payload == {
        "ok": True,
        "project_id": project.id,
        "sources": [],
    }

    pdf, _ = service.add_source(project.id, "plano.pdf", pdf_bytes())
    note, _ = service.add_source(
        project.id, "nota técnica.txt", text_bytes("Cota 40 mm\n")
    )

    listed = call(
        service,
        "autosolid_source_list",
        {"project_id": project.id},
    )
    assert listed.is_error is False
    assert listed.payload["project_id"] == project.id
    assert [item["id"] for item in listed.payload["sources"]] == [
        pdf.id,
        note.id,
    ]
    assert listed.payload["sources"][0] == {
        "id": pdf.id,
        "project_id": project.id,
        "kind": "pdf",
        "filename": "plano.pdf",
        "sha256": pdf.sha256,
        "byte_size": pdf.byte_size,
        "media_type": "application/pdf",
        "created_at": pdf.created_at,
    }
    assert listed.payload["sources"][1]["filename"] == "nota técnica.txt"

    fetched = call(
        service,
        "autosolid_source_get",
        {"project_id": project.id, "source_id": note.id},
    )
    assert fetched.is_error is False
    assert fetched.payload["source"] == listed.payload["sources"][1]

    assert_error(
        call(
            service,
            "autosolid_source_list",
            {"project_id": "prj_missing"},
        ),
        "PROJECT_NOT_FOUND",
    )
    error = assert_error(
        call(
            service,
            "autosolid_source_get",
            {"project_id": project.id, "source_id": "src_missing"},
        ),
        "SOURCE_NOT_FOUND",
    )
    assert error["details"] == {
        "project_id": project.id,
        "source_id": "src_missing",
    }


def test_source_read_text_returns_utf8_without_bom(service):
    project = service.create_project("Texto")
    data = b"\xef\xbb\xbfCota 40 mm\n"
    source, _ = service.add_source(project.id, "nota.txt", data)

    outcome = call(
        service,
        "autosolid_source_read_text",
        {"project_id": project.id, "source_id": source.id},
    )
    assert outcome.is_error is False
    assert outcome.payload == {
        "ok": True,
        "project_id": project.id,
        "source_id": source.id,
        "filename": "nota.txt",
        "sha256": source.sha256,
        "byte_size": len(data),
        "text": "Cota 40 mm\n",
        "returned_chars": 11,
        "truncated": False,
    }


def test_source_read_text_truncates_by_characters(service):
    project = service.create_project("Truncado")
    original = "á" * 10 + "final"
    source, _ = service.add_source(
        project.id, "nota.txt", text_bytes(original)
    )

    outcome = call(
        service,
        "autosolid_source_read_text",
        {
            "project_id": project.id,
            "source_id": source.id,
            "max_chars": 5,
        },
    )
    assert outcome.is_error is False
    assert outcome.payload["text"] == "ááááá"
    assert outcome.payload["returned_chars"] == 5
    assert outcome.payload["truncated"] is True
    assert outcome.payload["byte_size"] == len(original.encode("utf-8"))
    assert outcome.payload["sha256"] == source.sha256


def test_source_read_text_rejects_non_text_sources(service):
    project = service.create_project("Binario")
    source, _ = service.add_source(project.id, "plano.pdf", pdf_bytes())

    error = assert_error(
        call(
            service,
            "autosolid_source_read_text",
            {"project_id": project.id, "source_id": source.id},
        ),
        "SOURCE_NOT_TEXT",
    )
    assert error["details"] == {
        "project_id": project.id,
        "source_id": source.id,
        "kind": "pdf",
    }


def test_source_read_text_reports_missing_and_corrupt_content(
    service, tmp_path
):
    project = service.create_project("Integridad")
    source, _ = service.add_source(project.id, "nota.txt", text_bytes())

    assert_error(
        call(
            service,
            "autosolid_source_read_text",
            {"project_id": project.id, "source_id": "src_missing"},
        ),
        "SOURCE_NOT_FOUND",
    )

    service.artifacts.path_for(source.sha256).write_bytes(b"texto corrupto")
    corrupt = assert_error(
        call(
            service,
            "autosolid_source_read_text",
            {"project_id": project.id, "source_id": source.id},
        ),
        "STORE_ERROR",
    )
    encoded = json.dumps(corrupt)
    assert str(tmp_path) not in encoded
    assert "artifacts" not in encoded
    assert "autosolid.db" not in encoded


def test_source_tools_reject_invalid_arguments(service):
    project = service.create_project("Argumentos")
    source, _ = service.add_source(project.id, "nota.txt", text_bytes())

    cases = [
        ("autosolid_source_list", {}),
        ("autosolid_source_list", {"project_id": 1}),
        ("autosolid_source_list", {"project_id": project.id, "extra": 1}),
        (
            "autosolid_source_get",
            {"project_id": project.id, "source_id": 1},
        ),
        (
            "autosolid_source_read_text",
            {"project_id": project.id, "source_id": source.id, "max_chars": 0},
        ),
        (
            "autosolid_source_read_text",
            {
                "project_id": project.id,
                "source_id": source.id,
                "max_chars": 100_001,
            },
        ),
        (
            "autosolid_source_read_text",
            {
                "project_id": project.id,
                "source_id": source.id,
                "max_chars": 1.0,
            },
        ),
    ]
    for name, arguments in cases:
        assert_error(call(service, name, arguments), "INVALID_ARGUMENTS")

    assert len(service.list_sources(project.id)) == 1


def test_source_success_and_error_payloads_match_declared_output_schemas(
    service,
):
    definitions = {definition.name: definition for definition in TOOL_DEFINITIONS}
    project = service.create_project("Esquemas")
    source, _ = service.add_source(project.id, "nota.txt", text_bytes())

    outcomes = [
        (
            "autosolid_source_list",
            call(
                service,
                "autosolid_source_list",
                {"project_id": project.id},
            ),
        ),
        (
            "autosolid_source_get",
            call(
                service,
                "autosolid_source_get",
                {"project_id": project.id, "source_id": source.id},
            ),
        ),
        (
            "autosolid_source_read_text",
            call(
                service,
                "autosolid_source_read_text",
                {"project_id": project.id, "source_id": source.id},
            ),
        ),
        (
            "autosolid_source_get",
            call(
                service,
                "autosolid_source_get",
                {"project_id": project.id, "source_id": "src_missing"},
            ),
        ),
    ]
    for name, outcome in outcomes:
        jsonschema.validate(
            instance=outcome.payload,
            schema=definitions[name].output_schema(),
        )


def test_source_tools_work_through_mcp_protocol(tmp_path):
    store = ProjectStore(tmp_path / "data")
    service = ProjectService(store)
    project = service.create_project("Protocolo de fuentes")
    source, _ = service.add_source(
        project.id, "nota.txt", text_bytes("Línea uno\nLínea dos\n")
    )
    server = create_server(service=service)
    holder: list[str] = []

    async def scenario():
        async with create_connected_server_and_client_session(server) as session:
            listed = await session.list_tools()
            assert tuple(tool.name for tool in listed.tools) == tuple(
                definition.name for definition in TOOL_DEFINITIONS
            )
            tools = {tool.name: tool for tool in listed.tools}
            assert tools["autosolid_source_list"].annotations.readOnlyHint is True
            assert (
                tools["autosolid_source_read_text"].annotations.idempotentHint
                is True
            )

            sources = await session.call_tool(
                "autosolid_source_list", {"project_id": project.id}
            )
            assert sources.isError is False
            assert sources.structuredContent["sources"][0]["id"] == source.id
            assert json.loads(sources.content[0].text) == sources.structuredContent

            text = await session.call_tool(
                "autosolid_source_read_text",
                {"project_id": project.id, "source_id": source.id},
            )
            assert text.isError is False
            assert text.structuredContent["text"] == "Línea uno\nLínea dos\n"
            assert text.structuredContent["truncated"] is False
            holder.append(text.structuredContent["source_id"])

            missing = await session.call_tool(
                "autosolid_source_get",
                {"project_id": project.id, "source_id": "src_missing"},
            )
            assert missing.isError is True
            assert (
                missing.structuredContent["error"]["code"]
                == "SOURCE_NOT_FOUND"
            )

    anyio.run(scenario)
    assert holder == [source.id]
