from langchain_core.documents import Document
import pytest

from app.rag.splitters import split_documents


def test_splitter_preserves_metadata_and_adds_chunk_ids() -> None:
    page = Document(
        page_content=("retrieval augmented generation " * 60).strip(),
        metadata={
            "document_id": "doc-1",
            "source": "paper.pdf",
            "page": 3,
        },
    )

    chunks = split_documents([page], chunk_size=120, chunk_overlap=20)

    assert len(chunks) > 1
    assert all(chunk.metadata["page"] == 3 for chunk in chunks)
    assert all(chunk.metadata["source"] == "paper.pdf" for chunk in chunks)
    assert len({chunk.metadata["chunk_id"] for chunk in chunks}) == len(chunks)


def test_splitter_rejects_invalid_overlap() -> None:
    with pytest.raises(ValueError, match="overlap"):
        split_documents([], chunk_size=100, chunk_overlap=100)
