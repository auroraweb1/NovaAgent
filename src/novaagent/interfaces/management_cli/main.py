from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import uvicorn

from novaagent import __version__
from novaagent.bootstrap.container import build_app, build_settings
from novaagent.config.loader import runtime_paths
from novaagent.config.secrets import load_runtime_environment
from novaagent.domain.errors import NovaAgentError
from novaagent.domain.providers import PROVIDER_SECRET_ENV


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        exit_code = _dispatch(args)
    except NovaAgentError as error:
        print(f"error [{error.code}]: {error.message}", file=sys.stderr)
        exit_code = 1
    except KeyboardInterrupt:
        exit_code = 130
    raise SystemExit(exit_code)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="novaagent")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")

    for name in ("doctor", "serve"):
        command = subparsers.add_parser(name)
        command.add_argument("--environment", choices=("local", "test", "production"))
        command.add_argument("--config-file", type=Path)
        command.add_argument("--env-file", type=Path)
    status = subparsers.add_parser("status")
    status.add_argument("--url", default="http://127.0.0.1:8765/health/ready")
    return parser


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "doctor":
        return _doctor(args)
    if args.command == "serve":
        return _serve(args)
    if args.command == "status":
        return _status(args.url)
    _build_parser().print_help()
    return 0


def _doctor(args: argparse.Namespace) -> int:
    env_file = getattr(args, "env_file", None)
    settings = build_settings(
        config_file=args.config_file,
        environment=args.environment,
        env_file=env_file,
    )
    paths = runtime_paths(settings)
    paths.ensure_directories()
    environment = load_runtime_environment(env_file=env_file)
    provider_details = {
        name: {
            "enabled": name in settings.providers.enabled,
            "secret_present": bool(environment.get(PROVIDER_SECRET_ENV[name])),
        }
        for name in ("qwen", "doubao")
    }
    payload = {
        "status": "ok",
        "environment": settings.app.environment,
        "web": {"host": settings.web.host, "port": settings.web.port},
        "providers": provider_details,
        "paths": {name: str(path) for name, path in paths.as_mapping().items()},
        "warnings": [
            f"{PROVIDER_SECRET_ENV[name]} is not set"
            for name, details in provider_details.items()
            if details["enabled"] and not details["secret_present"]
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _serve(args: argparse.Namespace) -> int:
    env_file = getattr(args, "env_file", None)
    settings = build_settings(
        config_file=args.config_file,
        environment=args.environment,
        env_file=env_file,
    )
    app = build_app(settings, env_file=env_file)
    uvicorn.run(app, host=settings.web.host, port=settings.web.port, log_config=None)
    return 0


def _status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            print(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError) as error:
        print(f"error [web_bind_failed]: unable to connect to {url}: {error}", file=sys.stderr)
        return 3
    return 0
