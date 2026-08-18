from __future__ import annotations

import asyncio

import pytest

from novaagent.application.agent import EchoTool, ToolRegistry
from novaagent.domain.errors import (
    ToolArgumentsInvalidError,
    ToolExecutionFailedError,
    ToolNotFoundError,
    ToolResultInvalidError,
    ToolTimeoutError,
)
from novaagent.domain.messages import (
    JSONObjectInput,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolResultStatus,
)
from novaagent.domain.ports import ToolDefinition, ToolExecutionContext


class StubTool:
    def __init__(
        self,
        name: str,
        *,
        description: str = "stub",
        schema: JSONObjectInput | None = None,
        behavior: str = "success",
    ) -> None:
        self.name = name
        self.description = description
        self.schema = schema or {"type": "object"}
        self.behavior = behavior

    def definition(self) -> ToolDefinition:
        return ToolDefinition(self.name, self.description, self.schema)

    async def execute(self, call: ToolCallBlock, context: ToolExecutionContext) -> ToolResultBlock:
        if self.behavior == "timeout":
            await asyncio.sleep(1)
        if self.behavior == "failure":
            raise RuntimeError("private failure")
        if self.behavior == "tool_timeout":
            raise ToolTimeoutError()
        call_id = "wrong-call" if self.behavior == "invalid" else call.call_id
        return ToolResultBlock(
            call_id,
            ToolResultStatus.SUCCESS,
            (TextBlock("ok"),),
        )


def test_registry_validates_arguments_and_executes_echo() -> None:
    async def scenario() -> None:
        registry = ToolRegistry((EchoTool(),))
        registry.freeze()
        call = ToolCallBlock("call-1", "echo", {"text": "hello"})
        result = await registry.execute(
            call,
            ToolExecutionContext("run-1", "session-1"),
            timeout_seconds=1,
        )
        assert result.status is ToolResultStatus.SUCCESS
        assert result.content == (TextBlock("hello"),)
        with pytest.raises(ToolArgumentsInvalidError):
            await registry.execute(
                ToolCallBlock("call-2", "echo", {}),
                ToolExecutionContext("run-1"),
                timeout_seconds=1,
            )
        with pytest.raises(ToolNotFoundError):
            await registry.execute(
                ToolCallBlock("call-3", "missing", {}),
                ToolExecutionContext("run-1"),
                timeout_seconds=1,
            )

    asyncio.run(scenario())


def test_registry_rejects_duplicates_and_freezes_after_bootstrap() -> None:
    registry = ToolRegistry((EchoTool(),))
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(EchoTool())
    registry.freeze()
    with pytest.raises(RuntimeError, match="frozen"):
        registry.register(EchoTool())


@pytest.mark.parametrize(
    "tool",
    [
        StubTool("Invalid"),
        StubTool("bad_description", description="x" * 1025),
        StubTool("bad_type", schema={"type": "array"}),
        StubTool("bad_schema", schema={"type": "object", "properties": "bad"}),
        StubTool("remote_ref", schema={"type": "object", "$ref": "https://example.test/x"}),
        StubTool(
            "large_schema",
            schema={"type": "object", "description": "x" * (32 * 1024)},
        ),
    ],
)
def test_registry_rejects_unsafe_definitions(tool: StubTool) -> None:
    with pytest.raises(ValueError):
        ToolRegistry((tool,))


def test_registry_enforces_tool_count_and_reports_presence() -> None:
    registry = ToolRegistry(StubTool(f"tool_{index}") for index in range(32))
    assert registry.has("tool_0")
    assert not registry.has("missing")
    with pytest.raises(ValueError, match="at most"):
        registry.register(StubTool("tool_overflow"))


@pytest.mark.parametrize(
    ("behavior", "error_type"),
    [
        ("timeout", ToolTimeoutError),
        ("failure", ToolExecutionFailedError),
        ("tool_timeout", ToolTimeoutError),
        ("invalid", ToolResultInvalidError),
    ],
)
def test_registry_maps_execution_failures(behavior: str, error_type: type[Exception]) -> None:
    async def scenario() -> None:
        registry = ToolRegistry((StubTool("stub", behavior=behavior),))
        with pytest.raises(error_type):
            await registry.execute(
                ToolCallBlock("call-1", "stub", {}),
                ToolExecutionContext("run-1"),
                timeout_seconds=0.001,
            )

    asyncio.run(scenario())
