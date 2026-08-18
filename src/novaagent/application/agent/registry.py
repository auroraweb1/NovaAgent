from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from novaagent.domain.errors import (
    ToolArgumentsInvalidError,
    ToolExecutionFailedError,
    ToolNotFoundError,
    ToolResultInvalidError,
    ToolTimeoutError,
)
from novaagent.domain.messages import TextBlock, ToolCallBlock, ToolResultBlock, ToolResultStatus
from novaagent.domain.ports import ToolDefinition, ToolExecutionContext, ToolPort


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    port: ToolPort
    validator: Draft202012Validator


class ToolRegistry:
    def __init__(self, tools: Iterable[ToolPort] = ()) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        self._frozen = False
        for tool in tools:
            self.register(tool)

    def register(self, tool: ToolPort) -> None:
        if self._frozen:
            raise RuntimeError("Tool registry is frozen")
        definition = tool.definition()
        if len(self._tools) >= MAX_TOOLS:
            raise ValueError(f"tool registry supports at most {MAX_TOOLS} tools")
        if not _TOOL_NAME_PATTERN.fullmatch(definition.name):
            raise ValueError(f"invalid tool name: {definition.name}")
        description = definition.description.strip()
        if not 1 <= len(description) <= 1024:
            raise ValueError(f"invalid description for tool {definition.name}")
        if definition.name in self._tools:
            raise ValueError(f"duplicate tool: {definition.name}")
        schema = cast(dict[str, object], _thaw(definition.parameters))
        if schema.get("type") != "object":
            raise ValueError(f"tool {definition.name} parameters must use object type")
        if len(json.dumps(schema, ensure_ascii=False).encode("utf-8")) > MAX_SCHEMA_BYTES:
            raise ValueError(f"schema for tool {definition.name} is too large")
        if _has_remote_reference(schema):
            raise ValueError(f"remote schema references are not allowed for tool {definition.name}")
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as error:
            raise ValueError(f"invalid schema for tool {definition.name}") from error
        validator = Draft202012Validator(schema)
        self._tools[definition.name] = RegisteredTool(tool, validator)

    def freeze(self) -> None:
        self._frozen = True

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(item.port.definition() for item in self._tools.values())

    def has(self, name: str) -> bool:
        return name in self._tools

    async def execute(
        self,
        call: ToolCallBlock,
        context: ToolExecutionContext,
        *,
        timeout_seconds: float,
    ) -> ToolResultBlock:
        registered = self._tools.get(call.tool_name)
        if registered is None:
            raise ToolNotFoundError()
        errors = sorted(
            registered.validator.iter_errors(dict(call.arguments)), key=lambda item: list(item.path)
        )
        if errors:
            field = ".".join(str(part) for part in errors[0].path) or "arguments"
            raise ToolArgumentsInvalidError(field=f"arguments.{field}")
        try:
            result = await asyncio.wait_for(
                registered.port.execute(call, context), timeout=timeout_seconds
            )
        except TimeoutError as error:
            raise ToolTimeoutError() from error
        except (ToolNotFoundError, ToolArgumentsInvalidError, ToolTimeoutError):
            raise
        except Exception as error:
            raise ToolExecutionFailedError() from error
        if (
            not isinstance(result, ToolResultBlock)
            or result.call_id != call.call_id
            or not all(isinstance(block, TextBlock) for block in result.content)
        ):
            raise ToolResultInvalidError()
        return result


class EchoTool:
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="echo",
            description="Return the supplied text unchanged for Agent loop diagnostics.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 2000}},
                "required": ["text"],
                "additionalProperties": False,
            },
        )

    async def execute(self, call: ToolCallBlock, context: ToolExecutionContext) -> ToolResultBlock:
        text = cast(str, call.arguments["text"])
        return ToolResultBlock(
            call_id=call.call_id,
            status=ToolResultStatus.SUCCESS,
            content=(TextBlock(text),),
        )


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _has_remote_reference(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if (
                key in {"$ref", "$dynamicRef"}
                and isinstance(item, str)
                and not item.startswith("#")
            ):
                return True
            if _has_remote_reference(item):
                return True
    elif isinstance(value, list):
        return any(_has_remote_reference(item) for item in value)
    return False


_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MAX_TOOLS = 32
MAX_SCHEMA_BYTES = 32 * 1024
