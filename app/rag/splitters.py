"""Metadata-preserving document splitting."""

import hashlib
from collections import defaultdict
from collections.abc import Sequence

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


DEFAULT_SEPARATORS = ["\n\n", "\n", "。", "！", "？", ". ", " ", ""]


def split_documents(
    documents: Sequence[Document],
    *,
    chunk_size: int = 500,
    chunk_overlap: int = 80,
) -> list[Document]:
    """Split documents while preserving citation metadata."""

    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap 必须满足 0 <= overlap < chunk_size")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=DEFAULT_SEPARATORS,
        length_function=len,
    )
    raw_chunks = splitter.split_documents(list(documents))
    counters: dict[tuple[str, int], int] = defaultdict(int)
    chunks: list[Document] = []

    for chunk in raw_chunks:
        text = chunk.page_content.strip()
        if not text:
            continue

        metadata = dict(chunk.metadata)
        key = (str(metadata["document_id"]), int(metadata["page"]))
        chunk_index = counters[key]
        counters[key] += 1
        knowledge_base_id = str(metadata.get("knowledge_base_id", ""))
        identity = (
            f"{knowledge_base_id}:{key[0]}:{key[1]}:"
            f"{chunk_index}:{text}"
        )

        metadata["chunk_index"] = chunk_index
        metadata["chunk_id"] = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        chunks.append(Document(page_content=text, metadata=metadata))

    return chunks
