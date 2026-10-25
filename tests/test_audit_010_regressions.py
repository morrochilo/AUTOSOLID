import json
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

import pytest

from autosolid.providers import (
    ChatMessage,
    CompletionRequest,
    OpenAICompatibleConfig,
    ProviderError,
    SimulatedProvider,
    SimulatedReply,
)
from autosolid.providers.json_output import parse_json_object


def json_request():
    return CompletionRequest(
        messages=[ChatMessage(role="user", content="JSON")],
        response_format="json_object",
    )


def test_audit_long_integer_is_a_provider_error():
    with pytest.raises(ProviderError):
        parse_json_object('{"x":' + "1" * 5000 + "}")


def test_audit_excessive_nesting_is_a_provider_error():
    content = '{"x":' + "[" * 3000 + "0" + "]" * 3000 + "}"
    with pytest.raises(ProviderError):
        parse_json_object(content)


def test_audit_simulator_rejects_non_finite_mapping():
    with pytest.raises(ProviderError):
        SimulatedProvider([{"value": float("nan")}]).complete(json_request())


def test_audit_simulator_rejects_contradictory_json_reply():
    reply = SimulatedReply(content="not json", parsed_json={"ok": True})
    with pytest.raises(ProviderError):
        SimulatedProvider([reply]).complete(json_request())


def test_audit_request_messages_cannot_be_mutated():
    request = json_request()
    with pytest.raises((TypeError, AttributeError)):
        request.messages.append(ChatMessage(role="user", content="cambio"))


def test_audit_simulated_history_cannot_change_retroactively():
    request = json_request()
    provider = SimulatedProvider(["{}"])
    provider.complete(request)
    with pytest.raises((TypeError, AttributeError)):
        provider.requests[0].messages.append(
            ChatMessage(role="user", content="cambio")
        )


def test_audit_response_json_cannot_be_mutated():
    response = SimulatedProvider([{"ok": True}]).complete(json_request())
    with pytest.raises((TypeError, AttributeError)):
        response.parsed_json["ok"] = False


@pytest.mark.parametrize("suffix", ["?", "#"])
def test_audit_base_url_rejects_empty_delimiters(suffix):
    with pytest.raises(ProviderError):
        OpenAICompatibleConfig(
            base_url=f"http://127.0.0.1:8000/v1{suffix}",
            model="model",
        )


def test_audit_timeout_is_normalized_for_json():
    config = OpenAICompatibleConfig(
        base_url="http://127.0.0.1:8000",
        model="model",
        timeout_seconds=Fraction(1, 3),
    )
    json.dumps(config.to_public_dict())
    assert isinstance(config.to_public_dict()["timeout_seconds"], float)


@pytest.mark.parametrize(
    "body",
    [
        b'{"choices": [], "usage": {"prompt_tokens": NaN}}',
        b'{"choices": [], "value":' + b"1" * 5000 + b"}",
        b'{"x":' + b"[" * 3000 + b"0" + b"]" * 3000 + b"}",
    ],
)
def test_audit_envelope_rejects_non_standard_or_pathological_json(body):
    from autosolid.providers.openai_compatible import _decode_response_body

    with pytest.raises(ProviderError) as error:
        _decode_response_body(body)
    assert error.value.code == "PROVIDER_RESPONSE_INVALID"


def test_audit_simulator_is_safe_for_concurrent_calls():
    provider = SimulatedProvider([f"reply-{index}" for index in range(50)])
    requests = [
        CompletionRequest(
            messages=[ChatMessage(role="user", content=str(index))]
        )
        for index in range(50)
    ]
    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(executor.map(provider.complete, requests))

    assert {response.request_id for response in responses} == {
        f"sim_{index}" for index in range(1, 51)
    }
    assert {response.content for response in responses} == {
        f"reply-{index}" for index in range(50)
    }
    assert len(provider.requests) == 50
