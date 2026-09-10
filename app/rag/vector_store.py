"""Milvus Lite vector-store integration."""

from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_milvus import Milvus

from app.core.config import Settings


def escape_milvus_string(value: str) -> str:
    """Escape a string used in a Milvus filter expression."""

    return value.replace("\\", "\\\\").replace('"', '\\"')


class MilvusVectorStore:
    """Knowledge-base-isolated access to one Milvus collection."""

    def __init__(self, settings: Settings, embeddings: Embeddings) -> None:
        uri = Path(settings.milvus_lite_path)
        if not uri.is_absolute():
            uri = (settings.model_config.get("env_file").parent / uri).resolve()
        uri.parent.mkdir(parents=True, exist_ok=True)

        self.store = Milvus(
            embedding_function=embeddings,
            collection_name=settings.milvus_collection,
            connection_args={"uri": str(uri)},
            consistency_level="Strong",
            auto_id=False,
            enable_dynamic_field=True,
            index_params={
                "metric_type": "COSINE",
                "index_type": "AUTOINDEX",
                "params": {},
            },
            search_params={"metric_type": "COSINE", "params": {}},
        )

    def add_documents(self, documents: list[Document]) -> list[str]:
        ids = [str(document.metadata["chunk_id"]) for document in documents]
        return self.store.add_documents(documents, ids=ids)

    def search(self, query: str, knowledge_base_id: str, top_k: int):
        if not self.collection_exists():
            return []
        kb = escape_milvus_string(knowledge_base_id)
        return self.store.similarity_search_with_score(
            query,
            k=top_k,
            expr=f'knowledge_base_id == "{kb}"',
        )

    def collection_exists(self) -> bool:
        """Return whether the collection has been created by a first insert."""

        return bool(self.store.client.has_collection(self.store.collection_name))

    def delete_document(self, knowledge_base_id: str, document_id: str) -> bool:
        if not self.collection_exists():
            return True
        kb = escape_milvus_string(knowledge_base_id)
        doc = escape_milvus_string(document_id)
        return bool(self.store.delete(
            expr=f'knowledge_base_id == "{kb}" and document_id == "{doc}"'
        ))

    def delete_knowledge_base(self, knowledge_base_id: str) -> bool:
        if not self.collection_exists():
            return True
        kb = escape_milvus_string(knowledge_base_id)
        return bool(self.store.delete(expr=f'knowledge_base_id == "{kb}"'))
