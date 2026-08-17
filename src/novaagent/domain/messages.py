from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar

from novaagent.domain.errors import MessageRoleError, ProtocolValidationError, ToolCallError

type JSONScalar = None | bool | int | float | str
type JSONValue = JSONScalar | tuple[JSONValue, ...] | Mapping[str, JSONValue]
type JSONObject = Mapping[str, JSONValue]
type JSONInput = JSONScalar | list[JSONInput] | tuple[JSONInput, ...] | Mapping[str, JSONInput]
type JSONObjectInput = Mapping[str, JSONInput]

_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def freeze_json(value: object, *, field_path: str = "value") -> JSONValue:
    """Copy a JSON-compatible value into an immutable representation."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProtocolValidationError("JSON numbers must be finite", field=field_path)
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProtocolValidationError("JSON object keys must be strings", field=field_path)
            frozen[key] = freeze_json(item, field_path=f"{field_path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            freeze_json(item, field_path=f"{field_path}[{index}]")
            for index, item in enumerate(value)
        )
    raise ProtocolValidationError(
        f"Value at '{field_path}' is not JSON-compatible", field=field_path
    )


def freeze_json_object(value: Mapping[str, object], *, field_path: str) -> JSONObject:
    frozen = freeze_json(value, field_path=field_path)
    if not isinstance(frozen, Mapping):  # pragma: no cover - guaranteed by the input type
        raise ProtocolValidationError("Expected a JSON object", field=field_path)
    return frozen


def validate_identifier(value: str, *, field_path: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolValidationError("Identifier must be a non-empty string", field=field_path)


def validate_optional_name(value: str | None, *, field_path: str) -> None:
    if value is not None and not value.strip():
        raise ProtocolValidationError("Name must be non-empty when provided", field=field_path)


def validate_utc_datetime(value: datetime, *, field_path: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ProtocolValidationError("Datetime must be timezone-aware UTC", field=field_path)


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolResultStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class TextBlock:
    type: ClassVar[str] = "text"
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or self.text == "":
            raise ProtocolValidationError("Text must not be empty", field="text")


def _validate_resource(
    *,
    resource_id: str,
    media_type: str,
    name: str | None,
    size_bytes: int | None,
    sha256: str | None,
) -> None:
    validate_identifier(resource_id, field_path="resource_id")
    if not media_type.strip() or "/" not in media_type:
        raise ProtocolValidationError("media_type must be a MIME type", field="media_type")
    validate_optional_name(name, field_path="name")
    if size_bytes is not None and (isinstance(size_bytes, bool) or size_bytes < 0):
        raise ProtocolValidationError("size_bytes must be non-negative", field="size_bytes")
    if sha256 is not None and not _SHA256_PATTERN.fullmatch(sha256):
        raise ProtocolValidationError(
            "sha256 must contain 64 hexadecimal characters", field="sha256"
        )


@dataclass(frozen=True, slots=True)
class ImageRefBlock:
    type: ClassVar[str] = "image_ref"
    resource_id: str
    media_type: str
    name: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None

    def __post_init__(self) -> None:
        _validate_resource(
            resource_id=self.resource_id,
            media_type=self.media_type,
            name=self.name,
            size_bytes=self.size_bytes,
            sha256=self.sha256,
        )


@dataclass(frozen=True, slots=True)
class AudioRefBlock:
    type: ClassVar[str] = "audio_ref"
    resource_id: str
    media_type: str
    name: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None

    def __post_init__(self) -> None:
        _validate_resource(
            resource_id=self.resource_id,
            media_type=self.media_type,
            name=self.name,
            size_bytes=self.size_bytes,
            sha256=self.sha256,
        )


@dataclass(frozen=True, slots=True)
class FileRefBlock:
    type: ClassVar[str] = "file_ref"
    resource_id: str
    media_type: str
    name: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None

    def __post_init__(self) -> None:
        _validate_resource(
            resource_id=self.resource_id,
            media_type=self.media_type,
            name=self.name,
            size_bytes=self.size_bytes,
            sha256=self.sha256,
        )


@dataclass(frozen=True, slots=True)
class ToolCallBlock:
    type: ClassVar[str] = "tool_call"
    call_id: str
    tool_name: str
    arguments: JSONObjectInput = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not self.call_id.strip():
            raise ToolCallError("call_id must be non-empty", field="call_id")
        if not self.tool_name.strip():
            raise ToolCallError("tool_name must be non-empty", field="tool_name")
        object.__setattr__(
            self,
            "arguments",
            freeze_json_object(self.arguments, field_path="arguments"),
        )


@dataclass(frozen=True, slots=True)
class ToolResultBlock:
    type: ClassVar[str] = "tool_result"
    call_id: str
    status: ToolResultStatus
    content: tuple[ContentBlock, ...]
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not self.call_id.strip():
            raise ToolCallError("call_id must be non-empty", field="call_id")
        try:
            object.__setattr__(self, "status", ToolResultStatus(self.status))
        except ValueError as error:
            raise ProtocolValidationError("Unknown tool result status", field="status") from error
        object.__setattr__(self, "content", tuple(self.content))
        if not self.content:
            raise ProtocolValidationError("Tool result content must not be empty", field="content")
        if not all(isinstance(block, _CONTENT_BLOCK_TYPES) for block in self.content):
            raise ProtocolValidationError("Unknown content block", field="content")
        if self.status is ToolResultStatus.ERROR:
            if self.error_code is None or not self.error_code.strip():
                raise ProtocolValidationError(
                    "Failed tool results require error_code", field="error_code"
                )
        elif self.error_code is not None:
            raise ProtocolValidationError(
                "Successful tool results cannot include error_code", field="error_code"
            )


type ContentBlock = (
    TextBlock | ImageRefBlock | AudioRefBlock | FileRefBlock | ToolCallBlock | ToolResultBlock
)

_CONTENT_BLOCK_TYPES = (
    TextBlock,
    ImageRefBlock,
    AudioRefBlock,
    FileRefBlock,
    ToolCallBlock,
    ToolResultBlock,
)


@dataclass(frozen=True, slots=True)
class Message:
    message_id: str
    role: MessageRole
    content: tuple[ContentBlock, ...]
    created_at: datetime
    name: str | None = None
    metadata: JSONObjectInput = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        validate_identifier(self.message_id, field_path="message_id")
        try:
            object.__setattr__(self, "role", MessageRole(self.role))
        except ValueError as error:
            raise MessageRoleError("Unknown message role", field="role") from error
        object.__setattr__(self, "content", tuple(self.content))
        if not self.content:
            raise ProtocolValidationError("Message content must not be empty", field="content")
        if not all(isinstance(block, _CONTENT_BLOCK_TYPES) for block in self.content):
            raise ProtocolValidationError("Unknown content block", field="content")
        if not any(
            not isinstance(block, TextBlock) or block.text.strip() for block in self.content
        ):
            raise ProtocolValidationError(
                "Message must contain meaningful content", field="content"
            )
        validate_utc_datetime(self.created_at, field_path="created_at")
        validate_optional_name(self.name, field_path="name")
        object.__setattr__(
            self,
            "metadata",
            freeze_json_object(self.metadata, field_path="metadata"),
        )
        self._validate_role_content()

    def _validate_role_content(self) -> None:
        if self.role is MessageRole.SYSTEM and not all(
            isinstance(block, TextBlock) for block in self.content
        ):
            raise MessageRoleError("System messages only support text", field="content")
        if self.role is MessageRole.TOOL and not any(
            isinstance(block, ToolResultBlock) for block in self.content
        ):
            raise MessageRoleError("Tool messages require a tool result block", field="content")
