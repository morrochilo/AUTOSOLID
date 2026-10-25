import hashlib

import pytest
from fastapi.testclient import TestClient

from autosolid.api import create_app
from autosolid.projects import ProjectStore

API = "/api/v1"


def pdf_bytes(marker: bytes = b"1") -> bytes:
    return b"%PDF-1.7\n%" + marker + b"\n%%EOF\n"


def create_project(client: TestClient, name: str = "Fuentes") -> dict:
    response = client.post(f"{API}/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    return body["error"]


@pytest.fixture
def client_and_app(tmp_path):
    store = ProjectStore(tmp_path / "data")
    app = create_app(store)
    with TestClient(app) as client:
        yield client, app, store


def upload(client, project_id, filename, data, **params):
    return client.post(
        f"{API}/projects/{project_id}/sources",
        params={"filename": filename, **params},
        content=data,
        headers={"Content-Type": "application/octet-stream"},
    )


def test_upload_list_get_and_download_source(client_and_app):
    client, _, _ = client_and_app
    project = create_project(client)
    data = pdf_bytes()

    response = upload(client, project["id"], "Plano principal.pdf", data)
    assert response.status_code == 201
    source = response.json()
    assert source["id"].startswith("src_")
    assert source["project_id"] == project["id"]
    assert source["kind"] == "pdf"
    assert source["filename"] == "Plano principal.pdf"
    assert source["sha256"] == hashlib.sha256(data).hexdigest()
    assert source["byte_size"] == len(data)
    assert source["media_type"] == "application/pdf"
    assert response.headers["location"] == (
        f"{API}/projects/{project['id']}/sources/{source['id']}"
    )

    listed = client.get(f"{API}/projects/{project['id']}/sources")
    assert listed.status_code == 200
    assert listed.json() == [source]

    fetched = client.get(
        f"{API}/projects/{project['id']}/sources/{source['id']}"
    )
    assert fetched.status_code == 200
    assert fetched.json() == source

    content = client.get(
        f"{API}/projects/{project['id']}/sources/{source['id']}/content"
    )
    assert content.status_code == 200
    assert content.content == data
    assert content.headers["content-type"] == "application/pdf"
    assert content.headers["etag"] == f'"{source["sha256"]}"'
    assert content.headers["x-content-sha256"] == source["sha256"]
    assert content.headers["x-content-type-options"] == "nosniff"
    assert content.headers["cache-control"].endswith("immutable")
    assert "attachment" in content.headers["content-disposition"]
    assert 'filename="Plano principal.pdf"' in content.headers[
        "content-disposition"
    ]
    assert "filename*=UTF-8''Plano%20principal.pdf" in content.headers[
        "content-disposition"
    ]


def test_duplicate_upload_is_idempotent_and_shares_artifact(client_and_app):
    client, _, store = client_and_app
    first_project = create_project(client, "Primero")
    second_project = create_project(client, "Segundo")
    data = pdf_bytes(b"shared")

    first = upload(client, first_project["id"], "plano.pdf", data)
    duplicate = upload(client, first_project["id"], "copia.pdf", data)
    other_project = upload(client, second_project["id"], "plano.pdf", data)

    assert first.status_code == 201
    assert duplicate.status_code == 200
    assert duplicate.json() == first.json()
    assert other_project.status_code == 201
    assert other_project.json()["id"] != first.json()["id"]
    assert other_project.json()["sha256"] == first.json()["sha256"]
    assert len(
        client.get(f"{API}/projects/{first_project['id']}/sources").json()
    ) == 1
    assert len(
        client.get(f"{API}/projects/{second_project['id']}/sources").json()
    ) == 1

    artifact_files = [
        path
        for path in (store.data_dir / "artifacts").rglob("*")
        if path.is_file()
    ]
    assert len(artifact_files) == 1


def test_upload_validates_extension_signature_kind_and_filename(client_and_app):
    client, _, _ = client_and_app
    project = create_project(client)

    cases = [
        ("plano.exe", b"%PDF-1.7\n", None, "unsupported_extension"),
        ("plano.pdf", b"no es pdf", None, "signature"),
        ("plano.pdf", b"%PDF-1.7\n", "image", "kind_mismatch"),
        ("nota.txt", b"\xff\xfe", None, "encoding"),
        ("../plano.pdf", b"%PDF-1.7\n", None, "filename"),
        ("carpeta\\plano.pdf", b"%PDF-1.7\n", None, "filename"),
    ]
    for filename, data, kind, reason in cases:
        response = upload(
            client,
            project["id"],
            filename,
            data,
            **({} if kind is None else {"kind": kind}),
        )
        error = assert_error(response, 422, "INVALID_SOURCE")
        assert error["details"] == {"reason": reason}
        assert str(project["id"]) not in error["message"]

    assert client.get(f"{API}/projects/{project['id']}/sources").json() == []
    missing = client.post(f"{API}/projects/{project['id']}/sources", content=b"")
    assert_error(missing, 422, "REQUEST_INVALID")

    empty = upload(client, project["id"], "vacio.pdf", b"")
    assert_error(empty, 422, "INVALID_SOURCE")


def test_upload_size_limit_returns_413(client_and_app):
    client, app, _ = client_and_app
    project = create_project(client)
    app.state.service.max_source_bytes = 16
    data = b"%PDF-1.7\n" + b"x" * 32

    response = upload(client, project["id"], "grande.pdf", data)
    error = assert_error(response, 413, "SOURCE_TOO_LARGE")
    assert error["details"]["limit_bytes"] == 16
    assert error["details"]["actual_bytes"] == len(data)
    assert client.get(f"{API}/projects/{project['id']}/sources").json() == []


def test_upload_text_and_unicode_filename(client_and_app):
    client, _, _ = client_and_app
    project = create_project(client)
    data = "Cota 40 mm\n".encode("utf-8")

    response = upload(client, project["id"], "nota técnica.txt", data)
    assert response.status_code == 201
    source = response.json()
    assert source["kind"] == "text"
    assert source["media_type"] == "text/plain"

    content = client.get(
        f"{API}/projects/{project['id']}/sources/{source['id']}/content"
    )
    assert content.status_code == 200
    assert content.content == data
    assert content.headers["content-type"] == "text/plain; charset=utf-8"
    disposition = content.headers["content-disposition"]
    assert "filename*=UTF-8''nota%20t%C3%A9cnica.txt" in disposition
    assert "\n" not in disposition


def test_missing_project_and_source_have_stable_errors(client_and_app):
    client, _, _ = client_and_app
    project = create_project(client)
    source = upload(client, project["id"], "plano.pdf", pdf_bytes()).json()

    assert_error(
        client.get(f"{API}/projects/prj_missing/sources"),
        404,
        "PROJECT_NOT_FOUND",
    )
    assert_error(
        client.get(f"{API}/projects/{project['id']}/sources/src_missing"),
        404,
        "SOURCE_NOT_FOUND",
    )
    assert_error(
        client.get(
            f"{API}/projects/{project['id']}/sources/src_missing/content"
        ),
        404,
        "SOURCE_NOT_FOUND",
    )
    assert_error(
        client.get(f"{API}/projects/prj_missing/sources/{source['id']}/content"),
        404,
        "PROJECT_NOT_FOUND",
    )


def test_corrupt_artifact_returns_store_error_without_paths(client_and_app):
    client, app, _ = client_and_app
    project = create_project(client)
    source = upload(client, project["id"], "plano.pdf", pdf_bytes()).json()
    app.state.service.artifacts.path_for(source["sha256"]).write_bytes(
        b"%PDF-1.7\ncorrupto\n"
    )

    response = client.get(
        f"{API}/projects/{project['id']}/sources/{source['id']}/content"
    )
    assert_error(response, 500, "STORE_ERROR")
    assert "artifacts" not in response.text
    assert "autosolid.db" not in response.text


def test_source_survives_app_recreation(tmp_path):
    data_dir = tmp_path / "data"
    data = pdf_bytes()

    first_store = ProjectStore(data_dir)
    first_app = create_app(first_store)
    with TestClient(first_app) as client:
        project = create_project(client)
        source = upload(client, project["id"], "plano.pdf", data).json()

    second_store = ProjectStore(data_dir)
    second_app = create_app(second_store)
    with TestClient(second_app) as client:
        listed = client.get(f"{API}/projects/{project['id']}/sources")
        assert listed.status_code == 200
        assert listed.json() == [source]
        content = client.get(
            f"{API}/projects/{project['id']}/sources/{source['id']}/content"
        )
        assert content.status_code == 200
        assert content.content == data
