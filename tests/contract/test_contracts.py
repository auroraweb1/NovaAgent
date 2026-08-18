from novaagent.domain.providers import ALLOWED_PROVIDERS, PROVIDER_SECRET_ENV


def test_provider_contract_is_explicitly_limited() -> None:
    assert ALLOWED_PROVIDERS == {"qwen"}
    assert PROVIDER_SECRET_ENV == {"qwen": "DASHSCOPE_API_KEY"}
