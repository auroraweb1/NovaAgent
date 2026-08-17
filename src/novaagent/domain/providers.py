from typing import Literal

ProviderName = Literal["qwen", "doubao"]
ALLOWED_PROVIDERS: frozenset[str] = frozenset({"qwen", "doubao"})
PROVIDER_SECRET_ENV: dict[str, str] = {
    "qwen": "DASHSCOPE_API_KEY",
    "doubao": "DOUBAO_API_KEY",
}
