from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from novaagent.bootstrap.container import build_app, build_settings


def qwen_success(_: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "NOVAAGENT_OK",
                        "reasoning_content": "must never appear",
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 3,
                "total_tokens": 999,
            },
        },
    )


def test_web_chat_completes_one_qwen_text_turn(runtime_environment: dict[str, str]) -> None:
    environment = {**runtime_environment, "DASHSCOPE_API_KEY": "test-key"}
    settings = build_settings(environ=environment)
    transport = httpx.MockTransport(qwen_success)

    with TestClient(build_app(settings, environ=environment, qwen_transport=transport)) as client:
        response = client.post(
            "/api/v1/chat",
            json={"message": "你好"},
            headers={"X-Request-ID": "web-chat-1"},
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "web-chat-1"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    payload = response.json()
    assert payload["protocol_version"] == "1"
    assert payload["run_id"].startswith("run-")
    assert payload["message"]["role"] == "assistant"
    assert payload["message"]["content"] == [{"type": "text", "text": "NOVAAGENT_OK"}]
    assert payload["provider"] == {"name": "qwen", "model": "qwen3.8-max"}
    assert payload["usage"] == {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}
    assert payload["latency_ms"] >= 0
    assert "reasoning" not in response.text.lower()
    assert "test-key" not in response.text


def test_diagnostics_only_exposes_qwen_key_presence(runtime_environment: dict[str, str]) -> None:
    environment = {**runtime_environment, "DASHSCOPE_API_KEY": "never-return-this"}
    settings = build_settings(environ=environment)

    with TestClient(build_app(settings, environ=environment)) as client:
        response = client.get("/api/v1/diagnostics")

    assert response.status_code == 200
    assert response.json()["providers"]["details"]["qwen"]["secret_present"] is True
    assert "never-return-this" not in response.text
    assert "DASHSCOPE_API_KEY" not in response.text


def test_missing_qwen_key_returns_stable_error_without_outbound_request(
    runtime_environment: dict[str, str],
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return qwen_success(_)

    settings = build_settings(environ=runtime_environment)
    with TestClient(
        build_app(
            settings,
            environ=runtime_environment,
            qwen_transport=httpx.MockTransport(handler),
        )
    ) as client:
        response = client.post("/api/v1/chat", json={"message": "你好"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "secret_missing"
    assert response.json()["error"]["field"] == "providers.qwen.secret"
    assert response.json()["error"]["retryable"] is False
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]
    assert calls == 0


@pytest.mark.parametrize(
    ("body", "headers", "status", "code", "field"),
    [
        (b"not-json", {"Content-Type": "application/json"}, 422, "request_invalid", None),
        (
            json.dumps({"message": "hello", "unknown": True}).encode(),
            {"Content-Type": "application/json"},
            422,
            "request_invalid",
            None,
        ),
        (
            b'{"message": 1}',
            {"Content-Type": "application/json"},
            422,
            "request_invalid",
            "message",
        ),
        (b'{"message": "hello"}', {"Content-Type": "text/plain"}, 422, "request_invalid", None),
        (
            b'{"message": "   "}',
            {"Content-Type": "application/json"},
            422,
            "message_empty",
            "message",
        ),
        (
            json.dumps({"message": "x" * 32_001}).encode(),
            {"Content-Type": "application/json"},
            422,
            "message_too_long",
            "message",
        ),
        (
            b"x" * (64 * 1024 + 1),
            {"Content-Type": "application/json"},
            413,
            "request_too_large",
            None,
        ),
    ],
)
def test_chat_request_validation_has_stable_errors(
    runtime_environment: dict[str, str],
    body: bytes,
    headers: dict[str, str],
    status: int,
    code: str,
    field: str | None,
) -> None:
    environment = {**runtime_environment, "DASHSCOPE_API_KEY": "test-key"}
    settings = build_settings(environ=environment)

    with TestClient(
        build_app(
            settings,
            environ=environment,
            qwen_transport=httpx.MockTransport(qwen_success),
        )
    ) as client:
        response = client.post("/api/v1/chat", content=body, headers=headers)

    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    assert bool(error["message"])
    assert bool(error["request_id"])
    assert error.get("field") == field


def test_token_mode_protects_chat_and_accepts_header_or_bearer_token(
    runtime_environment: dict[str, str],
) -> None:
    environment = {
        **runtime_environment,
        "DASHSCOPE_API_KEY": "test-key",
        "NOVAAGENT_WEB_HOST": "0.0.0.0",
        "NOVAAGENT_WEB_AUTH_MODE": "token",
        "NOVAAGENT_WEB_TOKEN": "web-token",
    }
    settings = build_settings(environ=environment)

    with TestClient(
        build_app(
            settings,
            environ=environment,
            qwen_transport=httpx.MockTransport(qwen_success),
        )
    ) as client:
        missing = client.post("/api/v1/chat", json={"message": "hello"})
        header = client.post(
            "/api/v1/chat",
            json={"message": "hello"},
            headers={"X-NovaAgent-Token": "web-token"},
        )
        bearer = client.post(
            "/api/v1/chat",
            json={"message": "hello"},
            headers={"Authorization": "Bearer web-token"},
        )

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "authentication_required"
    assert header.status_code == 200
    assert bearer.status_code == 200


def test_invalid_supplied_request_id_is_replaced(runtime_environment: dict[str, str]) -> None:
    settings = build_settings(environ=runtime_environment)

    with TestClient(build_app(settings, environ=runtime_environment)) as client:
        response = client.post(
            "/api/v1/chat",
            content=b"invalid",
            headers={
                "Content-Type": "application/json",
                "X-Request-ID": "contains spaces and must be replaced",
            },
        )

    request_id = response.json()["error"]["request_id"]
    assert request_id != "contains spaces and must be replaced"
    assert request_id == response.headers["X-Request-ID"]
