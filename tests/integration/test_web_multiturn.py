from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from novaagent.bootstrap.container import build_app, build_settings


def _stream_response(_: httpx.Request) -> httpx.Response:
    chunks = [
        'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":"NOVA"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":"AGENT"}}]}\n\n',
        'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2}}\n\n',
        "data: [DONE]\n\n",
    ]
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content="".join(chunks).encode(),
    )


def test_sessions_stream_and_revision(runtime_environment: dict[str, str]) -> None:
    environment = {**runtime_environment, "DASHSCOPE_API_KEY": "test-key"}
    settings = build_settings(environ=environment)
    transport = httpx.MockTransport(_stream_response)
    with TestClient(build_app(settings, environ=environment, qwen_transport=transport)) as client:
        created = client.post("/api/v1/sessions", json={})
        assert created.status_code == 201
        session = created.json()["session"]
        session_id = session["session_id"]

        with client.stream(
            "POST",
            f"/api/v1/sessions/{session_id}/messages:stream",
            json={"message": "hello", "expected_revision": 0},
        ) as response:
            assert response.status_code == 200
            body = response.read().decode()
        assert "event: agent_event" in body
        assert '"type":"text_delta"' in body
        assert "NOVAAGENT" in body
        assert '"type":"run_completed"' in body

        detail = client.get(f"/api/v1/sessions/{session_id}").json()
        assert detail["session"]["revision"] == 1
        assert len(detail["messages"]) == 2

        with client.stream(
            "POST",
            f"/api/v1/sessions/{session_id}/messages:stream",
            json={"message": "again", "expected_revision": 1},
        ) as response:
            assert response.status_code == 200
            response.read()

        assert client.get(f"/api/v1/sessions/{session_id}").json()["session"]["revision"] == 2


def test_session_management_and_stream_validation(runtime_environment: dict[str, str]) -> None:
    environment = {**runtime_environment, "DASHSCOPE_API_KEY": "test-key"}
    settings = build_settings(environ=environment)
    with TestClient(
        build_app(
            settings,
            environ=environment,
            qwen_transport=httpx.MockTransport(_stream_response),
        )
    ) as client:
        created = client.post("/api/v1/sessions", json={})
        session_id = created.json()["session"]["session_id"]
        assert client.get("/api/v1/sessions").json()["sessions"]
        assert (
            client.post(
                f"/api/v1/sessions/{session_id}/messages:stream",
                json={"message": "hello", "expected_revision": 1},
            ).json()["error"]["code"]
            == "session_revision_conflict"
        )
        assert (
            client.post(
                f"/api/v1/sessions/{session_id}/messages:stream",
                json={"message": "   ", "expected_revision": 0},
            ).json()["error"]["code"]
            == "message_empty"
        )
        assert client.post("/api/v1/runs/unknown/cancel").json()["error"]["code"] == "run_not_found"
        cleared = client.delete(f"/api/v1/sessions/{session_id}/messages?expected_revision=0")
        assert cleared.status_code == 200
        deleted = client.delete(f"/api/v1/sessions/{session_id}?expected_revision=1")
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/sessions/{session_id}").status_code == 404
