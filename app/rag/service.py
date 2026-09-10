"""Document ingestion and evidence retrieval service."""

from dataclasses import asdict, dataclass
from pathlib import Path

from langchain_core.documents import Document

from app.core.config import Settings
from app.memory.store import SQLiteStore
from app.rag.loaders import load_document
from app.rag.splitters import split_documents
from app.rag.vector_store import MilvusVectorStore


@dataclass(frozen=True)
class IngestResult:
    document_id: str
    filename: str
    page_count: int
    chunk_count: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SearchHit:
    content: str
    score: float
    document_id: str
    chunk_id: str
    source: str
    page: int

    def to_dict(self) -> dict:
        return asdict(self)


class RAGService:
    """Coordinate loaders, splitting, persistence, and retrieval."""

    def __init__(
        self,
        settings: Settings,
        business_store: SQLiteStore,
        vector_store: MilvusVectorStore,
    ) -> None:
        self.settings = settings
        self.business_store = business_store
        self.vector_store = vector_store

    def _unlink_managed_file(self, file_path: str | Path) -> None:
        """Delete files only when they live below the configured upload root."""
        path = Path(file_path).resolve()
        upload_root = self.settings.upload_dir.resolve()
        if path.is_relative_to(upload_root):
            path.unlink(missing_ok=True)

    def ingest(self, file_path: str | Path, knowledge_base_id: str) -> IngestResult:
        pages = load_document(file_path)
        document_id = str(pages[0].metadata["document_id"])
        path = Path(file_path).resolve()
        previous = self.business_store.get_document(
            knowledge_base_id,
            document_id,
        )

        for page in pages:
            page.metadata["knowledge_base_id"] = knowledge_base_id

        chunks = split_documents(
            pages,
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
        )
        if not self.vector_store.delete_document(knowledge_base_id, document_id):
            raise RuntimeError("旧文档向量清理失败，已停止写入")
        self.vector_store.add_documents(chunks)

        result = IngestResult(
            document_id=document_id,
            filename=path.name,
            page_count=len(pages),
            chunk_count=len(chunks),
        )
        self.business_store.add_document(
            document_id=document_id,
            knowledge_base_id=knowledge_base_id,
            filename=path.name,
            file_path=str(path),
            page_count=result.page_count,
            chunk_count=result.chunk_count,
        )
        if previous:
            previous_path = Path(previous["file_path"]).resolve()
            if previous_path != path:
                self._unlink_managed_file(previous_path)
        return result

    def search(
        self,
        query: str,
        knowledge_base_id: str,
        top_k: int | None = None,
    ) -> list[SearchHit]:
        results = self.vector_store.search(
            query=query,
            knowledge_base_id=knowledge_base_id,
            top_k=top_k or self.settings.retrieval_top_k,
        )
        hits = []
        for document, score in results:
            hits.append(
                SearchHit(
                    content=document.page_content,
                    score=float(score),
                    document_id=str(document.metadata["document_id"]),
                    chunk_id=str(document.metadata["chunk_id"]),
                    source=str(document.metadata["source"]),
                    page=int(document.metadata["page"]),
                )
            )
        return hits

    def reindex(
        self,
        knowledge_base_id: str,
        document_id: str,
    ) -> IngestResult:
        record = self.business_store.get_document(
            knowledge_base_id,
            document_id,
        )
        if record is None:
            raise KeyError("文档不存在")
        path = Path(record["file_path"])
        if not path.is_file():
            raise FileNotFoundError(f"原始文件不存在：{path}")
        return self.ingest(path, knowledge_base_id)

    def delete_document(
        self,
        knowledge_base_id: str,
        document_id: str,
    ) -> dict:
        record = self.business_store.get_document(
            knowledge_base_id,
            document_id,
        )
        if record is None:
            raise KeyError("文档不存在")
        if not self.vector_store.delete_document(knowledge_base_id, document_id):
            raise RuntimeError("Milvus 文档向量删除失败")
        self.business_store.delete_document(knowledge_base_id, document_id)
        self._unlink_managed_file(record["file_path"])
        return {"deleted": True, "document_id": document_id}

    def delete_knowledge_base(self, knowledge_base_id: str) -> dict:
        if not self.business_store.knowledge_base_exists(knowledge_base_id):
            raise KeyError("知识库不存在")
        records = [
            self.business_store.get_document(knowledge_base_id, item["id"])
            for item in self.business_store.list_documents(knowledge_base_id)
        ]
        if not self.vector_store.delete_knowledge_base(knowledge_base_id):
            raise RuntimeError("Milvus 知识库向量删除失败")
        self.business_store.delete_knowledge_base(knowledge_base_id)
        for record in records:
            if record:
                self._unlink_managed_file(record["file_path"])
        return {"deleted": True, "knowledge_base_id": knowledge_base_id}
