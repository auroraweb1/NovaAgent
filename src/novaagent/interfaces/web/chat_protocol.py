from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from novaagent.application.chat import SingleTurnChatResult
from novaagent.interfaces.web.protocol import MessageSchema, message_to_dict

PROTOCOL_VERSION = "1"


class ChatProtocolSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatRequestSchema(ChatProtocolSchema):
    message: str


class ProviderInfoSchema(ChatProtocolSchema):
    name: Literal["qwen"]
    model: str


class UsageSchema(ChatProtocolSchema):
    input_tokens: int
    output_tokens: int
    total_tokens: int


class ChatResponseSchema(ChatProtocolSchema):
    protocol_version: Literal["1"]
    run_id: str
    message: MessageSchema
    provider: ProviderInfoSchema
    usage: UsageSchema | None
    latency_ms: int


def chat_response_from_result(result: SingleTurnChatResult) -> ChatResponseSchema:
    usage = result.usage
    return ChatResponseSchema.model_validate(
        {
            "protocol_version": PROTOCOL_VERSION,
            "run_id": result.run_id,
            "message": message_to_dict(result.message),
            "provider": {"name": result.provider, "model": result.model},
            "usage": (
                {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "total_tokens": usage.total_tokens,
                }
                if usage is not None
                else None
            ),
            "latency_ms": result.latency_ms,
        }
    )
