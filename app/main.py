"""Authenticated local research workspace API."""
import asyncio
from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
import sqlite3
from threading import Event, Lock
import time
import uuid

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from app.api.schemas import ChatRequest, KnowledgeBaseCreate, NoteCreate, Credentials, ConversationCreate, Rename, WebApprovalDecision
from app.core.config import PROJECT_ROOT, get_settings
from app.core.logging import setup_logging
from app.rag.loaders import load_document
from app.runtime import get_runtime, get_store

setup_logging()
logger = logging.getLogger(__name__)
tasks = set()
approval_requests = {}
approval_lock = Lock()


@asynccontextmanager
async def lifespan(app):
    await asyncio.to_thread(get_store().reset_processing)
    yield
    with approval_lock:
        for approval in approval_requests.values():
            approval['event'].set()
        approval_requests.clear()
    if tasks:
        await asyncio.gather(*list(tasks),return_exceptions=True)
    if get_runtime.cache_info().currsize:
        rt = get_runtime()
        rt.connection.close()
        rt.vectors.store.client.close()
        get_runtime.cache_clear()


app = FastAPI(title='ResearchMate',version='0.2.0',lifespan=lifespan)
app.mount('/static',StaticFiles(directory=PROJECT_ROOT/'app'/'static'),name='static')


@app.middleware('http')
async def authentication(request: Request, call_next):
    path = request.url.path
    if path.startswith('/api/'):
        if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('X-ResearchMate') != '1':
            return JSONResponse({'detail':'缺少请求校验头 X-ResearchMate: 1'},status_code=403)
        if path not in ('/api/health','/api/auth/login','/api/auth/register'):
            user = await asyncio.to_thread(get_store().session_user,request.cookies.get('researchmate_session',''))
            if not user:
                return JSONResponse({'detail':'请先登录'},status_code=401)
            request.state.user = user
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'"
    if path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(KeyError)
async def missing(request, error):
    return JSONResponse({'detail':str(error.args[0])},status_code=404)


@app.exception_handler(Exception)
async def failure(request, error):
    logger.error('Request failed: %s',type(error).__name__)
    return JSONResponse({'detail':'处理失败，请查看服务器日志或稍后重试'},status_code=500)


def owned_kb(request, kb):
    return get_store().require_kb(kb,request.state.user['id'])


@app.get('/',include_in_schema=False)
def index():
    return FileResponse(PROJECT_ROOT/'app'/'static'/'index.html')


@app.get('/api/health')
def health():
    return {'status':'ok','version':app.version}


def set_session(response, user):
    response.set_cookie('researchmate_session',get_store().new_session(user['id']),
        httponly=True,secure=get_settings().cookie_secure,samesite='strict',max_age=604800)
    return user


@app.post('/api/auth/register',status_code=201)
def register(payload: Credentials, response: Response):
    try:
        user = get_store().register(payload.username,payload.password)
    except sqlite3.IntegrityError:
        raise HTTPException(409,'用户名已存在')
    return set_session(response,user)


@app.post('/api/auth/login')
def login(payload: Credentials, response: Response):
    try:
        user = get_store().login(payload.username,payload.password)
    except ValueError as error:
        raise HTTPException(429,str(error))
    if not user:
        raise HTTPException(401,'用户名或密码错误')
    return set_session(response,user)


@app.get('/api/auth/me')
def me(request: Request):
    return request.state.user


@app.post('/api/auth/logout')
def logout(request: Request,response: Response):
    get_store().logout(request.cookies.get('researchmate_session',''))
    response.delete_cookie('researchmate_session')
    return {'ok':True}


@app.post('/api/knowledge-bases',status_code=201)
def create_kb(payload: KnowledgeBaseCreate,request: Request):
    if not payload.name.strip():
        raise HTTPException(422,'知识库名称不能为空')
    return get_store().create_owned_kb(payload.name.strip(),request.state.user['id'])


@app.get('/api/knowledge-bases')
def list_kbs(request: Request):
    return get_store().owned_kbs(request.state.user['id'])


@app.delete('/api/knowledge-bases/{kb}')
def delete_kb(kb: str,request: Request):
    owned_kb(request,kb)
    rt = get_runtime()
    with rt.mutation_lock:
        threads = [x for x in rt.store.conversations(request.state.user['id']) if x['knowledge_base_id']==kb]
        for thread in threads:
            rt.checkpointer.delete_thread(thread['id'])
        return rt.rag.delete_knowledge_base(kb)


@app.get('/api/knowledge-bases/{kb}/documents')
def documents(kb: str,request: Request):
    owned_kb(request,kb)
    return get_store().list_documents(kb)


@app.post('/api/knowledge-bases/{kb}/documents',status_code=201)
def upload(kb: str,request: Request,file: UploadFile=File(...)):
    owned_kb(request,kb)
    rt = get_runtime()
    name = Path((file.filename or '').replace('\\','/')).name
    if Path(name).suffix.lower() not in {'.pdf','.docx','.md','.markdown','.txt'}:
        raise HTTPException(422,'请选择 PDF、DOCX、Markdown 或 TXT 文件')
    directory = rt.settings.upload_dir/kb/uuid.uuid4().hex
    directory.mkdir(parents=True,exist_ok=True)
    destination = directory/name
    try:
        size = 0
        with destination.open('xb') as output:
            while chunk := file.file.read(1024*1024):
                size += len(chunk)
                if size>50*1024*1024:
                    raise HTTPException(413,'单个文件不能超过 50 MB')
                output.write(chunk)
        with rt.mutation_lock:
            result = rt.rag.ingest(destination,kb).to_dict()
        return result
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()


@app.delete('/api/knowledge-bases/{kb}/documents/{doc}')
def delete_document(kb: str,doc: str,request: Request):
    owned_kb(request,kb)
    rt = get_runtime()
    with rt.mutation_lock:
        return rt.rag.delete_document(kb,doc)


@app.post('/api/knowledge-bases/{kb}/documents/{doc}/reindex')
def reindex(kb: str,doc: str,request: Request):
    owned_kb(request,kb)
    rt = get_runtime()
    with rt.mutation_lock:
        return rt.rag.reindex(kb,doc).to_dict()


@app.get('/api/knowledge-bases/{kb}/documents/{doc}/pages/{page}')
def page_content(kb: str,doc: str,page: int,request: Request):
    owned_kb(request,kb)
    record = get_store().get_document(kb,doc)
    if not record:
        raise HTTPException(404,'文档不存在')
    pages = load_document(record['file_path'])
    matches = [p for p in pages if p.metadata['page']==page]
    if not matches:
        raise HTTPException(404,'页面不存在')
    return {'source':record['filename'],'page':page,'content':matches[0].page_content}


@app.get('/api/knowledge-bases/{kb}/graph')
def graph_data(kb: str,request: Request):
    root = owned_kb(request,kb)
    nodes = [dict(id=kb,label=root['name'],kind='knowledge_base')]
    edges = []
    for doc in get_store().list_documents(kb):
        nodes.append(dict(id=doc['id'],label=doc['filename'],kind='document',pages=doc['page_count'],chunks=doc['chunk_count']))
        edges.append(dict(source=kb,target=doc['id'],relation='包含'))
    return {'nodes':nodes,'edges':edges,'kind':'document_structure',
            'description':'文档结构关系；选择文档展开页面，不表示实体语义或因果关系'}


@app.post('/api/conversations',status_code=201)
def new_conversation(payload: ConversationCreate,request: Request):
    return get_store().new_conversation(request.state.user['id'],payload.knowledge_base_id,payload.title.strip() or '新会话')


@app.get('/api/conversations')
def conversations(request: Request):
    return get_store().conversations(request.state.user['id'])


@app.get('/api/conversations/{thread}/messages')
def history(thread: str,request: Request):
    get_store().require_conversation(thread,request.state.user['id'])
    return get_store().history(thread)


@app.patch('/api/conversations/{thread}')
def rename(thread: str,payload: Rename,request: Request):
    get_store().require_conversation(thread,request.state.user['id'])
    get_store().rename_conversation(thread,payload.title.strip() or '新会话')
    return {'ok':True}


@app.delete('/api/conversations/{thread}')
def delete_conversation(thread: str,request: Request):
    get_store().require_conversation(thread,request.state.user['id'])
    rt = get_runtime()
    rt.store.require_conversation(thread,request.state.user['id'])
    with rt.mutation_lock:
        rt.checkpointer.delete_thread(thread)
        rt.store.remove_conversation(thread)
    return {'ok':True}


def reserve(payload, request):
    store = get_store()
    owner = request.state.user['id']
    conv = store.require_conversation(payload.thread_id,owner)
    if conv['knowledge_base_id']!=payload.knowledge_base_id:
        raise HTTPException(409,'会话绑定的知识库不能更改，请新建会话')
    if not payload.question.strip():
        raise HTTPException(422,'问题不能为空')
    if not store.acquire(payload.thread_id,owner):
        raise HTTPException(409,'当前会话仍在生成，请稍后重试')
    return owner


def ask(payload, owner, callback=None, token_callback=None, approval_callback=None):
    store = get_store()
    started = time.monotonic()
    try:
        rt = get_runtime()
        with rt.mutation_lock:
            store.require_conversation(payload.thread_id,owner)
            result = rt.agent.ask(payload.question,payload.knowledge_base_id,payload.thread_id,
                                  allow_web=payload.allow_web,on_event=callback,
                                  on_token=token_callback,
                                  on_web_approval=approval_callback)
            result['duration_seconds'] = round(time.monotonic()-started,2)
            store.record_turn(payload.thread_id,payload.question,result)
            return result
    finally:
        store.release(payload.thread_id)


@app.post('/api/chat')
def chat(payload: ChatRequest,request: Request):
    return ask(payload,reserve(payload,request))


@app.post('/api/chat/approvals/{approval_id}')
def decide_web_search(approval_id: str,payload: WebApprovalDecision,request: Request):
    with approval_lock:
        approval = approval_requests.get(approval_id)
        if not approval or approval['owner'] != request.state.user['id']:
            raise HTTPException(404,'联网授权请求不存在或已过期')
        approval['accepted'] = payload.accepted
        approval['event'].set()
    return {'accepted':payload.accepted}


@app.post('/api/chat/stream')
async def stream(payload: ChatRequest,request: Request):
    owner = await asyncio.to_thread(reserve,payload,request)
    queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    def publish_status(item):
        loop.call_soon_threadsafe(queue.put_nowait,('status',item))
    def publish_token(text):
        loop.call_soon_threadsafe(queue.put_nowait,('token',{'text':text}))
    def request_web_approval(query,provider):
        approval_id = uuid.uuid4().hex
        gate = Event()
        approval = {'owner':owner,'event':gate,'accepted':None}
        with approval_lock:
            approval_requests[approval_id] = approval
        loop.call_soon_threadsafe(queue.put_nowait,('approval',{
            'approval_id':approval_id,'query':query,'provider':provider,
            'timeout_seconds':60,
        }))
        gate.wait(timeout=60)
        with approval_lock:
            approval_requests.pop(approval_id,None)
        return approval['accepted'] is True
    async def run():
        try:
            result = await asyncio.to_thread(
                ask,payload,owner,publish_status,publish_token,request_web_approval
            )
            await queue.put(('result',result))
        except Exception as error:
            logger.error('Chat failed: %s',type(error).__name__)
            await queue.put(('error',{'detail':'生成失败，请检查模型连接后重试；问题已保留在输入框'}))
        finally:
            await queue.put(None)
    task = asyncio.create_task(run())
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    async def events():
        yield 'event: status\ndata: {"stage":"queued","detail":"请求已接收，等待处理"}\n\n'
        while True:
            try:
                item = await asyncio.wait_for(queue.get(),timeout=15)
            except asyncio.TimeoutError:
                yield ': heartbeat\n\n'
                continue
            if item is None:
                break
            name,data = item
            yield 'event: '+name+'\ndata: '+json.dumps(data,ensure_ascii=False)+'\n\n'
    return StreamingResponse(events(),media_type='text/event-stream',
                             headers={'X-Accel-Buffering':'no','Cache-Control':'no-cache'})


@app.post('/api/knowledge-bases/{kb}/notes',status_code=201)
def save_note(kb: str,payload: NoteCreate,request: Request):
    owned_kb(request,kb)
    if not payload.title.strip() or not payload.content.strip():
        raise HTTPException(422,'笔记标题和内容不能为空')
    return get_runtime().notes.save(kb,payload.title.strip(),payload.content.strip())


@app.get('/api/knowledge-bases/{kb}/notes')
def notes(kb: str,request: Request,query: str=''):
    owned_kb(request,kb)
    memory = get_runtime().notes
    return memory.search(query[:1500],kb,top_k=10) if query.strip() else memory.list(kb)


@app.delete('/api/knowledge-bases/{kb}/notes/{note}')
def delete_note(kb: str,note: str,request: Request):
    owned_kb(request,kb)
    if not get_runtime().notes.delete(kb,note):
        raise HTTPException(404,'笔记不存在')
    return {'ok':True}
