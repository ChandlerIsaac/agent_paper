from pathlib import Path

import pymupdf
import pytest

from app.rag.loaders import load_document, load_pdf_pages


def create_pdf(path: Path, texts: list[str]) -> None:
    with pymupdf.open() as pdf:
        for text in texts:
            page = pdf.new_page()
            page.insert_text((72, 72), text)
        pdf.save(path)


def test_pdf_loader_preserves_page_metadata(tmp_path: Path) -> None:
    path = tmp_path / "paper.pdf"
    create_pdf(path, ["first page evidence", "second page evidence"])

    documents = load_pdf_pages(path)

    assert len(documents) == 2
    assert documents[0].metadata["page"] == 1
    assert documents[1].metadata["page"] == 2
    assert documents[0].metadata["document_id"] == documents[1].metadata["document_id"]
    assert documents[0].metadata["source"] == "paper.pdf"


def test_text_loader(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text("# Evidence\nUseful finding.", encoding="utf-8")

    documents = load_document(path)

    assert documents[0].page_content.startswith("# Evidence")
    assert documents[0].metadata["file_type"] == "md"


def test_unsupported_extension(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("a,b", encoding="utf-8")

    with pytest.raises(ValueError, match="不支持"):
        load_document(path)
