"""Document ingestion and evidence retrieval service."""

from dataclasses import asdict, dataclass
from pathlib import Path

from langchain_core.documents import Document

from app.core.config import Settings
from app.memory.store import SQLiteStore
from app.rag.loaders import load_document
from app.rag.sparse_store import SparseBM25Store, reciprocal_rank_fusion
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
    kind: str = "document"
    paper_id: str = ""
    metadata_provider: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class RAGService:
    """Coordinate loaders, splitting, persistence, and retrieval."""

    def __init__(
        self,
        settings: Settings,
        business_store: SQLiteStore,
        vector_store: MilvusVectorStore,
        sparse_store: SparseBM25Store | None = None,
    ) -> None:
        self.settings = settings
        self.business_store = business_store
        self.vector_store = vector_store
        self.sparse_store = sparse_store
        self.retrieval_mode = (
            "hybrid" if settings.hybrid_search_enabled and sparse_store else "dense"
        )

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
        if self.sparse_store:
            try:
                self.sparse_store.replace_document(
                    knowledge_base_id,document_id,chunks
                )
            except Exception:
                self.vector_store.delete_document(knowledge_base_id,document_id)
                raise

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
        limit = top_k or self.settings.retrieval_top_k
        candidate_k = max(limit,self.settings.hybrid_candidate_k)
        dense_results = self.vector_store.search(
            query=query,
            knowledge_base_id=knowledge_base_id,
            top_k=candidate_k,
        )
        if self.retrieval_mode=="hybrid":
            sparse_results = self.sparse_store.search(
                query,knowledge_base_id,candidate_k
            )
            results = reciprocal_rank_fusion(
                dense_results,sparse_results,top_k=candidate_k,
                rank_constant=self.settings.rrf_rank_constant,
            )
        else:
            results = dense_results
        hits = []
        seen_entities = {}
        for document, score in results:
            entity_key = str(document.metadata.get("paper_id") or document.metadata["chunk_id"])
            if entity_key in seen_entities:
                position=seen_entities[entity_key]
                current_provider=hits[position].metadata_provider
                new_provider=str(document.metadata.get("metadata_provider",""))
                if new_provider=="crossref" and current_provider!="crossref":
                    hits[position]=SearchHit(content=document.page_content,score=float(score),
                        document_id=str(document.metadata["document_id"]),chunk_id=str(document.metadata["chunk_id"]),
                        source=str(document.metadata["source"]),page=int(document.metadata["page"]),
                        kind=str(document.metadata.get("kind","document")),paper_id=str(document.metadata.get("paper_id","")),
                        metadata_provider=new_provider)
                continue
            seen_entities[entity_key]=len(hits)
            hits.append(
                SearchHit(
                    content=document.page_content,
                    score=float(score),
                    document_id=str(document.metadata["document_id"]),
                    chunk_id=str(document.metadata["chunk_id"]),
                    source=str(document.metadata["source"]),
                    page=int(document.metadata["page"]),
                    kind=str(document.metadata.get("kind","document")),
                    paper_id=str(document.metadata.get("paper_id","")),
                    metadata_provider=str(document.metadata.get("metadata_provider","")),
                )
            )
        return hits[:limit]

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
        if self.sparse_store:
            self.sparse_store.delete_document(knowledge_base_id,document_id)
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
        if self.sparse_store:
            self.sparse_store.delete_knowledge_base(knowledge_base_id)
        self.business_store.delete_knowledge_base(knowledge_base_id)
        for record in records:
            if record:
                self._unlink_managed_file(record["file_path"])
        return {"deleted": True, "knowledge_base_id": knowledge_base_id}
