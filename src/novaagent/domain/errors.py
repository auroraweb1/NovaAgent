from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NovaAgentError(Exception):
    """Base error with a stable public error code."""

    message: str
    code: str = "internal_error"
    field: str | None = None

    def __post_init__(self) -> None:
        super().__init__(self.message)


class ConfigurationError(NovaAgentError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message=message, code="configuration_invalid", field=field)


class SecretMissingError(NovaAgentError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message=message, code="secret_missing", field=field)


class PathConfigurationError(NovaAgentError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message=message, code="path_invalid", field=field)


class ProviderNotAllowedError(NovaAgentError):
    def __init__(self, provider: str) -> None:
        super().__init__(
            message=f"Provider '{provider}' is not allowed; only qwen and doubao are supported",
            code="provider_not_allowed",
            field="providers",
        )


class WebBindError(NovaAgentError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="web_bind_failed")


class DependencyUnavailableError(NovaAgentError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="dependency_unavailable")


class ProtocolValidationError(NovaAgentError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message=message, code="protocol_invalid", field=field)


class UnsupportedProtocolVersionError(NovaAgentError):
    def __init__(self, version: str) -> None:
        super().__init__(
            message=f"Protocol version '{version}' is not supported",
            code="protocol_version_unsupported",
            field="protocol_version",
        )


class UnsupportedContentTypeError(NovaAgentError):
    def __init__(self, content_type: str) -> None:
        super().__init__(
            message=f"Content type '{content_type}' is not supported",
            code="content_type_unsupported",
            field="type",
        )


class EventSequenceError(NovaAgentError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message=message, code="event_sequence_invalid", field=field)


class MessageRoleError(NovaAgentError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message=message, code="message_role_invalid", field=field)


class ToolCallError(NovaAgentError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message=message, code="tool_call_invalid", field=field)


class EmptyMessageError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(
            message="请输入内容后再发送",
            code="message_empty",
            field="message",
        )
