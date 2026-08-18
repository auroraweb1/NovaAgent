from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient

from novaagent.bootstrap.container import build_app, build_settings


def test_web_agent_executes_echo_and_keeps_tool_trace_out_of_history(
    runtime_environment: dict[str, str],
) -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            chunks = [
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-echo-1",
                                        "type": "function",
                                        "function": {
                                            "name": "echo",
                                            "arguments": '{"text":"web-ok"}',
                                        },
                                    }
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
                {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 1}},
            ]
        else:
            chunks = [
                {"choices": [{"delta": {"content": "echo complete"}}]},
                {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2}},
            ]
        body = "".join([*(f"data: {json.dumps(item)}\n\n" for item in chunks), "data: [DONE]\n\n"])
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body.encode(),
        )

    environment = {**runtime_environment, "DASHSCOPE_API_KEY": "test-key"}
    settings = build_settings(environ=environment)
    with TestClient(
        build_app(
            settings,
            environ=environment,
            qwen_transport=httpx.MockTransport(handler),
        )
    ) as client:
        session = client.post("/api/v1/sessions").json()["session"]
        session_id = session["session_id"]
        response = client.post(
            f"/api/v1/sessions/{session_id}/messages:stream",
            json={"message": "use echo", "expected_revision": 0},
        )
        detail = client.get(f"/api/v1/sessions/{session_id}").json()

    assert response.status_code == 200
    assert '"type":"tool_call"' in response.text
    assert '"type":"tool_result"' in response.text
    assert '"type":"run_completed"' in response.text
    assert "echo complete" in response.text
    assert len(requests) == 2
    assert requests[0]["tool_choice"] == "auto"
    assert requests[0]["tools"][0]["function"]["name"] == "echo"  # type: ignore[index]
    second_messages = requests[1]["messages"]
    assert second_messages[-2]["role"] == "assistant"  # type: ignore[index]
    assert second_messages[-1] == {  # type: ignore[index]
        "role": "tool",
        "tool_call_id": "call-echo-1",
        "content": "web-ok",
    }
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
