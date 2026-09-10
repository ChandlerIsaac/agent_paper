"""Verify PDF parsing, E5 embeddings, Milvus Lite, and retrieval offline."""

import argparse
import tempfile
from pathlib import Path

from app.core.config import get_settings
from app.memory.store import SQLiteStore
from app.rag.embeddings import get_embeddings
from app.rag.service import RAGService
from app.rag.vector_store import MilvusVectorStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="在临时数据库中验证本地 RAG 检索链，不调用大模型。"
    )
    parser.add_argument("file", type=Path, help="待验证的 PDF/DOCX/MD/TXT 文件")
    parser.add_argument("query", help="用于语义检索的问题")
    parser.add_argument("--top-k", type=int, default=3, help="返回结果数量")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix="researchmate-rag-") as directory:
        root = Path(directory)
        settings = get_settings().model_copy(
            update={
                "database_path": root / "researchmate.sqlite3",
                "milvus_lite_path": root / "vectors.db",
                "milvus_collection": "check_rag_chunks",
                "langsmith_tracing": False,
            }
        )
        store = SQLiteStore(settings.database_path)
        vector_store = MilvusVectorStore(settings, get_embeddings())
        rag = RAGService(settings, store, vector_store)

        knowledge_base = store.create_knowledge_base("本地 RAG 验证")
        result = rag.ingest(args.file, knowledge_base["id"])
        hits = rag.search(args.query, knowledge_base["id"], args.top_k)

        print(
            f"入库成功：{result.filename} | "
            f"{result.page_count} 页 | {result.chunk_count} 个切片"
        )
        for number, hit in enumerate(hits, start=1):
            snippet = " ".join(hit.content.split())[:220]
            print(
                f"[{number}] {hit.source} 第 {hit.page} 页 | "
                f"score={hit.score:.4f}\n{snippet}"
            )

        vector_store.store.client.close()


if __name__ == "__main__":
    main()
