from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fakes.protocol import InMemoryEventSink, InMemorySessionStore, ScriptedModel
from novaagent.domain.errors import ProtocolValidationError, ToolCallError
from novaagent.domain.messages import Message, MessageRole, TextBlock
from novaagent.domain.ports import (
    EventSinkPort,
    ModelOptions,
    ModelPort,
    ModelRequest,
    ReasoningSummaryModelDelta,
    SessionStorePort,
    TextModelDelta,
    ToolDefinition,
    ToolExecutionContext,
)

NOW = datetime(2026, 8, 17, 2, 0, tzinfo=UTC)


def message(message_id: str) -> Message:
    return Message(message_id, MessageRole.USER, (TextBlock("hello"),), NOW)


def test_model_request_and_options_invariants() -> None:
    request = ModelRequest((message("msg-1"),), options=ModelOptions(0.5, 100))
    assert request.messages[0].message_id == "msg-1"
    with pytest.raises(ProtocolValidationError, match="at least one"):
        ModelRequest(())
    with pytest.raises(ProtocolValidationError, match="temperature"):
        ModelOptions(temperature=3)
    with pytest.raises(ProtocolValidationError, match="positive"):
        ModelOptions(max_output_tokens=0)


def test_tool_contract_values_are_validated_and_frozen() -> None:
    definition = ToolDefinition("lookup", "Look up a value", {"type": "object", "properties": {}})
    context = ToolExecutionContext("run-1", "session-1", {"source": "test"})
    assert definition.parameters["type"] == "object"
    assert context.metadata["source"] == "test"
    with pytest.raises(ToolCallError, match="name"):
        ToolDefinition(" ", "description", {})
    with pytest.raises(ToolCallError, match="description"):
        ToolDefinition("lookup", " ", {})
    with pytest.raises(ProtocolValidationError, match="text delta"):
        TextModelDelta("")
    with pytest.raises(ProtocolValidationError, match="summary delta"):
        ReasoningSummaryModelDelta("")


def test_in_memory_session_store_preserves_order_and_batch_atomic_shape() -> None:
    async def scenario() -> None:
        store = InMemorySessionStore()
        first = message("msg-1")
        second = message("msg-2")
        await store.append_messages("session-1", [first, second])
        assert await store.get_messages("session-1") == (first, second)
        assert await store.get_messages("session-2") == ()

    asyncio.run(scenario())


def test_fakes_satisfy_async_behavior_without_network() -> None:
    async def scenario() -> None:
        model = ScriptedModel((TextModelDelta("hello"),))
        request = ModelRequest((message("msg-1"),))
        outputs = [output async for output in model.stream(request)]
        assert outputs == [TextModelDelta("hello")]
        assert model.requests == [request]
        sink = InMemoryEventSink()
        assert sink.events == ()

    asyncio.run(scenario())


def test_fakes_statically_match_the_core_ports() -> None:
    model: ModelPort = ScriptedModel((TextModelDelta("hello"),))
    sink: EventSinkPort = InMemoryEventSink()
    store: SessionStorePort = InMemorySessionStore()

    assert model is not None
    assert sink is not None
    assert store is not None


def test_domain_has_no_framework_or_provider_sdk_imports() -> None:
    project_root = Path(__file__).resolve().parents[2]
    domain_root = project_root / "src" / "novaagent" / "domain"
    forbidden = {"fastapi", "pydantic", "httpx", "httpx2", "dashscope", "volcenginesdk"}

    for path in domain_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        assert not imports & forbidden, f"{path.name} imports {imports & forbidden}"
