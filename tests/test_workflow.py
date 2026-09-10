from langchain_core.language_models import FakeListChatModel

from app.agent.workflow import ResearchAgent, build_research_graph
from app.rag.service import SearchHit


class FakeRAGService:
    def search(
        self,
        query: str,
        knowledge_base_id: str,
        top_k: int | None = None,
    ) -> list[SearchHit]:
        return [
            SearchHit(
                content="first evidence",
                score=0.9,
                document_id="doc-1",
                chunk_id="chunk-1",
                source="first.pdf",
                page=1,
            ),
            SearchHit(
                content="second evidence",
                score=0.8,
                document_id="doc-2",
                chunk_id="chunk-2",
                source="second.pdf",
                page=2,
            ),
        ]


def test_agent_returns_only_citations_used_in_answer() -> None:
    model = FakeListChatModel(
        responses=["结论由第二条证据支持。[来源 2]"]
    )
    graph = build_research_graph(FakeRAGService(), model)
    tokens = []
    result = ResearchAgent(graph).ask(
        "question", "kb-1", "thread-1", on_token=tokens.append
    )

    assert result["answer"].endswith("[来源 2]")
    assert ''.join(tokens) == result["answer"]
    assert [item["number"] for item in result["citations"]] == [2]
    assert result["citations"][0]["source"] == "second.pdf"
