# NovaAgent

NovaAgent is a personal AI agent being built from a clean Python project. The first product scope is intentionally narrow:

- The Web console is the only user chat entry point.
- Qwen is the only supported model provider.
- The CLI is for diagnostics and service management, not chat.
- Model input and output remain text-only; multimodal model tasks are out of scope.

## Requirements

- Python `3.12` or `3.13`
- [`uv`](https://docs.astral.sh/uv/)

## Install

```text
uv sync --all-groups
```

## Verify

```text
uv run novaagent --version
uv run novaagent doctor --environment test
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
```

## Run the Web console

```text
uv run novaagent serve --environment local
```

The service binds to `127.0.0.1:8765` by default. Open that address in a browser for the
streaming Qwen Agent console, or check the service with:

```text
curl http://127.0.0.1:8765/health/live
curl http://127.0.0.1:8765/health/ready
```

The current Web console supports text-only streaming and multiple in-memory sessions. Each session
can contain successful user/assistant turns, while cancellation and provider failures leave the
incomplete turn out of history. The stage 05 Agent loop can call registered tools and exposes only
tool name/status events to the Web page. The diagnostic `echo` tool is registered only in `local`
and `test`; production currently registers no tools. Tool traces remain run-local and are not added
to formal session history. Sessions are cleared when the service process restarts; real local tools,
persistence, and Markdown rendering are not implemented yet. Image, audio, and video model input
and related multimodal tasks are intentionally out of scope. The original non-streaming
`POST /api/v1/chat` endpoint remains available for compatibility.

## Configuration

The default configuration file is `~/.novaagent/config.toml`. `NOVAAGENT_CONFIG_FILE` can point to another TOML file. Provider secrets are supplied through a local, ignored `.env` file or another out-of-band environment source:

- `DASHSCOPE_API_KEY` for Qwen
- `NOVAAGENT_WEB_TOKEN` when Web token authentication is enabled

Secrets are never written to the project configuration, logs, diagnostics, or test output.

Stage 03 uses Qwen model `qwen3.8-max` by default and calls the fixed official DashScope
OpenAI-compatible endpoint. For local development, copy `.env.example` to `.env` and fill in the
key locally; `.env` is ignored by Git. The server loads that file at startup, while an explicitly
provided process environment variable takes precedence. You can use `--env-file /path/to/.env` for
another ignored file. The Web console only displays whether the key is configured; it never accepts,
reads, modifies, or persists Provider API keys.

The product scope no longer includes Doubao. Runtime configuration, diagnostics, CLI output and
tests are Qwen-only. An obsolete Doubao key left in an older local `.env` is ignored and never
enters the runtime environment or diagnostics.

Agent safety limits can be configured in TOML and are never controlled by the Web request:

```toml
[agent]
max_steps = 8
max_tool_calls = 16
max_tool_calls_per_step = 8
total_timeout_seconds = 180
model_step_timeout_seconds = 75
tool_timeout_seconds = 10
```
