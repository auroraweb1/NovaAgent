from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NovaAgentError(Exception):
    """Base error with a stable public error code."""

    message: str
    code: str = "internal_error"
    field: str | None = None
    retryable: bool = False

    def __post_init__(self) -> None:
        super().__init__(self.message)


class ConfigurationError(NovaAgentError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message=message, code="configuration_invalid", field=field)


class SecretMissingError(NovaAgentError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message=message, code="secret_missing", field=field)


class AuthenticationRequiredError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(message="需要有效的 Web 访问令牌", code="authentication_required")


class RequestInvalidError(NovaAgentError):
    def __init__(self, message: str = "请求格式不正确", *, field: str | None = None) -> None:
        super().__init__(message=message, code="request_invalid", field=field)


class RequestTooLargeError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(message="请求内容过大", code="request_too_large")


class MessageTooLongError(NovaAgentError):
    def __init__(self, limit: int) -> None:
        super().__init__(
            message=f"输入内容不能超过 {limit:,} 个字符",
            code="message_too_long",
            field="message",
        )


class SessionNotFoundError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(message="会话不存在或已关闭", code="session_not_found")


class SessionBusyError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(
            message="当前会话正在生成，请先停止当前请求",
            code="session_busy",
            retryable=True,
        )


class SessionRevisionConflictError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(
            message="会话已被其他页面更新，请刷新后重试",
            code="session_revision_conflict",
            retryable=True,
        )


class SessionLimitReachedError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(message="当前服务的会话数量已达到上限", code="session_limit_reached")


class ContextTooLargeError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(
            message="当前消息超过上下文预算，请缩短输入后重试",
            code="context_too_large",
        )


class RunNotFoundError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(message="生成任务不存在或已经结束", code="run_not_found")


class StreamProtocolInvalidError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(
            message="千问流式响应格式无效，请稍后重试",
            code="stream_protocol_invalid",
        )


class PathConfigurationError(NovaAgentError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message=message, code="path_invalid", field=field)


class ProviderNotAllowedError(NovaAgentError):
    def __init__(self, provider: str) -> None:
        super().__init__(
            message=f"Provider '{provider}' is not allowed; only qwen is supported",
            code="provider_not_allowed",
            field="providers",
        )


class WebBindError(NovaAgentError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="web_bind_failed")


class DependencyUnavailableError(NovaAgentError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="dependency_unavailable", retryable=True)


class ProviderAuthenticationError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(
            message="千问认证失败，请检查服务端 API Key 和模型权限",
            code="provider_authentication_failed",
        )


class ProviderRateLimitedError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(
            message="千问请求过于频繁，请稍后重试",
            code="provider_rate_limited",
            retryable=True,
        )


class ProviderTimeoutError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(
            message="千问响应超时，请稍后重试",
            code="provider_timeout",
            retryable=True,
        )


class ProviderBusyError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(
            message="当前模型请求较多，请稍后重试",
            code="provider_busy",
            retryable=True,
        )


class ProviderModelInvalidError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(
            message="千问模型配置无效或当前模型不兼容",
            code="provider_model_invalid",
            field="providers.qwen.model",
        )


class ProviderInputRejectedError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(
            message="千问拒绝了当前输入，请修改内容后重试",
            code="provider_input_rejected",
            field="message",
        )


class ProviderUnavailableError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(
            message="千问服务暂时不可用，请稍后重试",
            code="provider_unavailable",
            retryable=True,
        )


class ProviderResponseInvalidError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(
            message="千问返回了无法处理的响应，请稍后重试",
            code="provider_response_invalid",
            retryable=True,
        )


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


class ToolNotFoundError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(message="请求的工具不可用", code="tool_not_found", retryable=False)


class ToolArgumentsInvalidError(NovaAgentError):
    def __init__(self, field: str | None = None) -> None:
        super().__init__(
            message="工具参数无效",
            code="tool_arguments_invalid",
            field=field,
            retryable=False,
        )


class ToolTimeoutError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(message="工具执行超时", code="tool_timeout", retryable=False)


class ToolExecutionFailedError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(message="工具未能完成请求", code="tool_execution_failed", retryable=False)


class ToolResultInvalidError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(message="工具结果无效", code="tool_result_invalid", retryable=False)


class AgentStepLimitError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(message="Agent 达到最大步骤数", code="agent_step_limit_reached")


class AgentToolCallLimitError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(message="Agent 达到工具调用上限", code="agent_tool_call_limit_reached")


class AgentTimeoutError(NovaAgentError):
    def __init__(self, code: str = "agent_timeout") -> None:
        super().__init__(message="Agent 执行超时", code=code, retryable=True)


class AgentContextLimitError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(message="Agent 工作上下文超过预算", code="agent_context_limit_reached")


class AgentModelOutputInvalidError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(
            message="模型未返回可处理的 Agent 结果",
            code="agent_model_output_invalid",
            retryable=True,
        )


class EmptyMessageError(NovaAgentError):
    def __init__(self) -> None:
        super().__init__(
            message="请输入内容后再发送",
            code="message_empty",
            field="message",
        )
