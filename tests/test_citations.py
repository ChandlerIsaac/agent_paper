from langchain_core.documents import Document

from app.citations import extractor
from app.citations.crossref import match_score
from app.citations.store import CitationStore
from app.agent.tools.reference_extraction import make_reference_extraction_tool


def test_numbered_reference_extraction_keeps_provenance(monkeypatch):
    pages = [Document(page_content="""Introduction
Body text.
References
[1] Smith, J. 2021. A Reliable Paper Title. Journal X. doi:10.1000/test.1
[2] Li, M. 2020. Another Study. Conference Y.""",metadata={"page":1})]
    monkeypatch.setattr(extractor,"load_document",lambda path:pages)
    refs = extractor.extract_references("paper.pdf")
    assert len(refs) == 2
    assert refs[0].reference_number == 1
    assert refs[0].doi == "10.1000/test.1"
    assert refs[0].title == "A Reliable Paper Title"
    assert refs[0].authors
    assert refs[0].venue == "Journal X"
    assert refs[0].needs_enrichment is False
    assert refs[0].raw_reference.startswith("[1]")


def test_citation_store_separates_uploaded_and_cited_nodes(tmp_path):
    store = CitationStore(tmp_path/"research.sqlite3")
    result = store.replace_document("kb","doc","seed.pdf",[{
        "reference_number":1,"raw_reference":"Smith. 2021. Cited Paper.",
        "title":"Cited Paper","year":2021,"doi":"","page":8,
        "extraction_method":"numbered_reference_list",
    }])
    graph = store.graph("kb")
    assert result["citation_count"] == 1
    assert {paper["role"] for paper in graph["papers"]} == {"uploaded","cited"}
    assert graph["edges"][0]["extraction_page"] == 8


def test_crossref_match_requires_title_and_uses_year():
    candidate={"title":"Graph Neural Networks for Science","year":2022,"doi":""}
    exact={"title":["Graph Neural Networks for Science"],"published":{"date-parts":[[2022]]}}
    unrelated={"title":["Unrelated Clinical Trial"],"published":{"date-parts":[[2022]]}}
    assert match_score(candidate,exact) >= 0.99
    assert match_score(candidate,unrelated) < 0.78


def test_reference_tool_is_local_and_bound_to_registered_document(monkeypatch):
    class Store:
        def get_document(self,kb,doc):
            return {"filename":"paper.pdf","file_path":"/registered/paper.pdf"} if (kb,doc)==("kb","doc") else None
    sample=extractor.ExtractedReference(1,"[1] Smith. 2021. Paper.","Paper",2021,"",8,
        "numbered_reference_list",["Smith"],"Journal",False)
    monkeypatch.setattr("app.agent.tools.reference_extraction.extract_references",lambda path:[sample])
    tool=make_reference_extraction_tool(Store(),"kb")
    result=tool.invoke({"document_id":"doc"})
    assert result["network_used"] is False
    assert result["locally_complete_count"] == 1
    assert result["references"][0]["venue"] == "Journal"
    assert tool.invoke({"document_id":"other"})["ok"] is False


def test_suspicious_interleaved_reference_requests_enrichment(monkeypatch):
    pages=[Document(page_content="References\nLee, A. 2019. Wang, B. 2020. A mixed column title. Journal Z.",metadata={"page":4})]
    monkeypatch.setattr(extractor,"load_document",lambda path:pages)
    refs=extractor.extract_references("paper.pdf")
    assert refs[0].needs_enrichment is True
