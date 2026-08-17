from fastapi.testclient import TestClient

from novaagent.bootstrap.container import build_app, build_settings


def test_health_and_diagnostics_endpoints(runtime_environment: dict[str, str]) -> None:
    settings = build_settings(environ=runtime_environment)
    client = TestClient(build_app(settings, environ=runtime_environment))

    live = client.get("/health/live")
    ready = client.get("/health/ready")
    diagnostics = client.get("/api/v1/diagnostics")

    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert diagnostics.status_code == 200
    assert diagnostics.json()["providers"]["enabled"] == ["qwen", "doubao"]
    assert "DASHSCOPE_API_KEY" not in diagnostics.text


def test_token_authentication_protects_diagnostics(runtime_environment: dict[str, str]) -> None:
    environment = {
        **runtime_environment,
        "NOVAAGENT_WEB_HOST": "0.0.0.0",
        "NOVAAGENT_WEB_AUTH_MODE": "token",
        "NOVAAGENT_WEB_TOKEN": "test-token",
    }
    settings = build_settings(environ=environment)
    client = TestClient(build_app(settings, environ=environment))

    assert client.get("/health/live").status_code == 200
    assert client.get("/api/v1/diagnostics").status_code == 401
    assert (
        client.get("/api/v1/diagnostics", headers={"X-NovaAgent-Token": "test-token"}).status_code
        == 200
    )


def test_root_is_a_stage_placeholder(runtime_environment: dict[str, str]) -> None:
    settings = build_settings(environ=runtime_environment)
    client = TestClient(build_app(settings, environ=runtime_environment))

    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["chat"] == "not_implemented"
