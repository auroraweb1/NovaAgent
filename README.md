# NovaAgent

NovaAgent is a personal AI agent being built from a clean Python project. The first product scope is intentionally narrow:

- The Web console is the only user chat entry point.
- Qwen and Doubao are the only allowed model providers.
- The CLI is for diagnostics and service management, not chat.

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

## Run the foundation service

```text
uv run novaagent serve --environment test
```

The service binds to `127.0.0.1:8765` by default. Check it with:

```text
curl http://127.0.0.1:8765/health/live
curl http://127.0.0.1:8765/health/ready
```

Stage 01 intentionally exposes health and diagnostic endpoints only. Chat, sessions, tools, and real provider calls are added in later stages.

## Configuration

The default configuration file is `~/.novaagent/config.toml`. `NOVAAGENT_CONFIG_FILE` can point to another TOML file. Provider secrets are supplied out of band:

- `DASHSCOPE_API_KEY` for Qwen
- `DOUBAO_API_KEY` for Doubao
- `NOVAAGENT_WEB_TOKEN` when Web token authentication is enabled

Secrets are never written to the project configuration, logs, diagnostics, or test output.

