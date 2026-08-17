from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    name: str
    model: str


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    provider: str
    model: str
    text_input: bool = True
    text_output: bool = True
    native_streaming: bool = False
    tool_calling: bool = False
    reasoning_summary: bool = False
    image_input: bool = False
    audio_input: bool = False
    usage: bool = True
