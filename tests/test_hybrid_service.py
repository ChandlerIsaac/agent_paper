from app.core.config import Settings
from app.memory.store import SQLiteStore
from app.rag.service import RAGService
from app.rag.sparse_store import SparseBM25Store
from langchain_core.documents import Document


class EmptyDenseStore:
    def __init__(self):
        self.documents=[]

    def add_documents(self,documents):
        self.documents.extend(documents)
        return [item.metadata['chunk_id'] for item in documents]

    def search(self,query,knowledge_base_id,top_k):
        return []

    def delete_document(self,knowledge_base_id,document_id):
        self.documents=[item for item in self.documents
                        if item.metadata['document_id']!=document_id]
        return True

    def delete_knowledge_base(self,knowledge_base_id):
        self.documents=[]
        return True


def test_ingest_search_and_delete_cover_sparse_index(tmp_path):
    upload=tmp_path/'uploads'
    upload.mkdir()
    source=upload/'paper.txt'
    source.write_text('The experiment uses the exact BioSNAP-DrugTarget benchmark.',
                      encoding='utf-8')
    database=tmp_path/'researchmate.sqlite3'
    store=SQLiteStore(database)
    kb=store.create_knowledge_base('test')['id']
    settings=Settings(
        mimo_api_key='test',mimo_base_url='https://example.com/v1',
        model_name='test',langsmith_tracing=False,database_path=database,
        upload_dir=upload,hybrid_search_enabled=True,retrieval_top_k=5,
    )
    sparse=SparseBM25Store(database)
    rag=RAGService(settings,store,EmptyDenseStore(),sparse)
    result=rag.ingest(source,kb)
    hits=rag.search('BioSNAP DrugTarget',kb)
    assert rag.retrieval_mode=='hybrid'
    assert hits[0].document_id==result.document_id
    assert hits[0].source=='paper.txt'
    rag.delete_document(kb,result.document_id)
    assert sparse.search('BioSNAP',kb,5)==[]
    assert not source.exists()


def test_search_deduplicates_the_same_cited_paper(tmp_path):
    class Dense(EmptyDenseStore):
        def search(self,query,knowledge_base_id,top_k):
            def item(chunk,document,source,paper):
                return Document(page_content=source,metadata={"chunk_id":chunk,"document_id":document,
                    "knowledge_base_id":knowledge_base_id,"source":source,"page":0,
                    "kind":"cited_paper","paper_id":paper,
                    "metadata_provider":"crossref" if chunk=="remote" else "local"}),.9
            return [item("local","bundle","Local title","paper-1"),
                    item("remote","citation","Enriched title","paper-1"),
                    item("other","bundle","Other paper","paper-2")]
    settings=Settings(mimo_api_key="x",mimo_base_url="https://example.com/v1",model_name="x",
        langsmith_tracing=False,database_path=tmp_path/"db.sqlite3",upload_dir=tmp_path,
        hybrid_search_enabled=False,retrieval_top_k=5)
    rag=RAGService(settings,SQLiteStore(tmp_path/"db.sqlite3"),Dense())
    hits=rag.search("query","kb")
    assert [hit.paper_id for hit in hits] == ["paper-1","paper-2"]
    assert hits[0].source == "Enriched title"
