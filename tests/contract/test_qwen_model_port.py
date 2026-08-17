from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import httpx

from novaagent.config.model import QwenProviderSettings
from novaagent.domain.ports import ModelPort
from novaagent.infrastructure.models.qwen import QwenModelAdapter


def accepts_model_port(_: ModelPort) -> None:
    return None


def test_qwen_adapter_satisfies_model_port_and_declares_stage_03_capabilities() -> None:
    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
        adapter = QwenModelAdapter(
            client=client,
            settings=QwenProviderSettings(),
            secret_provider=lambda: None,
        )
        try:
            accepts_model_port(adapter)
            assert adapter.capabilities.provider == "qwen"
            assert adapter.capabilities.model == "qwen3.8-max"
            assert adapter.capabilities.text_input is True
            assert adapter.capabilities.text_output is True
            assert adapter.capabilities.usage is True
            assert adapter.capabilities.native_streaming is False
            assert adapter.capabilities.tool_calling is False
            assert adapter.capabilities.reasoning_summary is False
            assert adapter.capabilities.image_input is False
            assert adapter.capabilities.audio_input is False
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_domain_and_application_do_not_import_web_or_provider_libraries() -> None:
    source_root = Path(__file__).parents[2] / "src" / "novaagent"
    forbidden = {"fastapi", "httpx", "dashscope"}
    violations: list[str] = []

    for layer in ("domain", "application"):
        for path in (source_root / layer).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                imported: list[str] = []
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported = [node.module]
                for name in imported:
                    if name.split(".", 1)[0] in forbidden:
                        violations.append(f"{path.relative_to(source_root)} imports {name}")

    assert violations == []
