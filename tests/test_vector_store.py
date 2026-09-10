from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from milvus_lite.server_manager import server_manager_instance

from app.core.config import Settings
from app.rag.vector_store import MilvusVectorStore


class KeywordEmbeddings(Embeddings):
    """Deterministic embeddings for testing storage semantics."""

    terms = ("attention", "protein", "database")

    def _embed(self, text: str) -> list[float]:
        lowered = text.lower()
        vector = [float(lowered.count(term)) for term in self.terms]
        vector.append(0.01)
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def make_settings(path: Path) -> Settings:
    return Settings(
        mimo_api_key="test-key",
        mimo_base_url="https://example.com/v1",
        model_name="test-model",
        langsmith_tracing=False,
        milvus_lite_path=path,
        milvus_collection="test_chunks",
    )


def test_milvus_filters_and_deletes_by_knowledge_base(tmp_path: Path) -> None:
    vector_store = MilvusVectorStore(
        make_settings(tmp_path / "vectors.db"),
        KeywordEmbeddings(),
    )
    try:
        assert vector_store.delete_document("kb-a", "missing")

        vector_store.add_documents(
            [
                Document(
                    page_content="multilevel attention mechanism",
                    metadata={
                        "chunk_id": "kb-a-chunk",
                        "document_id": "paper-a",
                        "knowledge_base_id": "kb-a",
                        "source": "a.pdf",
                        "page": 4,
                    },
                ),
                Document(
                    page_content="protein interaction database",
                    metadata={
                        "chunk_id": "kb-b-chunk",
                        "document_id": "paper-b",
                        "knowledge_base_id": "kb-b",
                        "source": "b.pdf",
                        "page": 2,
                    },
                ),
            ]
        )

        hits = vector_store.search("attention", "kb-a", top_k=5)
        assert len(hits) == 1
        assert hits[0][0].metadata["knowledge_base_id"] == "kb-a"

        assert vector_store.delete_document("kb-a", "paper-a")
        assert vector_store.search("attention", "kb-a", top_k=5) == []
    finally:
        vector_store.store.client.close()
        server_manager_instance.release_all()
