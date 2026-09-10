import sqlite3
from types import SimpleNamespace
from threading import RLock, Thread
import time
import pytest
from fastapi.testclient import TestClient
import app.main as main
from app.memory.store import SQLiteStore
from app.memory.workspace import WorkspaceStore
from app.memory.notes import NoteMemory


class Vectors:
    def embed_documents(self, texts):
        return [self.embed_query(x) for x in texts]

    def embed_query(self, text):
        return [float('attention' in text), float('protein' in text),0.01]


@pytest.fixture
def workspace(tmp_path,monkeypatch):
    store = WorkspaceStore(tmp_path/'workspace.sqlite3')
    memory = NoteMemory(store,Vectors(),'test@1')
    runtime = SimpleNamespace(store=store,notes=memory,mutation_lock=RLock())
    monkeypatch.setattr(main,'get_store',lambda:store)
    monkeypatch.setattr(main,'get_runtime',lambda:runtime)
    return store,runtime


def client(username):
    c = TestClient(main.app)
    c.headers['X-ResearchMate']='1'
    result=c.post('/api/auth/register',json={'username':username,'password':'long-password-123'})
    assert result.status_code==201,result.text
    return c,result.json()


def test_auth_isolation_and_csrf(workspace):
    alice,a=client('alice')
    bob,b=client('bob')
    kb=alice.post('/api/knowledge-bases',json={'name':'Private'}).json()['id']
    conv=alice.post('/api/conversations',json={'knowledge_base_id':kb}).json()['id']
    assert bob.get('/api/knowledge-bases').json()==[]
    routes=[f'/api/knowledge-bases/{kb}/documents',f'/api/knowledge-bases/{kb}/notes',
            f'/api/knowledge-bases/{kb}/graph',f'/api/conversations/{conv}/messages',
            f'/api/knowledge-bases/{kb}/documents/fake/pages/1']
    for route in routes:
        assert bob.get(route).status_code==404
    for route in (f'/api/knowledge-bases/{kb}',f'/api/knowledge-bases/{kb}/documents/fake',
                  f'/api/knowledge-bases/{kb}/notes/fake'):
        assert bob.delete(route).status_code==404
    for endpoint in ('/api/chat','/api/chat/stream'):
        assert bob.post(endpoint,json={'knowledge_base_id':kb,'thread_id':conv,'question':'secret'}).status_code==404
    unauth=TestClient(main.app)
    assert unauth.get('/api/conversations').status_code==401
    assert unauth.post('/api/auth/register',json={'username':'mallory','password':'long-password-123'}).status_code==403
    assert alice.post('/api/auth/logout').status_code==200
    assert alice.get('/api/auth/me').status_code==401
    assert alice.post('/api/auth/login',json={'username':'alice','password':'wrong-password-123'}).status_code==401
    assert alice.post('/api/auth/login',json={'username':'alice','password':'long-password-123'}).status_code==200


def test_legacy_unassigned_and_backup_safe(tmp_path):
    path=tmp_path/'old.sqlite3'
    old=SQLiteStore(path)
    kb=old.create_knowledge_base('old')
    old.add_message('old-thread','user','legacy question')
    updated=WorkspaceStore(path)
    user=updated.register('owner','long-password')
    assert updated.owned_kbs(user['id'])==[]
    assert updated.get_messages('old-thread')[0]['content']=='legacy question'
    assert updated.claim_legacy('owner')==1
    assert updated.owned_kbs(user['id'])[0]['id']==kb['id']
    assert updated.claim_legacy('owner')==0


def test_notes_semantic_search_persistence_and_scope(workspace):
    store,rt=workspace
    a=store.register('alice','long-password')
    b=store.register('bob','long-password')
    kb=store.create_owned_kb('A',a['id'])['id']
    other=store.create_owned_kb('B',b['id'])['id']
    note=rt.notes.save(kb,'method','attention mechanism')
    rt.notes.save(kb,'biology','protein analysis')
    rt.notes.save(other,'private','attention secret')
    reloaded=NoteMemory(WorkspaceStore(store.database_path),Vectors(),'test@1')
    hits=reloaded.search('attention',kb)
    assert hits[0]['id']==note['id']
    assert len(hits)==2
    assert all('secret' not in x['content'] for x in hits)
    assert reloaded.delete(kb,note['id'])
    assert not any(x['id']==note['id'] for x in reloaded.search('attention',kb))


def test_chat_stream_history_and_concurrency(workspace):
    store,rt=workspace
    c,user=client('alice')
    kb=c.post('/api/knowledge-bases',json={'name':'A'}).json()['id']
    conv=c.post('/api/conversations',json={'knowledge_base_id':kb}).json()['id']
    class Agent:
        def ask(self,*args,**kwargs):
            time.sleep(.01)
            event={'stage':'retrieve','detail':'检索完成'}
            if kwargs.get('on_event'):
                kwargs['on_event'](event)
            if kwargs.get('on_token'):
                kwargs['on_token']('Answer ')
                kwargs['on_token']('[来源 1]')
            return {'answer':'Answer [来源 1]','citations':[{'number':1,'source':'paper.pdf'}],'trace':[event]}
    rt.agent=Agent()
    payload={'knowledge_base_id':kb,'thread_id':conv,'question':'hello'}
    response=c.post('/api/chat/stream',json=payload)
    assert response.status_code==200
    assert all(x in response.text for x in ('event: status','event: token','event: result'))
    messages=c.get(f'/api/conversations/{conv}/messages').json()
    assert [x['role'] for x in messages]==['user','assistant']
    assert messages[1]['citations'][0]['source']=='paper.pdf'
    assert messages[1]['duration_seconds']>=.01
    assert WorkspaceStore(store.database_path).history(conv)==messages
    assert store.acquire(conv,user['id'])
    assert c.post('/api/chat',json=payload).status_code==409
    store.release(conv)
    other=c.post('/api/knowledge-bases',json={'name':'B'}).json()['id']
    assert c.post('/api/chat',json={**payload,'knowledge_base_id':other}).status_code==409


def test_stream_waits_for_same_user_web_approval(workspace):
    store,rt=workspace
    chat_client,user=client('alice')
    approver=TestClient(main.app)
    approver.headers['X-ResearchMate']='1'
    assert approver.post('/api/auth/login',json={
        'username':'alice','password':'long-password-123'
    }).status_code==200
    kb=chat_client.post('/api/knowledge-bases',json={'name':'A'}).json()['id']
    conv=chat_client.post('/api/conversations',json={'knowledge_base_id':kb}).json()['id']
    class ApprovalAgent:
        def ask(self,*args,**kwargs):
            accepted=kwargs['on_web_approval']('paper title','crossref')
            answer='用户允许联网' if accepted else '用户拒绝联网'
            return {'answer':answer,'citations':[],'trace':[]}
    rt.agent=ApprovalAgent()
    payload={'knowledge_base_id':kb,'thread_id':conv,'question':'venue?',
             'allow_web':True}
    response={}
    worker=Thread(target=lambda:response.setdefault(
        'value',chat_client.post('/api/chat/stream',json=payload)
    ))
    worker.start()
    approval_id=None
    for _ in range(100):
        with main.approval_lock:
            if main.approval_requests:
                approval_id=next(iter(main.approval_requests))
                break
        time.sleep(.02)
    assert approval_id
    intruder,_=client('bob')
    assert intruder.post('/api/chat/approvals/'+approval_id,
                         json={'accepted':True}).status_code==404
    assert approver.post('/api/chat/approvals/'+approval_id,
                         json={'accepted':True}).status_code==200
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert 'event: approval' in response['value'].text
    assert '用户允许联网' in response['value'].text


def test_graph_page_scope_and_no_invented_edges(workspace,tmp_path):
    store,rt=workspace
    c,user=client('alice')
    kb=c.post('/api/knowledge-bases',json={'name':'Research'}).json()['id']
    path=tmp_path/'paper.txt'
    path.write_text('Real document evidence',encoding='utf-8')
    store.add_document(document_id='doc',knowledge_base_id=kb,filename=path.name,
                       file_path=str(path),page_count=1,chunk_count=1)
    graph=c.get(f'/api/knowledge-bases/{kb}/graph').json()
    assert graph['kind']=='document_structure'
    assert graph['edges']==[{'source':kb,'target':'doc','relation':'包含'}]
    page=c.get(f'/api/knowledge-bases/{kb}/documents/doc/pages/1')
    assert page.json()['content']=='Real document evidence'
    assert c.get(f'/api/knowledge-bases/{kb}/documents/doc/pages/9').status_code==404
