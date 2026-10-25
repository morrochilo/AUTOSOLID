import re

import pytest
from fastapi.testclient import TestClient

from autosolid.api import create_app
from autosolid.projects import ProjectStore

API = "/api/v1"


@pytest.fixture
def client(tmp_path):
    store = ProjectStore(tmp_path / "data")
    app = create_app(store)
    with TestClient(app) as test_client:
        yield test_client


def test_index_is_served_with_security_headers(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "access-control-allow-origin" not in response.headers

    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp

    html = response.text
    assert "AUTOSOLID" in html
    for element_id in (
        "project-list",
        "create-project-form",
        "spec-editor",
        "diagnostics",
        "questions",
        "spec-viewer",
        "save-spec",
        "validate-spec",
        "source-form",
        "source-file",
        "upload-source",
        "sources",
        "source-count",
        "approval-form",
        "approval-state",
        "approval-target",
        "approver",
        "approval-note",
        "approval-confirm",
        "approve-revision",
        "approvals",
        "approval-count",
    ):
        assert f'id="{element_id}"' in html
    assert 'src="/ui/app.js"' in html
    assert 'href="/ui/app.css"' in html
    assert "http://" not in html
    assert "https://" not in html

    inline_scripts = re.findall(
        r"<script(?![^>]*\bsrc=)[^>]*>", html, flags=re.IGNORECASE
    )
    assert inline_scripts == []


def test_local_assets_are_served_without_external_resources(client):
    script = client.get("/ui/app.js")
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert script.headers["cache-control"] == "no-cache"
    assert "Content-Security-Policy" in script.headers
    assert "fetch(" in script.text
    assert "textContent" in script.text
    assert "innerHTML" not in script.text
    assert "http://" not in script.text
    assert "https://" not in script.text
    assert "eval(" not in script.text
    assert "/sources" in script.text
    assert "SOURCE_LIMIT_BYTES" in script.text
    assert "/approvals" in script.text
    assert "canApproveRevision" in script.text
    assert "APPROVAL_BLOCKED" in script.text

    styles = client.get("/ui/app.css")
    assert styles.status_code == 200
    assert styles.headers["content-type"].startswith("text/css")
    assert "Content-Security-Policy" in styles.headers
    assert "prefers-color-scheme" in styles.text
    assert "http://" not in styles.text
    assert "https://" not in styles.text
    assert "@import" not in styles.text
    assert ".source-item" in styles.text
    assert ".approval-panel" in styles.text
    assert ".state-badge" in styles.text


def test_ui_routes_are_not_part_of_the_api_schema(client):
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    assert "/" not in paths
    assert "/ui/app.js" not in paths
    assert "/ui/app.css" not in paths
    assert "/api/v1/health" in paths


def test_ui_and_api_share_the_same_store(client):
    project = client.post(f"{API}/projects", json={"name": "Bancada"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    listed = client.get(f"{API}/projects")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [project_id]

    index = client.get("/")
    assert index.status_code == 200
    assert project_id not in index.text


def test_ui_unknown_asset_uses_stable_not_found_error(client):
    response = client.get("/ui/does-not-exist.js")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert "Traceback" not in response.text
