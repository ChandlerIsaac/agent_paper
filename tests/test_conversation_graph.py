import sqlite3
import json
import pytest
from langchain_core.language_models import FakeListChatModel
from langchain_core.messages import AIMessageChunk, HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from app.agent.workflow import ResearchAgent,build_research_graph
from app.rag.service import SearchHit


class RAG:
    def __init__(self,empty=False):
        self.queries=[]
        self.empty=empty
    def search(self,query,kb):
        self.queries.append(query)
        return [] if self.empty else [SearchHit('attention method',.9,'d','c','paper.pdf',4)]


def test_checkpoint_restart_and_contextual_followup(tmp_path):
    path=tmp_path/'checkpoints.db'
    rag=RAG()
    with sqlite3.connect(path,check_same_thread=False) as conn:
        graph=build_research_graph(rag,FakeListChatModel(responses=['方法使用注意力。[来源 1]']),SqliteSaver(conn))
        ResearchAgent(graph).ask('论文的方法是什么？','kb','alice-thread')
    with sqlite3.connect(path,check_same_thread=False) as conn:
        graph=build_research_graph(rag,FakeListChatModel(responses=['注意力方法的局限是什么？','其局限待验证。[来源 1]']),SqliteSaver(conn))
        saved=graph.get_state({'configurable':{'thread_id':'alice-thread'}}).values
        assert len(saved['messages'])==2
        assert graph.get_state({'configurable':{'thread_id':'bob-thread'}}).values=={}
        ResearchAgent(graph).ask('它有什么局限？','kb','alice-thread')
        assert rag.queries[-1]=='注意力方法的局限是什么？'
        assert len(graph.get_state({'configurable':{'thread_id':'alice-thread'}}).values['messages'])==4


class Web:
    def __init__(self):
        self.queries=[]
    def invoke(self,args):
        self.queries.append(args['query'])
        return {'results':[{'title':'Paper record','url':'https://doi.org/10.test/example','content':'Publisher: Example, 2021'}],
                'provider':'test'}


def test_insufficient_nonempty_evidence_uses_web_and_emits_trace():
    rag=RAG()
    web=Web()
    model=FakeListChatModel(responses=[
        '{"sufficient":false,"query":"paper publication"}',
        '出版记录见网页。[来源 2]'])
    events=[]
    graph=build_research_graph(rag,model,web_search=web)
    result=ResearchAgent(graph).ask('在哪发表？','kb','t',allow_web=True,on_event=events.append)
    assert len(rag.queries)==1
    assert len(web.queries)==1
    assert [x['stage'] for x in events]==['context','retrieve','assess','web_start','web','answer_start','answer']
    assert result['citations'][0]['kind']=='web'
    assert result['citations'][0]['url'].startswith('https://doi.org/')


def test_publication_question_forces_bibliographic_verification():
    web=Web()
    model=FakeListChatModel(responses=['经书目记录核验。[来源 2]'])
    result=ResearchAgent(build_research_graph(RAG(),model,web_search=web)).ask(
        '这篇文章发表在哪里？','kb','publication-thread',allow_web=True
    )
    assert len(web.queries)==1
    assert any(x['stage']=='web' for x in result['trace'])


def test_disabled_web_never_calls_search():
    web=Web()
    result=ResearchAgent(build_research_graph(RAG(empty=True),FakeListChatModel(responses=['rewritten']),web_search=web)).ask('q','kb','t')
    assert web.queries==[]
    assert '没有足够信息' in result['answer']


def test_note_evidence_is_separate():
    class Notes:
        def search(self,query,kb):
            return [dict(id='note',title='个人记录',content='待验证的偏好',score=.8)]
    graph=build_research_graph(RAG(),FakeListChatModel(responses=['个人笔记记录了偏好，未经验证。[来源 2]']),notes=Notes())
    result=ResearchAgent(graph).ask('记录是什么？','kb','t')
    assert result['citations'][0]['kind']=='note'


def test_search_error_preserves_local_evidence():
    class FailedWeb:
        def invoke(self,args):
            return {'results':[],'error':'测试网络不可用'}
    model=FakeListChatModel(responses=['{"sufficient":false}','当前仅有本地证据。[来源 1]'])
    result=ResearchAgent(build_research_graph(RAG(),model,web_search=FailedWeb())).ask('q','kb','t',allow_web=True)
    assert result['citations'][0]['kind']=='document'
    assert any(x['detail']=='测试网络不可用' for x in result['trace'])


def test_rejected_web_approval_never_calls_tool():
    web=Web()
    model=FakeListChatModel(responses=['仅依据本地证据回答。[来源 1]'])
    result=ResearchAgent(build_research_graph(RAG(),model,web_search=web)).ask(
        '这篇文章发表在哪里？','kb','reject-thread',allow_web=True,
        on_web_approval=lambda query,provider:False,
    )
    assert web.queries==[]
    assert result['citations'][0]['kind']=='document'
    assert any('拒绝联网' in x['detail'] for x in result['trace'])


def test_grouped_citation_keeps_every_referenced_source():
    class SixSources(RAG):
        def search(self,query,kb):
            return [SearchHit(f'evidence {i}',.9-i/100,f'd{i}',f'c{i}',f'paper-{i}.pdf',i)
                    for i in range(1,7)]
    model=FakeListChatModel(responses=['两条材料共同支持结论。[来源 2.6]'])
    result=ResearchAgent(build_research_graph(SixSources(),model)).ask(
        'q','kb','grouped-citation-thread'
    )
    assert result['answer'].endswith('[来源 2, 6]')
    assert [x['number'] for x in result['citations']]==[2,6]


def test_stream_usage_is_reported_for_whole_answer_call():
    class UsageModel(FakeListChatModel):
        def stream(self,*args,**kwargs):
            yield AIMessageChunk(content='有依据的回答。[来源 1]',usage_metadata={
                'input_tokens':120,'output_tokens':18,'total_tokens':138
            })
    result=ResearchAgent(build_research_graph(
        RAG(),UsageModel(responses=['unused'])
    )).ask('q','kb','usage-thread')
    assert result['usage']=={'input_tokens':120,'output_tokens':18,
                             'total_tokens':138,'model_calls':1,'reported':True}


def test_failed_turn_does_not_duplicate_user_input():
    class FailsOnce(FakeListChatModel):
        failures: int = 1

        def stream(self,*args,**kwargs):
            if self.failures:
                self.failures-=1
                raise RuntimeError('synthetic timeout')
            return super().stream(*args,**kwargs)

    agent=ResearchAgent(build_research_graph(
        RAG(),FailsOnce(responses=['重试成功。[来源 1]'])
    ))
    with pytest.raises(RuntimeError):
        agent.ask('failed question','kb','t')
    agent.ask('retry question','kb','t')
    state=agent.graph.get_state({'configurable':{'thread_id':'t'}}).values
    questions=[x.content for x in state['messages'] if isinstance(x,HumanMessage)]
    assert questions==['retry question']
