from langchain_core.documents import Document

from app.rag.sparse_store import (
    SparseBM25Store,
    reciprocal_rank_fusion,
    tokenize,
)


def document(chunk_id,document_id,text,kb='kb',page=1):
    return Document(page_content=text,metadata={
        'chunk_id':chunk_id,'document_id':document_id,
        'knowledge_base_id':kb,'source':document_id+'.pdf','page':page,
    })


def test_tokenizer_preserves_identifiers_and_chinese_bigrams():
    terms=tokenize('MlanDTI 使用注意力机制，DOI 10.1145/ABC-123')
    assert {'mlandti','注意','机制','10.1145/abc-123'} <= set(terms)


def test_bm25_persists_replaces_and_isolates_knowledge_bases(tmp_path):
    path=tmp_path/'business.sqlite3'
    store=SparseBM25Store(path)
    store.replace_document('kb-a','a',[
        document('a1','a','MlanDTI evaluates the exact BindingDB benchmark','kb-a',3)
    ])
    store.replace_document('kb-a','b',[
        document('b1','b','A general attention model','kb-a',2)
    ])
    store.replace_document('kb-b','private',[
        document('p1','private','BindingDB private result','kb-b',1)
    ])
    reloaded=SparseBM25Store(path)
    hits=reloaded.search('BindingDB','kb-a',top_k=5)
    assert [item[0].metadata['chunk_id'] for item in hits]==['a1']
    assert all(item[0].metadata['knowledge_base_id']=='kb-a' for item in hits)
    reloaded.replace_document('kb-a','a',[
        document('a2','a','DrugBank replacement text','kb-a',4)
    ])
    assert reloaded.search('BindingDB','kb-a',top_k=5)==[]
    assert reloaded.search('DrugBank','kb-a',top_k=5)[0][0].metadata['page']==4
    reloaded.delete_document('kb-a','a')
    assert reloaded.search('DrugBank','kb-a',top_k=5)==[]
    reloaded.delete_knowledge_base('kb-b')
    assert reloaded.search('BindingDB','kb-b',top_k=5)==[]


def test_rrf_promotes_chunks_supported_by_both_rankings():
    first=document('first','a','semantic match')
    second=document('second','b','exact term')
    dense=[(first,.95),(second,.80)]
    sparse=[(second,4.2)]
    fused=reciprocal_rank_fusion(dense,sparse,top_k=2,rank_constant=60)
    assert fused[0][0].metadata['chunk_id']=='second'
    assert fused[0][0].metadata['retrieval_channels']==['dense','sparse']
    assert fused[0][1]>fused[1][1]
