"""Chat-model construction."""

from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    """Build the OpenAI-compatible MIMO chat model."""

    settings = get_settings()
    return ChatOpenAI(
        api_key=settings.mimo_api_key.get_secret_value(),
        base_url=str(settings.mimo_base_url),
        model=settings.model_name,
        temperature=0,
        timeout=60,
        max_retries=2,
        stream_usage=True,
    )
