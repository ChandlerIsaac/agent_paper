"""Application service for citation graphs and cited-paper RAG metadata."""
from hashlib import sha256
from langchain_core.documents import Document
from app.citations.crossref import CrossrefEnricher
from app.citations.extractor import extract_references
from app.citations.store import CitationStore
from app.agent.tools.reference_extraction import make_reference_extraction_tool

def format_citation_graph(data):
    nodes=[]
    for paper in data["papers"]:
        nodes.append({**paper,"label":paper["title"],"kind":"uploaded_paper" if paper["role"]=="uploaded" else "cited_paper"})
    edges=[{**e,"source":e["citing_paper_id"],"target":e["cited_paper_id"],"relation":"引用"} for e in data["edges"]]
    cited=[x for x in nodes if x["kind"]=="cited_paper"]
    return {"nodes":nodes,"edges":edges,"kind":"citation_graph","stats":{
        "uploaded_papers":sum(x["kind"]=="uploaded_paper" for x in nodes),"cited_papers":len(cited),
        "relations":len(edges),"enriched":sum(x["match_status"] in ("matched","doi_exact") for x in cited),
            "pending":sum(bool(x.get("needs_enrichment")) for x in cited)},
        "description":"有向边表示参考文献表中的引用关系；联网元数据仅在匹配阈值通过后写入。"}

class CitationGraphService:
    def __init__(self,database_path,vector_store,sparse_store,*,timeout: int=20,document_store=None):
        self.store=CitationStore(database_path); self.vector_store=vector_store
        self.sparse_store=sparse_store; self.enricher=CrossrefEnricher(timeout)
        self.document_store=document_store
    @staticmethod
    def vector_document_id(paper_id): return "citation_metadata:"+paper_id
    @staticmethod
    def bundle_document_id(document_id): return "citation_bundle:"+document_id
    def _delete_index(self,kb,paper_id):
        doc=self.vector_document_id(paper_id); self.vector_store.delete_document(kb,doc)
        if self.sparse_store: self.sparse_store.delete_document(kb,doc)
    def _rebuild_bundle(self,kb,document_id,core_id):
        bundle_id=self.bundle_document_id(document_id)
        self.vector_store.delete_document(kb,bundle_id)
        if self.sparse_store: self.sparse_store.delete_document(kb,bundle_id)
        graph=self.store.graph(kb)
        targets={edge["cited_paper_id"] for edge in graph["edges"] if edge["citing_paper_id"]==core_id}
        papers=[p for p in graph["papers"] if p["id"] in targets and p["match_status"] not in ("matched","doi_exact")]
        documents=[]
        for paper in papers:
            content="\n".join(x for x in ["引用论文题目："+paper["title"],
                "作者："+"、".join(paper.get("authors",[])) if paper.get("authors") else "",
                "期刊或会议："+paper.get("venue","") if paper.get("venue") else "",
                "年份："+str(paper.get("year")) if paper.get("year") else "",
                "DOI："+paper.get("doi","") if paper.get("doi") else ""] if x)
            chunk_id=sha256(f"{kb}:{bundle_id}:{paper['id']}:local-v1".encode()).hexdigest()
            documents.append(Document(page_content=content,metadata={"knowledge_base_id":kb,
                "document_id":bundle_id,"chunk_id":chunk_id,"source":paper["title"],"page":0,
                "kind":"cited_paper","paper_id":paper["id"],"metadata_provider":paper["metadata_provider"]}))
        if documents:
            self.vector_store.add_documents(documents)
            if self.sparse_store: self.sparse_store.replace_document(kb,bundle_id,documents)
    def extract_document(self,kb,document_id,filename,file_path):
        before={p["id"] for p in self.store.graph(kb)["papers"] if p["role"]=="cited"}
        if self.document_store:
            tool=make_reference_extraction_tool(self.document_store,kb)
            extracted=tool.invoke({"document_id":document_id})
            if not extracted.get("ok"):
                raise KeyError(extracted.get("error","参考文献提取失败"))
            refs=extracted["references"]
        else:
            refs=[item.to_dict() for item in extract_references(file_path)]
        result=self.store.replace_document(kb,document_id,filename,refs)
        after={p["id"] for p in self.store.graph(kb)["papers"] if p["role"]=="cited"}
        for paper_id in before-after: self._delete_index(kb,paper_id)
        self._rebuild_bundle(kb,document_id,result["paper_id"])
        return {**result,"extraction_status":"completed"}
    def _index(self,kb,paper):
        document_id=self.vector_document_id(paper["id"]); self._delete_index(kb,paper["id"])
        fields=["引用论文题目："+paper["title"],"作者："+"、".join(paper.get("authors",[])) if paper.get("authors") else "",
            "摘要："+paper.get("abstract","") if paper.get("abstract") else "",
            "期刊或会议："+paper.get("venue","") if paper.get("venue") else "",
            "发表日期："+paper.get("publication_date","") if paper.get("publication_date") else "",
            "DOI："+paper.get("doi","") if paper.get("doi") else ""]
        chunk_id=sha256(f"{kb}:{document_id}:metadata-v1".encode()).hexdigest()
        doc=Document(page_content="\n".join(x for x in fields if x),metadata={"knowledge_base_id":kb,
            "document_id":document_id,"chunk_id":chunk_id,"source":paper["title"],"page":0,
            "kind":"cited_paper","paper_id":paper["id"],"metadata_provider":paper["metadata_provider"]})
        self.vector_store.add_documents([doc])
        if self.sparse_store: self.sparse_store.replace_document(kb,document_id,[doc])
    def enrich(self,kb,*,accepted: bool,limit: int=30):
        candidates=self.store.candidates(kb,min(max(limit,1),50))
        if not accepted: return {"accepted":False,"pending":len(candidates),"matched":0,"failed":0}
        matched=failed=ambiguous=0
        for candidate,metadata,score,error in self.enricher.enrich_many(candidates):
            if not metadata:
                ambiguous += int(bool(score)); failed += int(bool(error)); continue
            paper={**candidate,**metadata,"id":candidate["id"],"authors":metadata.get("authors",[])}
            self._index(kb,paper)
            self.store.update_metadata(candidate["id"],metadata)
            matched+=1
        if matched:
            for core in (p for p in self.store.graph(kb)["papers"] if p["role"]=="uploaded"):
                self._rebuild_bundle(kb,core["document_id"],core["id"])
        return {"accepted":True,"requested":len(candidates),"matched":matched,"ambiguous":ambiguous,
            "failed":failed,"pending":len(self.store.candidates(kb,10000))}
    def graph(self,kb):
        return format_citation_graph(self.store.graph(kb))
    def delete_document(self,kb,document_id):
        bundle_id=self.bundle_document_id(document_id)
        self.vector_store.delete_document(kb,bundle_id)
        if self.sparse_store: self.sparse_store.delete_document(kb,bundle_id)
        for paper_id in self.store.delete_document(kb,document_id): self._delete_index(kb,paper_id)
    def delete_kb(self,kb): self.store.delete_kb(kb)
