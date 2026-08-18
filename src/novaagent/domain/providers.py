from typing import Literal

ProviderName = Literal["qwen"]
ALLOWED_PROVIDERS: frozenset[str] = frozenset({"qwen"})
PROVIDER_SECRET_ENV: dict[str, str] = {"qwen": "DASHSCOPE_API_KEY"}
