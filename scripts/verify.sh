#!/usr/bin/env bash
set -euo pipefail

uv sync --all-groups
uv run pytest --cov=novaagent --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run novaagent doctor --environment test
