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


def test_citation_count_question_uses_complete_graph_not_top_k() -> None:
    class NoSearchRAG:
        retrieval_mode="hybrid"
        def search(self,*args,**kwargs):
            raise AssertionError("aggregate citation questions must not use Top-K retrieval")
    class Citations:
        def graph(self,kb):
            return {"papers":[
                {"id":"core","role":"uploaded","title":"Seed"},
                {"id":"p1","role":"cited","title":"Paper One","authors":[],"venue":"A","year":2020,"match_status":"local_extracted"},
                {"id":"p2","role":"cited","title":"Paper Two","authors":[],"venue":"B","year":2021,"match_status":"matched"},
            ],"edges":[{"id":"e1"},{"id":"e2"}]}
    model=FakeListChatModel(responses=["共有2篇参考文献。[来源 1]"])
    graph=build_research_graph(NoSearchRAG(),model,citation_store=Citations())
    result=ResearchAgent(graph).ask("所有参考文献总共有多少篇？","kb","thread")
    assert result["citations"][0]["kind"] == "citation_graph"
    assert "2篇" in result["answer"]
