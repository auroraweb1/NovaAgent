from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol

from novaagent.domain.errors import ProtocolValidationError, ToolCallError
from novaagent.domain.events import AgentEvent, TokenUsage
from novaagent.domain.messages import (
    JSONObjectInput,
    Message,
    ToolCallBlock,
    ToolResultBlock,
    freeze_json_object,
    validate_identifier,
)


class HealthPort(Protocol):
    def check(self) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: JSONObjectInput

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ToolCallError("Tool name must be non-empty", field="name")
        if not self.description.strip():
            raise ToolCallError("Tool description must be non-empty", field="description")
        object.__setattr__(
            self,
            "parameters",
            freeze_json_object(self.parameters, field_path="parameters"),
        )


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    run_id: str
    session_id: str | None = None
    metadata: JSONObjectInput = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        validate_identifier(self.run_id, field_path="run_id")
        if self.session_id is not None:
            validate_identifier(self.session_id, field_path="session_id")
        object.__setattr__(
            self,
            "metadata",
            freeze_json_object(self.metadata, field_path="metadata"),
        )


@dataclass(frozen=True, slots=True)
class ModelOptions:
    temperature: float | None = None
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.temperature is not None and not 0 <= self.temperature <= 2:
            raise ProtocolValidationError(
                "temperature must be between 0 and 2", field="temperature"
            )
        if self.max_output_tokens is not None and self.max_output_tokens <= 0:
            raise ProtocolValidationError(
                "max_output_tokens must be positive", field="max_output_tokens"
            )


@dataclass(frozen=True, slots=True)
class ModelRequest:
    messages: tuple[Message, ...]
    tools: tuple[ToolDefinition, ...] = ()
    options: ModelOptions = field(default_factory=ModelOptions)

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", tuple(self.tools))
        if not self.messages:
            raise ProtocolValidationError(
                "Model request requires at least one message", field="messages"
            )


@dataclass(frozen=True, slots=True)
class TextModelDelta:
    text: str

    def __post_init__(self) -> None:
        if self.text == "":
            raise ProtocolValidationError("Model text delta must not be empty", field="text")


@dataclass(frozen=True, slots=True)
class ReasoningSummaryModelDelta:
    text: str

    def __post_init__(self) -> None:
        if self.text == "":
            raise ProtocolValidationError("Reasoning summary delta must not be empty", field="text")


@dataclass(frozen=True, slots=True)
class ToolCallModelOutput:
    call: ToolCallBlock


@dataclass(frozen=True, slots=True)
class UsageModelOutput:
    usage: TokenUsage


type ModelOutput = (
    TextModelDelta | ReasoningSummaryModelDelta | ToolCallModelOutput | UsageModelOutput
)


class ModelPort(Protocol):
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelOutput]: ...


class EventSinkPort(Protocol):
    async def publish(self, event: AgentEvent) -> None: ...


class ToolPort(Protocol):
    def definition(self) -> ToolDefinition: ...

    async def execute(
        self, call: ToolCallBlock, context: ToolExecutionContext
    ) -> ToolResultBlock: ...


class SessionStorePort(Protocol):
    async def get_messages(self, session_id: str) -> tuple[Message, ...]: ...

    async def append_messages(self, session_id: str, messages: Sequence[Message]) -> None: ...
