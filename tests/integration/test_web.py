from fastapi.testclient import TestClient

from novaagent.bootstrap.container import build_app, build_settings


def test_health_and_diagnostics_endpoints(runtime_environment: dict[str, str]) -> None:
    settings = build_settings(environ=runtime_environment)
    with TestClient(build_app(settings, environ=runtime_environment)) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")
        diagnostics = client.get("/api/v1/diagnostics")

    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert diagnostics.status_code == 200
    assert diagnostics.json()["providers"]["enabled"] == ["qwen"]
    assert diagnostics.json()["providers"]["details"]["qwen"]["secret_present"] is False
    assert "DASHSCOPE_API_KEY" not in diagnostics.text


def test_token_authentication_protects_diagnostics(runtime_environment: dict[str, str]) -> None:
    environment = {
        **runtime_environment,
        "NOVAAGENT_WEB_HOST": "0.0.0.0",
        "NOVAAGENT_WEB_AUTH_MODE": "token",
        "NOVAAGENT_WEB_TOKEN": "test-token",
    }
    settings = build_settings(environ=environment)
    with TestClient(build_app(settings, environ=environment)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/").status_code == 200
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/api/v1/diagnostics").status_code == 401
        assert (
            client.get(
                "/api/v1/diagnostics", headers={"X-NovaAgent-Token": "test-token"}
            ).status_code
            == 200
        )


def test_root_serves_the_stage_05_web_console(runtime_environment: dict[str, str]) -> None:
    settings = build_settings(environ=runtime_environment)
    with TestClient(build_app(settings, environ=runtime_environment)) as client:
        response = client.get("/")
        script = client.get("/assets/app.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "千问多轮对话" in response.text
    assert "STAGE 05" in response.text
    assert "Provider API Key" not in response.text
    assert "Content-Security-Policy" in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "innerHTML" not in script.text
    assert "localStorage" not in script.text
    assert "sessionStorage" not in script.text
