"""Check whether the configured chat model is available."""

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def require_env(name: str) -> str:
    """Read a required environment variable."""

    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"缺少环境变量：{name}")
    return value


def main() -> None:
    """Send a minimal request to the chat model."""

    model = ChatOpenAI(
        api_key=require_env("MIMO_API_KEY"),
        base_url=require_env("MIMO_BASE_URL"),
        model=require_env("MODEL_NAME"),
        temperature=0,
        timeout=60,
        max_retries=2,
    )

    response = model.invoke("你是什么模型？")
    print(response.content)


if __name__ == "__main__":
    main()