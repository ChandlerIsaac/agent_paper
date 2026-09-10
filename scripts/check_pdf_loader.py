"""Manually check PDF text extraction and metadata."""

import sys
from pathlib import Path

from app.rag.loaders import load_pdf_pages


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "用法：python -m scripts.check_pdf_loader PDF路径"
        )

    pdf_path = Path(sys.argv[1])
    documents = load_pdf_pages(pdf_path)

    print(f"文件：{pdf_path.name}")
    print(f"页数：{len(documents)}")

    document_ids = {
        document.metadata["document_id"]
        for document in documents
    }
    assert len(document_ids) == 1

    for expected_page, document in enumerate(documents, start=1):
        metadata = document.metadata
        text = document.page_content

        assert metadata["page"] == expected_page
        assert metadata["page_index"] == expected_page - 1
        assert metadata["total_pages"] == len(documents)
        assert metadata["source"] == pdf_path.name

        preview = text[:100].replace("\n", " ")
        print(
            f"第 {metadata['page']} 页｜"
            f"{len(text)} 个字符｜{preview}"
        )

    document_id = documents[0].metadata["document_id"]
    print(f"document_id：{document_id}")
    print("PDF 页面正文和元数据验证成功")


if __name__ == "__main__":
    main()