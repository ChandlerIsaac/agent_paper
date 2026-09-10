"""Opt-in browser acceptance using synthetic local data; never calls a remote LLM."""
import os
import socket
import sqlite3
import threading
import time
from functools import lru_cache
from types import SimpleNamespace
import pytest

pytestmark = pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',
                                reason='Set RUN_BROWSER_TESTS=1 and install the browser extra')


def test_workspace_browser(tmp_path,monkeypatch):
    from playwright.sync_api import sync_playwright, expect
    import uvicorn
    import app.main as main
    from app.memory.workspace import WorkspaceStore
    from app.memory.notes import NoteMemory
    from app.agent.workflow import ResearchAgent,build_research_graph
    from app.rag.service import RAGService
    from app.rag.loaders import load_document
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langchain_core.language_models import FakeListChatModel
    from app.core.config import Settings
    from tests.test_workspace import Vectors

    settings=Settings(mimo_api_key='test',mimo_base_url='https://example.com/v1',model_name='test',
                      langsmith_tracing=False,upload_dir=tmp_path/'uploads',database_path=tmp_path/'app.sqlite3')
    store=WorkspaceStore(settings.database_path)
    class Index:
        def __init__(self):
            self.docs=[]
            self.store=SimpleNamespace(client=SimpleNamespace(close=lambda:None))
        def add_documents(self,docs):
            self.docs.extend(docs)
        def search(self,query,knowledge_base_id,top_k):
            return [(x,.9) for x in self.docs if x.metadata['knowledge_base_id']==knowledge_base_id][:top_k]
        def delete_document(self,kb,doc):
            self.docs=[x for x in self.docs if not(x.metadata['knowledge_base_id']==kb and x.metadata['document_id']==doc)]
            return True
        def delete_knowledge_base(self,kb):
            self.docs=[x for x in self.docs if x.metadata['knowledge_base_id']!=kb]
            return True
    index=Index()
    rag=RAGService(settings,store,index)
    notes=NoteMemory(store,Vectors(),'test')
    connection=sqlite3.connect(tmp_path/'checkpoints.db',check_same_thread=False)
    saver=SqliteSaver(connection)
    model=FakeListChatModel(responses=['**文档结论**说明了 attention mechanism。[来源 1]'])
    class Web:
        metadata={'provider':'test-search'}
        def invoke(self,args):
            return {'results':[{'title':'Verified record','url':'https://example.com/paper',
                                'content':'Published in a test venue'}],
                    'provider':'test-search','elapsed_seconds':.01}
    graph=build_research_graph(rag,model,saver,notes=notes,web_search=Web())
    rt=SimpleNamespace(store=store,rag=rag,notes=notes,settings=settings,agent=ResearchAgent(graph),
                       checkpointer=saver,connection=connection,vectors=index,mutation_lock=threading.RLock())
    @lru_cache()
    def runtime():
        return rt
    monkeypatch.setattr(main,'get_runtime',runtime)
    monkeypatch.setattr(main,'get_store',lambda:store)
    sock=socket.socket()
    sock.bind(('127.0.0.1',0))
    port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(main.app,log_level='warning'))
    worker=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True)
    worker.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(.05)
    errors=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/opt/google/chrome/chrome',headless=True,
                                      args=['--no-sandbox','--disable-dev-shm-usage'])
            page=browser.new_page(viewport={'width':1440,'height':960})
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{port}')
            page.locator('#username').fill('browser_user')
            page.locator('#password').fill('browser-password-123')
            page.locator('#register').click()
            page.locator('#auth').wait_for(state='hidden')
            page.once('dialog',lambda d:d.accept('Browser Research'))
            page.locator('#createKb').click()
            expect(page.locator('#kbSelect option')).to_have_count(1)
            page.locator('#file').set_input_files({'name':'evidence.txt','mimeType':'text/plain',
                                                  'buffer':b'The paper uses an attention mechanism to study protein interactions.'})
            page.locator('#uploadButton').click()
            page.locator('#documents .card').wait_for()
            page.locator('#question').fill('What method does the paper use?')
            page.locator('#question').press('Enter')
            expect(page.locator('.message.assistant .save-note')).to_have_count(1)
            expect(page.locator('.message.assistant .markdown-body strong')).to_have_count(1)
            expect(page.locator('.message.assistant .trace-duration').first).to_contain_text('用时')
            page.evaluate("renderMessage('assistant','usage',{trace:[{detail:'done'}],duration_seconds:2,usage:{reported:true,input_tokens:10,output_tokens:5,total_tokens:15}}).classList.add('usage-probe')")
            expect(page.locator('.trace-tokens').last).to_contain_text('Token 15')
            page.locator('.usage-probe').evaluate('element => element.remove()')
            assert page.locator('#question').input_value()==''
            page.locator('#question').fill('What are its limitations?')
            page.locator('#question').press('Enter')
            expect(page.locator('.message.assistant .save-note')).to_have_count(2)
            assert page.locator('.message').count()==4
            page.reload()
            expect(page.locator('.message')).to_have_count(4)
            expect(page.locator('.message.assistant .markdown-body strong')).to_have_count(2)
            page.locator('#allowWeb').check()
            page.locator('#question').fill('这篇文章发表在哪里？')
            page.locator('#question').press('Enter')
            page.locator('#webApproval').wait_for(state='visible')
            assert 'evidence' in page.locator('#approvalQuery').inner_text()
            page.locator('#acceptWeb').click()
            expect(page.locator('.message.assistant .save-note')).to_have_count(3)
            page.locator('.save-note').last.click()
            page.locator('#noteTitle').fill('Attention finding')
            page.locator('#noteForm button').click()
            page.locator('#notes .card').wait_for()
            page.locator('[data-tab=graph]').click()
            page.locator('.graph-node').first.click()
            page.locator('.page-buttons button').first.click()
            page.locator('#sourceText').wait_for()
            assert 'attention mechanism' in page.locator('#sourceText').inner_text()
            page.screenshot(path=str(tmp_path/'workspace-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.screenshot(path=str(tmp_path/'workspace-mobile.png'),full_page=True)
            assert errors==[]
            browser.close()
    finally:
        server.should_exit=True
        worker.join(timeout=10)
        sock.close()
