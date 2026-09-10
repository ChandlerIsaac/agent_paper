"""A local-only tool for extracting structured references from registered files."""

from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from app.citations.extractor import extract_references


class ReferenceExtractionInput(BaseModel):
    document_id: str = Field(
        min_length=1,
        max_length=128,
        description="当前知识库中已登记的文档 ID；不是文件路径",
    )


def make_reference_extraction_tool(document_store, knowledge_base_id: str) -> StructuredTool:
    """Bind extraction to one knowledge base so the model cannot read arbitrary files."""

    def run(document_id: str) -> dict:
        record = document_store.get_document(knowledge_base_id, document_id)
        if record is None:
            return {
                "ok": False,
                "error": "文档不存在于当前知识库",
                "document_id": document_id,
                "references": [],
            }
        references = [item.to_dict() for item in extract_references(record["file_path"])]
        complete = sum(not item["needs_enrichment"] for item in references)
        return {
            "ok": True,
            "network_used": False,
            "document_id": document_id,
            "filename": record["filename"],
            "reference_count": len(references),
            "locally_complete_count": complete,
            "needs_enrichment_count": len(references) - complete,
            "references": references,
        }

    return StructuredTool.from_function(
        func=run,
        name="extract_document_references",
        description=(
            "从当前知识库中已上传的学术文档离线提取参考文献，返回作者、题名、"
            "期刊或会议、年份、DOI、原始引文和页码。该工具不联网。"
        ),
        args_schema=ReferenceExtractionInput,
    )
