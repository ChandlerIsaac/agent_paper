"""E5 embedding adapter for LangChain."""

from functools import lru_cache
from threading import Lock

from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer

from app.core.config import get_settings


class E5Embeddings(Embeddings):
    """Generate normalized multilingual E5 vectors."""

    def __init__(self, model_name: str, revision: str, device: str, offline: bool = True) -> None:
        self.model_name = model_name
        self.revision = revision
        self.device = device
        self.offline = offline
        self._model: SentenceTransformer | None = None
        self._lock = Lock()

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    self._model = SentenceTransformer(
                        self.model_name,
                        revision=self.revision,
                        device=self.device,
                        local_files_only=self.offline,
                    )
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        passages = [
            text if text.startswith("passage: ") else f"passage: {text}"
            for text in texts
        ]
        vectors = self.model.encode(
            passages,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        query = text if text.startswith("query: ") else f"query: {text}"
        vector = self.model.encode(
            query,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vector.tolist()


@lru_cache(maxsize=1)
def get_embeddings() -> E5Embeddings:
    """Return the process-wide embedding adapter."""

    settings = get_settings()
    return E5Embeddings(
        model_name=settings.embedding_model,
        revision=settings.embedding_model_revision,
        device=settings.embedding_device,
        offline=settings.embedding_offline,
    )
