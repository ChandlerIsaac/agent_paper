"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Validated application settings."""

    mimo_api_key: SecretStr = Field(validation_alias="MIMO_API_KEY")
    mimo_base_url: AnyHttpUrl = Field(validation_alias="MIMO_BASE_URL")
    model_name: str = Field(validation_alias="MODEL_NAME")

    embedding_model: str = Field(
        default="intfloat/multilingual-e5-small",
        validation_alias="EMBEDDING_MODEL",
    )
    embedding_model_revision: str = Field(
        default="614241f622f53c4eeff9890bdc4f31cfecc418b3",
        validation_alias="EMBEDDING_MODEL_REVISION",
    )
    embedding_device: Literal["cpu", "cuda"] = Field(
        default="cuda",
        validation_alias="EMBEDDING_DEVICE",
    )
    embedding_offline: bool = Field(
        default=True,
        validation_alias="EMBEDDING_OFFLINE",
    )

    cookie_secure: bool = False
    web_search_provider: Literal["crossref", "tavily"] = "crossref"
    tavily_api_key: SecretStr | None = None
    web_search_timeout: int = Field(default=20, ge=1, le=60)

    database_path: Path = Field(
        default=PROJECT_ROOT / "data" / "researchmate.sqlite3",
        validation_alias="DATABASE_PATH",
    )
    upload_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "uploads",
        validation_alias="UPLOAD_DIR",
    )
    milvus_lite_path: Path = Field(
        default=PROJECT_ROOT / "data" / "milvus" / "researchmate.db",
        validation_alias="MILVUS_LITE_PATH",
    )
    milvus_collection: str = Field(
        default="researchmate_chunks",
        validation_alias="MILVUS_COLLECTION",
    )
    chunk_size: int = Field(default=500, ge=100, validation_alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=80, ge=0, validation_alias="CHUNK_OVERLAP")
    retrieval_top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        validation_alias="RETRIEVAL_TOP_K",
    )
    hybrid_search_enabled: bool = Field(
        default=True,
        validation_alias="HYBRID_SEARCH_ENABLED",
    )
    hybrid_candidate_k: int = Field(
        default=10,
        ge=2,
        le=100,
        validation_alias="HYBRID_CANDIDATE_K",
    )
    rrf_rank_constant: int = Field(
        default=60,
        ge=1,
        le=1000,
        validation_alias="RRF_RANK_CONSTANT",
    )

    langsmith_tracing: bool = Field(
        default=False,
        validation_alias="LANGSMITH_TRACING",
    )
    langsmith_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="LANGSMITH_API_KEY",
    )
    langsmith_project: str = Field(
        default="researchmate",
        validation_alias="LANGSMITH_PROJECT",
    )

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    @model_validator(mode="after")
    def validate_settings(self) -> Self:
        """Validate related settings that depend on one another."""

        api_key = (
            self.langsmith_api_key.get_secret_value()
            if self.langsmith_api_key
            else ""
        )
        if self.langsmith_tracing and not api_key:
            raise ValueError(
                "启用 LANGSMITH_TRACING 时必须配置 LANGSMITH_API_KEY"
            )
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP 必须小于 CHUNK_SIZE")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache application settings."""

    return Settings()
