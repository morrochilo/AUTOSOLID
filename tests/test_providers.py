import json
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from autosolid.providers import (
    ChatMessage,
    CompletionRequest,
    ModelProvider,
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
    ProviderError,
    SimulatedProvider,
    SimulatedReply,
)


@dataclass
class FakeReply:
    status: int = 200
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    delay_seconds: float = 0.0


class _FakeOpenAIHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        server: FakeOpenAIServer = self.server  # type: ignore[assignment]
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        server.paths.append(self.path)
        server.headers_seen.append(dict(self.headers))
        try:
            server.requests.append(json.loads(raw_body))
        except json.JSONDecodeError:
            server.requests.append(None)

        reply = (
            server.replies.pop(0)
            if server.replies
            else FakeReply(body={"error": "no reply queued"})
        )
        if reply.delay_seconds:
            time.sleep(reply.delay_seconds)

        body = reply.body
        if isinstance(body, bytes):
            data = body
        elif isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = json.dumps(body).encode("utf-8")

        self.send_response(reply.status)
        for name, value in reply.headers.items():
            self.send_header(name, value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_: Any) -> None:
        return


class FakeOpenAIServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _FakeOpenAIHandler)
        self.replies: list[FakeReply] = []
        self.requests: list[Any] = []
        self.paths: list[str] = []
        self.headers_seen: list[dict[str, str]] = []


@contextmanager
def fake_openai_server():
    server = FakeOpenAIServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def base_url(server: FakeOpenAIServer, path: str = "/v1") -> str:
    host, port = server.server_address
    return f"http://{host}:{port}{path}"


def make_config(server: FakeOpenAIServer, **overrides: Any) -> OpenAICompatibleConfig:
    values = {
        "base_url": base_url(server),
        "model": "test-model",
        "api_key": "secret-key",
        "timeout_seconds": 2.0,
    }
    values.update(overrides)
    return OpenAICompatibleConfig(**values)


def make_request(**overrides: Any) -> CompletionRequest:
    values = {
        "messages": [ChatMessage(role="user", content="Genera un JSON.")],
        "temperature": 0.0,
    }
    values.update(overrides)
    return CompletionRequest(**values)


def completion_body(
    content: str,
    *,
    model: str = "model-from-server",
    request_id: str = "req_1",
    finish_reason: str = "stop",
) -> dict[str, Any]:
    return {
        "id": request_id,
        "model": model,
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }


def test_openai_compatible_sends_request_and_parses_json():
    with fake_openai_server() as server:
        server.replies.append(FakeReply(body=completion_body('{"part": "bracket"}')))
        provider = OpenAICompatibleProvider(make_config(server))

        response = provider.complete(
            make_request(
                response_format="json_object",
                temperature=0.2,
                max_tokens=128,
            )
        )

        assert response.provider == "openai_compatible"
        assert response.model == "model-from-server"
        assert response.parsed_json == {"part": "bracket"}
        assert response.content == '{"part": "bracket"}'
        assert response.usage.total_tokens == 15
        assert response.request_id == "req_1"
        assert response.finish_reason == "stop"
        assert response.latency_ms >= 0
        assert server.paths == ["/v1/chat/completions"]

        sent = server.requests[0]
        assert sent["model"] == "test-model"
        assert sent["messages"] == [
            {"role": "user", "content": "Genera un JSON."}
        ]
        assert sent["temperature"] == 0.2
        assert sent["max_tokens"] == 128
        assert sent["response_format"] == {"type": "json_object"}
        assert sent["stream"] is False
        assert "api_key" not in sent

        headers = server.headers_seen[0]
        assert headers["Authorization"] == "Bearer secret-key"
        assert headers["Content-Type"] == "application/json"
        assert headers["User-Agent"].startswith("autosolid/")


def test_custom_endpoint_path_and_organization_header():
    with fake_openai_server() as server:
        server.replies.append(FakeReply(body=completion_body("ok")))
        provider = OpenAICompatibleProvider(
            make_config(
                server,
                endpoint_path="/custom/chat",
                organization="org-1",
            )
        )

        response = provider.complete(make_request())

        assert response.content == "ok"
        assert server.paths == ["/v1/custom/chat"]
        headers = {
            name.lower(): value
            for name, value in server.headers_seen[0].items()
        }
        assert headers["openai-organization"] == "org-1"


def test_openai_compatible_text_response_does_not_parse_json():
    with fake_openai_server() as server:
        server.replies.append(FakeReply(body=completion_body("texto libre")))
        provider = OpenAICompatibleProvider(make_config(server))

        response = provider.complete(make_request())

        assert response.content == "texto libre"
        assert response.parsed_json is None
        assert "response_format" not in server.requests[0]


def test_openai_compatible_can_use_request_model_and_no_auth():
    with fake_openai_server() as server:
        server.replies.append(FakeReply(body=completion_body("ok")))
        provider = OpenAICompatibleProvider(
            make_config(server, api_key=None)
        )

        provider.complete(make_request(model="other-model"))

        assert server.requests[0]["model"] == "other-model"
        assert "Authorization" not in server.headers_seen[0]
        assert provider.model == "test-model"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "PROVIDER_AUTH_FAILED"),
        (403, "PROVIDER_AUTH_FAILED"),
        (429, "PROVIDER_RATE_LIMITED"),
        (500, "PROVIDER_UNAVAILABLE"),
        (503, "PROVIDER_UNAVAILABLE"),
        (400, "PROVIDER_HTTP_ERROR"),
    ],
)
def test_http_errors_map_to_stable_codes_without_body_leaks(status, code):
    with fake_openai_server() as server:
        server.replies.append(
            FakeReply(
                status=status,
                body={"error": "secret-key and internal details"},
            )
        )
        provider = OpenAICompatibleProvider(make_config(server))

        with pytest.raises(ProviderError) as error_info:
            provider.complete(make_request())

        error = error_info.value
        assert error.code == code
        assert error.details == {"status": status}
        encoded = f"{error} {error.to_dict()} {error.details}"
        assert "secret-key" not in encoded
        assert "internal details" not in encoded


def test_redirects_are_not_followed():
    with fake_openai_server() as server:
        server.replies.append(
            FakeReply(
                status=302,
                headers={"Location": "http://127.0.0.1:1/elsewhere"},
                body={},
            )
        )
        provider = OpenAICompatibleProvider(make_config(server))

        with pytest.raises(ProviderError) as error_info:
            provider.complete(make_request())

        assert error_info.value.code == "PROVIDER_REDIRECT_BLOCKED"
        assert len(server.paths) == 1


def test_timeout_is_reported_and_does_not_echo_secret():
    with fake_openai_server() as server:
        server.replies.append(
            FakeReply(body=completion_body("late"), delay_seconds=1.0)
        )
        provider = OpenAICompatibleProvider(
            make_config(server, timeout_seconds=0.05)
        )

        with pytest.raises(ProviderError) as error_info:
            provider.complete(make_request())

        error = error_info.value
        assert error.code == "PROVIDER_TIMEOUT"
        assert "secret-key" not in str(error)


def test_request_timeout_overrides_config():
    with fake_openai_server() as server:
        server.replies.append(
            FakeReply(body=completion_body("late"), delay_seconds=1.0)
        )
        provider = OpenAICompatibleProvider(
            make_config(server, timeout_seconds=5.0)
        )

        with pytest.raises(ProviderError) as error_info:
            provider.complete(make_request(timeout_seconds=0.05))

        assert error_info.value.code == "PROVIDER_TIMEOUT"
        assert error_info.value.details == {"timeout_seconds": 0.05}


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("no es json", "invalid_json"),
        ("", "empty_content"),
        ("[1, 2]", "json_not_object"),
        ('{"unterminated": ', "invalid_json"),
        ('{"value": NaN}', "non_finite_number"),
        ('{"value": -Infinity}', "non_finite_number"),
    ],
)
def test_invalid_model_json_is_rejected_without_repair(content, reason):
    with fake_openai_server() as server:
        server.replies.append(FakeReply(body=completion_body(content)))
        provider = OpenAICompatibleProvider(make_config(server))

        with pytest.raises(ProviderError) as error_info:
            provider.complete(make_request(response_format="json_object"))

        error = error_info.value
        assert error.code == "MODEL_OUTPUT_INVALID"
        assert error.details["reason"] == reason
        assert "secret-key" not in str(error)


def test_invalid_utf8_response_is_rejected():
    with fake_openai_server() as server:
        server.replies.append(FakeReply(body=b'{"choices": "\xff"}'))
        provider = OpenAICompatibleProvider(make_config(server))

        with pytest.raises(ProviderError) as error_info:
            provider.complete(make_request())

        assert error_info.value.code == "PROVIDER_RESPONSE_INVALID"
        assert error_info.value.details["reason"] == "invalid_utf8"


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        "",
        [],
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": 1}}]},
    ],
)
def test_invalid_provider_body_is_rejected(body):
    with fake_openai_server() as server:
        server.replies.append(FakeReply(body=body))
        provider = OpenAICompatibleProvider(make_config(server))

        with pytest.raises(ProviderError) as error_info:
            provider.complete(make_request())

        assert error_info.value.code == "PROVIDER_RESPONSE_INVALID"


def test_response_size_limit_is_enforced_before_parsing():
    with fake_openai_server() as server:
        server.replies.append(
            FakeReply(body=completion_body('{"padding": "' + "x" * 2000 + '"}'))
        )
        provider = OpenAICompatibleProvider(
            make_config(server, max_response_bytes=256)
        )

        with pytest.raises(ProviderError) as error_info:
            provider.complete(make_request(response_format="json_object"))

        assert error_info.value.code == "PROVIDER_RESPONSE_TOO_LARGE"


def test_config_rejects_insecure_remote_http_and_credentials():
    with pytest.raises(ProviderError) as remote_http:
        OpenAICompatibleConfig(
            base_url="http://example.com/v1",
            model="test-model",
        )
    assert remote_http.value.code == "PROVIDER_CONFIG_INVALID"

    assert OpenAICompatibleConfig(
        base_url="http://example.com/v1",
        model="test-model",
        allow_insecure_http=True,
    ).allow_insecure_http is True

    for base_url in (
        "ftp://example.com/v1",
        "http://user:password@127.0.0.1/v1",
        "http://127.0.0.1/v1?token=secret",
        "http://127.0.0.1/v1#fragment",
        "https://example.com:notaport/v1",
        "https://example.com:99999/v1",
    ):
        with pytest.raises(ProviderError):
            OpenAICompatibleConfig(base_url=base_url, model="test-model")


def test_config_rejects_header_injection_and_bad_values():
    with pytest.raises(ProviderError):
        OpenAICompatibleConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="key\nInjected: yes",
        )
    with pytest.raises(ProviderError):
        OpenAICompatibleConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            organization="org\rInjected: yes",
        )
    with pytest.raises(ProviderError):
        OpenAICompatibleConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="clave-\U0001f600",
        )
    with pytest.raises(ProviderError):
        OpenAICompatibleConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            organization="organización-\U0001f600",
        )
    with pytest.raises(ProviderError):
        OpenAICompatibleConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            timeout_seconds=float("nan"),
        )
    with pytest.raises(ProviderError):
        OpenAICompatibleConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            endpoint_path="//evil.example/path",
        )
    with pytest.raises(ProviderError):
        OpenAICompatibleConfig(
            base_url="http://127.0.0.1:8000/v1/ñ",
            model="test-model",
        )
    with pytest.raises(ProviderError):
        OpenAICompatibleConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            endpoint_path="/chat/ñ",
        )


def test_config_redacts_api_key():
    config = OpenAICompatibleConfig(
        base_url="http://127.0.0.1:8000/v1",
        model="test-model",
        api_key="super-secret-key",
        organization="private-org",
    )
    public = config.to_public_dict()
    assert "super-secret-key" not in repr(config)
    assert "private-org" not in repr(config)
    assert "super-secret-key" not in json.dumps(public)
    assert "private-org" not in json.dumps(public)
    assert public["has_api_key"] is True
    assert public["has_organization"] is True
    assert config.endpoint_url == "http://127.0.0.1:8000/v1/chat/completions"


def test_config_from_environment(monkeypatch):
    monkeypatch.setenv("AUTOSOLID_OPENAI_BASE_URL", "https://models.example/v1")
    monkeypatch.setenv("AUTOSOLID_OPENAI_MODEL", "planner-model")
    monkeypatch.setenv("AUTOSOLID_OPENAI_API_KEY", "env-secret")
    monkeypatch.setenv("AUTOSOLID_OPENAI_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("AUTOSOLID_OPENAI_MAX_RESPONSE_BYTES", "2048")
    monkeypatch.setenv("AUTOSOLID_OPENAI_ALLOW_INSECURE_HTTP", "false")
    monkeypatch.setenv("AUTOSOLID_OPENAI_USE_SYSTEM_PROXY", "true")

    config = OpenAICompatibleConfig.from_env()

    assert config.base_url == "https://models.example/v1"
    assert config.model == "planner-model"
    assert config.api_key == "env-secret"
    assert config.timeout_seconds == 12.5
    assert config.max_response_bytes == 2048
    assert config.use_system_proxy is True
    assert "env-secret" not in repr(config)


def test_config_from_environment_reports_missing_names_without_values(monkeypatch):
    monkeypatch.delenv("AUTOSOLID_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AUTOSOLID_OPENAI_MODEL", raising=False)

    with pytest.raises(ProviderError) as error_info:
        OpenAICompatibleConfig.from_env()

    error = error_info.value
    assert error.code == "PROVIDER_CONFIG_INVALID"
    assert error.details["missing"] == [
        "AUTOSOLID_OPENAI_BASE_URL",
        "AUTOSOLID_OPENAI_MODEL",
    ]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AUTOSOLID_OPENAI_TIMEOUT_SECONDS", "not-a-number"),
        ("AUTOSOLID_OPENAI_MAX_RESPONSE_BYTES", "1.5"),
        ("AUTOSOLID_OPENAI_ALLOW_INSECURE_HTTP", "maybe"),
        ("AUTOSOLID_OPENAI_USE_SYSTEM_PROXY", "maybe"),
    ],
)
def test_config_from_environment_rejects_bad_values(
    monkeypatch, name, value
):
    monkeypatch.setenv("AUTOSOLID_OPENAI_BASE_URL", "https://models.example/v1")
    monkeypatch.setenv("AUTOSOLID_OPENAI_MODEL", "planner-model")
    monkeypatch.setenv(name, value)

    with pytest.raises(ProviderError) as error_info:
        OpenAICompatibleConfig.from_env()

    assert error_info.value.code == "PROVIDER_CONFIG_INVALID"
    assert error_info.value.details["variable"] == name
    assert value not in str(error_info.value)


def test_simulated_provider_queue_and_request_log():
    provider = SimulatedProvider(
        [
            {"ok": True},
            "texto",
            SimulatedReply(parsed_json={"second": 2}),
        ],
        name="sim",
        model="sim-model",
    )
    assert provider.pending == 3

    first = provider.complete(make_request(response_format="json_object"))
    assert first.parsed_json == {"ok": True}
    assert first.provider == "sim"
    assert first.model == "sim-model"
    assert first.latency_ms == 0.0

    second = provider.complete(make_request())
    assert second.content == "texto"
    assert second.parsed_json is None

    third = provider.complete(make_request(response_format="json_object"))
    assert third.parsed_json == {"second": 2}
    assert len(provider.requests) == 3
    assert provider.pending == 0

    with pytest.raises(ProviderError) as error_info:
        provider.complete(make_request())
    assert error_info.value.code == "SIMULATED_PROVIDER_EXHAUSTED"


def test_simulated_provider_injects_errors_and_invalid_json():
    provider = SimulatedProvider(
        [
            ProviderError("PROVIDER_TIMEOUT", "timeout simulado"),
            "no es json",
            "[1, 2]",
        ]
    )

    with pytest.raises(ProviderError) as timeout:
        provider.complete(make_request())
    assert timeout.value.code == "PROVIDER_TIMEOUT"

    with pytest.raises(ProviderError) as invalid:
        provider.complete(make_request(response_format="json_object"))
    assert invalid.value.code == "MODEL_OUTPUT_INVALID"
    assert invalid.value.details["reason"] == "invalid_json"

    with pytest.raises(ProviderError) as not_object:
        provider.complete(make_request(response_format="json_object"))
    assert not_object.value.details["reason"] == "json_not_object"


def test_provider_protocol_is_structural():
    provider = SimulatedProvider()
    assert isinstance(provider, ModelProvider)
    with fake_openai_server() as server:
        assert isinstance(
            OpenAICompatibleProvider(make_config(server)),
            ModelProvider,
        )
