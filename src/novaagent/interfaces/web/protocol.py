from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal, cast, overload

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from novaagent.domain.errors import (
    ProtocolValidationError,
    UnsupportedContentTypeError,
    UnsupportedProtocolVersionError,
)
from novaagent.domain.events import (
    AgentEvent,
    AgentEventPayload,
    ArtifactPayload,
    ContextPreparedPayload,
    ErrorPayload,
    MessageCompletedPayload,
    MessageStartedPayload,
    ReasoningSummaryDeltaPayload,
    RunCancelledPayload,
    RunCompletedPayload,
    RunFailedPayload,
    RunStartedPayload,
    TextDeltaPayload,
    TokenUsage,
    ToolCallPayload,
    ToolResultPayload,
)
from novaagent.domain.messages import (
    AudioRefBlock,
    ContentBlock,
    FileRefBlock,
    ImageRefBlock,
    JSONObjectInput,
    Message,
    MessageRole,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolResultStatus,
)

PROTOCOL_VERSION = "1"


class ProtocolSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")


class TextBlockSchema(ProtocolSchema):
    type: Literal["text"]
    text: str


class ImageRefBlockSchema(ProtocolSchema):
    type: Literal["image_ref"]
    resource_id: str
    media_type: str
    name: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None


class AudioRefBlockSchema(ProtocolSchema):
    type: Literal["audio_ref"]
    resource_id: str
    media_type: str
    name: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None


class FileRefBlockSchema(ProtocolSchema):
    type: Literal["file_ref"]
    resource_id: str
    media_type: str
    name: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None


class ToolCallBlockSchema(ProtocolSchema):
    type: Literal["tool_call"]
    call_id: str
    tool_name: str
    arguments: dict[str, JsonValue]


class ToolResultBlockSchema(ProtocolSchema):
    type: Literal["tool_result"]
    call_id: str
    status: Literal["success", "error"]
    content: list[ContentBlockSchema]
    error_code: str | None = None


type ContentBlockSchema = Annotated[
    TextBlockSchema
    | ImageRefBlockSchema
    | AudioRefBlockSchema
    | FileRefBlockSchema
    | ToolCallBlockSchema
    | ToolResultBlockSchema,
    Field(discriminator="type"),
]


class MessageSchema(ProtocolSchema):
    protocol_version: Literal["1"]
    message_id: str
    role: Literal["system", "user", "assistant", "tool"]
    content: list[ContentBlockSchema]
    created_at: datetime
    name: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class AgentEventSchema(ProtocolSchema):
    protocol_version: Literal["1"]
    event_id: str
    run_id: str
    sequence: int
    type: str
    occurred_at: datetime
    payload: dict[str, JsonValue]


class TokenUsageSchema(ProtocolSchema):
    input_tokens: int
    output_tokens: int


def message_to_dict(message: Message) -> dict[str, object]:
    raw: dict[str, object] = {
        "protocol_version": PROTOCOL_VERSION,
        "message_id": message.message_id,
        "role": message.role.value,
        "content": [_block_to_dict(block) for block in message.content],
        "created_at": message.created_at,
        "metadata": _thaw_json_object(message.metadata),
    }
    if message.name is not None:
        raw["name"] = message.name
    return cast(
        dict[str, object],
        MessageSchema.model_validate(raw).model_dump(mode="json", exclude_none=True),
    )


def message_from_dict(data: Mapping[str, object]) -> Message:
    _validate_version(data)
    _validate_content_types(data.get("content"))
    try:
        schema = MessageSchema.model_validate(dict(data))
    except ValidationError as error:
        raise _schema_error(error) from error
    return _message_from_schema(schema)


def event_to_dict(event: AgentEvent) -> dict[str, object]:
    raw: dict[str, object] = {
        "protocol_version": PROTOCOL_VERSION,
        "event_id": event.event_id,
        "run_id": event.run_id,
        "sequence": event.sequence,
        "type": event.type,
        "occurred_at": event.occurred_at,
        "payload": _payload_to_dict(event.payload),
    }
    return cast(
        dict[str, object],
        AgentEventSchema.model_validate(raw).model_dump(mode="json", exclude_none=True),
    )


def event_from_dict(data: Mapping[str, object]) -> AgentEvent:
    _validate_version(data)
    try:
        schema = AgentEventSchema.model_validate(dict(data))
    except ValidationError as error:
        raise _schema_error(error) from error
    payload = _payload_from_dict(schema.type, schema.payload)
    return AgentEvent(
        event_id=schema.event_id,
        run_id=schema.run_id,
        sequence=schema.sequence,
        occurred_at=schema.occurred_at,
        payload=payload,
    )


def _message_from_schema(schema: MessageSchema) -> Message:
    return Message(
        message_id=schema.message_id,
        role=MessageRole(schema.role),
        content=tuple(_block_from_schema(block) for block in schema.content),
        created_at=schema.created_at,
        name=schema.name,
        metadata=cast(JSONObjectInput, schema.metadata),
    )


def _block_from_schema(schema: ContentBlockSchema) -> ContentBlock:
    if isinstance(schema, TextBlockSchema):
        return TextBlock(schema.text)
    if isinstance(schema, ImageRefBlockSchema):
        return ImageRefBlock(
            schema.resource_id,
            schema.media_type,
            schema.name,
            schema.size_bytes,
            schema.sha256,
        )
    if isinstance(schema, AudioRefBlockSchema):
        return AudioRefBlock(
            schema.resource_id,
            schema.media_type,
            schema.name,
            schema.size_bytes,
            schema.sha256,
        )
    if isinstance(schema, FileRefBlockSchema):
        return FileRefBlock(
            schema.resource_id,
            schema.media_type,
            schema.name,
            schema.size_bytes,
            schema.sha256,
        )
    if isinstance(schema, ToolCallBlockSchema):
        return ToolCallBlock(
            schema.call_id, schema.tool_name, cast(JSONObjectInput, schema.arguments)
        )
    return ToolResultBlock(
        call_id=schema.call_id,
        status=ToolResultStatus(schema.status),
        content=tuple(_block_from_schema(block) for block in schema.content),
        error_code=schema.error_code,
    )


def _block_to_dict(block: ContentBlock) -> dict[str, object]:
    if isinstance(block, TextBlock):
        return {"type": block.type, "text": block.text}
    if isinstance(block, ToolCallBlock):
        return {
            "type": block.type,
            "call_id": block.call_id,
            "tool_name": block.tool_name,
            "arguments": _thaw_json_object(block.arguments),
        }
    if isinstance(block, ToolResultBlock):
        data: dict[str, object] = {
            "type": block.type,
            "call_id": block.call_id,
            "status": block.status.value,
            "content": [_block_to_dict(item) for item in block.content],
        }
        if block.error_code is not None:
            data["error_code"] = block.error_code
        return data
    data = {
        "type": block.type,
        "resource_id": block.resource_id,
        "media_type": block.media_type,
    }
    if block.name is not None:
        data["name"] = block.name
    if block.size_bytes is not None:
        data["size_bytes"] = block.size_bytes
    if block.sha256 is not None:
        data["sha256"] = block.sha256
    return data


def _payload_to_dict(payload: object) -> dict[str, object]:
    if isinstance(payload, RunStartedPayload):
        return {} if payload.session_id is None else {"session_id": payload.session_id}
    if isinstance(payload, MessageStartedPayload):
        return {"message_id": payload.message_id}
    if isinstance(payload, ContextPreparedPayload):
        return {
            "included_messages": payload.included_messages,
            "dropped_messages": payload.dropped_messages,
            "estimated_input_tokens": payload.estimated_input_tokens,
        }
    if isinstance(payload, TextDeltaPayload):
        return {"message_id": payload.message_id, "delta": payload.delta}
    if isinstance(payload, ReasoningSummaryDeltaPayload):
        return {"delta": payload.delta}
    if isinstance(payload, ToolCallPayload):
        return {"call": _block_to_dict(payload.call)}
    if isinstance(payload, ToolResultPayload):
        return {"result": _block_to_dict(payload.result)}
    if isinstance(payload, ArtifactPayload):
        return {
            "artifact_id": payload.artifact_id,
            "resource": _block_to_dict(payload.resource),
        }
    if isinstance(payload, ErrorPayload):
        data: dict[str, object] = {
            "code": payload.code,
            "message": payload.message,
            "retryable": payload.retryable,
        }
        if payload.field is not None:
            data["field"] = payload.field
        return data
    if isinstance(payload, MessageCompletedPayload):
        return {"message": message_to_dict(payload.message)}
    if isinstance(payload, RunCompletedPayload):
        data = {"message_id": payload.message_id}
        if payload.usage is not None:
            data["usage"] = {
                "input_tokens": payload.usage.input_tokens,
                "output_tokens": payload.usage.output_tokens,
            }
        return data
    if isinstance(payload, RunFailedPayload):
        return {"error_code": payload.error_code}
    if isinstance(payload, RunCancelledPayload):
        return {} if payload.reason is None else {"reason": payload.reason}
    raise ProtocolValidationError("Unknown event payload", field="payload")


def _payload_from_dict(event_type: str, payload: Mapping[str, JsonValue]) -> AgentEventPayload:
    data = cast(dict[str, object], dict(payload))
    try:
        if event_type == "run_started":
            return RunStartedPayload(session_id=_optional_str(data, "session_id"))
        if event_type == "message_started":
            return MessageStartedPayload(message_id=_required_str(data, "message_id"))
        if event_type == "context_prepared":
            return ContextPreparedPayload(
                included_messages=_required_int(data, "included_messages"),
                dropped_messages=_required_int(data, "dropped_messages"),
                estimated_input_tokens=_required_int(data, "estimated_input_tokens"),
            )
        if event_type == "text_delta":
            return TextDeltaPayload(
                message_id=_required_str(data, "message_id"),
                delta=_required_str(data, "delta", allow_whitespace=True),
            )
        if event_type == "reasoning_summary_delta":
            return ReasoningSummaryDeltaPayload(
                delta=_required_str(data, "delta", allow_whitespace=True)
            )
        if event_type == "tool_call":
            call_block = _block_from_payload(data, "call", ToolCallBlockSchema)
            return ToolCallPayload(call=call_block)
        if event_type == "tool_result":
            result_block = _block_from_payload(data, "result", ToolResultBlockSchema)
            return ToolResultPayload(result=result_block)
        if event_type == "artifact":
            resource_block = _block_from_payload(data, "resource", FileRefBlockSchema)
            return ArtifactPayload(
                artifact_id=_required_str(data, "artifact_id"), resource=resource_block
            )
        if event_type == "error":
            retryable = data.get("retryable")
            if not isinstance(retryable, bool):
                raise ProtocolValidationError(
                    "payload.retryable must be a boolean", field="payload.retryable"
                )
            return ErrorPayload(
                code=_required_str(data, "code"),
                message=_required_str(data, "message"),
                retryable=retryable,
                field=_optional_str(data, "field"),
            )
        if event_type == "message_completed":
            raw_message = data.get("message")
            if not isinstance(raw_message, Mapping):
                raise ProtocolValidationError(
                    "payload.message must be an object", field="payload.message"
                )
            return MessageCompletedPayload(message=message_from_dict(raw_message))
        if event_type == "run_completed":
            raw_usage = data.get("usage")
            usage = None
            if raw_usage is not None:
                if not isinstance(raw_usage, Mapping):
                    raise ProtocolValidationError(
                        "payload.usage must be an object", field="payload.usage"
                    )
                usage_schema = TokenUsageSchema.model_validate(dict(raw_usage))
                usage = TokenUsage(
                    input_tokens=usage_schema.input_tokens,
                    output_tokens=usage_schema.output_tokens,
                )
            return RunCompletedPayload(message_id=_required_str(data, "message_id"), usage=usage)
        if event_type == "run_failed":
            return RunFailedPayload(error_code=_required_str(data, "error_code"))
        if event_type == "run_cancelled":
            return RunCancelledPayload(reason=_optional_str(data, "reason"))
    except ValidationError as error:
        raise _schema_error(error) from error
    raise ProtocolValidationError(f"Unknown event type '{event_type}'", field="type")


@overload
def _block_from_payload(
    data: Mapping[str, object], key: str, schema_type: type[ToolCallBlockSchema]
) -> ToolCallBlock: ...


@overload
def _block_from_payload(
    data: Mapping[str, object], key: str, schema_type: type[ToolResultBlockSchema]
) -> ToolResultBlock: ...


@overload
def _block_from_payload(
    data: Mapping[str, object], key: str, schema_type: type[FileRefBlockSchema]
) -> FileRefBlock: ...


def _block_from_payload(
    data: Mapping[str, object],
    key: str,
    schema_type: type[ToolCallBlockSchema] | type[ToolResultBlockSchema] | type[FileRefBlockSchema],
) -> ToolCallBlock | ToolResultBlock | FileRefBlock:
    raw = data.get(key)
    if not isinstance(raw, Mapping):
        raise ProtocolValidationError(f"payload.{key} must be an object", field=f"payload.{key}")
    schema = schema_type.model_validate(dict(raw))
    return cast(
        ToolCallBlock | ToolResultBlock | FileRefBlock,
        _block_from_schema(schema),
    )


def _required_str(data: Mapping[str, object], key: str, *, allow_whitespace: bool = False) -> str:
    value = data.get(key)
    if not isinstance(value, str) or value == "" or (not allow_whitespace and not value.strip()):
        raise ProtocolValidationError(
            f"payload.{key} must be a non-empty string", field=f"payload.{key}"
        )
    return value


def _required_int(data: Mapping[str, object], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolValidationError(f"payload.{key} must be an integer", field=f"payload.{key}")
    return value


def _optional_str(data: Mapping[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProtocolValidationError(f"payload.{key} must be a string", field=f"payload.{key}")
    return value


def _validate_version(data: Mapping[str, object]) -> None:
    version = data.get("protocol_version")
    if version != PROTOCOL_VERSION:
        raise UnsupportedProtocolVersionError(str(version))


def _validate_content_types(content: object) -> None:
    if not isinstance(content, list):
        return
    supported = {"text", "image_ref", "audio_ref", "file_ref", "tool_call", "tool_result"}
    for item in content:
        if isinstance(item, Mapping):
            block_type = item.get("type")
            if isinstance(block_type, str) and block_type not in supported:
                raise UnsupportedContentTypeError(block_type)


def _schema_error(error: ValidationError) -> ProtocolValidationError:
    first = error.errors(include_url=False)[0]
    path = ".".join(str(part) for part in first["loc"])
    return ProtocolValidationError(str(first["msg"]), field=path or None)


def _thaw_json(value: object) -> JsonValue:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return cast(JsonValue, value)


def _thaw_json_object(value: Mapping[str, object]) -> dict[str, JsonValue]:
    return {key: _thaw_json(item) for key, item in value.items()}


ToolResultBlockSchema.model_rebuild()
MessageSchema.model_rebuild()
