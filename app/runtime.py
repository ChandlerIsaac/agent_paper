"""Lazy construction of application services."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import sqlite3
from threading import RLock
from langgraph.checkpoint.sqlite import SqliteSaver

from app.agent.model import get_chat_model
from app.agent.workflow import ResearchAgent, build_research_graph
from app.core.config import PROJECT_ROOT, Settings, get_settings
from app.memory.workspace import WorkspaceStore
from app.memory.notes import NoteMemory
from app.agent.web import make_web_search
from app.rag.embeddings import get_embeddings
from app.rag.service import RAGService
from app.rag.sparse_store import SparseBM25Store
from app.rag.vector_store import MilvusVectorStore
from app.citations.service import CitationGraphService
from app.citations.store import CitationStore


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


@dataclass(frozen=True)
class Runtime:
    settings: Settings
    store: WorkspaceStore
    rag: RAGService
    agent: ResearchAgent
    notes: NoteMemory
    checkpointer: SqliteSaver
    connection: sqlite3.Connection
    vectors: MilvusVectorStore
    sparse: SparseBM25Store
    citations: CitationGraphService
    mutation_lock: RLock


_initialization_lock = RLock()


@lru_cache(maxsize=1)
def _cached_store() -> WorkspaceStore:
    return WorkspaceStore(resolve_project_path(get_settings().database_path))


def get_store() -> WorkspaceStore:
    with _initialization_lock:
        return _cached_store()


@lru_cache(maxsize=1)
def get_citation_store() -> CitationStore:
    return CitationStore(resolve_project_path(get_settings().database_path))


@lru_cache(maxsize=1)
def _cached_runtime() -> Runtime:
    """Build and cache the local MVP runtime."""

    settings = get_settings()
    settings.upload_dir = resolve_project_path(settings.upload_dir)
    settings.database_path = resolve_project_path(settings.database_path)
    settings.milvus_lite_path = resolve_project_path(settings.milvus_lite_path)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.milvus_lite_path.parent.mkdir(parents=True, exist_ok=True)

    store = get_store()
    vector_store = MilvusVectorStore(settings, get_embeddings())
    sparse_store = SparseBM25Store(settings.database_path)
    rag = RAGService(settings, store, vector_store, sparse_store)
    citations = CitationGraphService(
        settings.database_path,vector_store,sparse_store,
        timeout=settings.web_search_timeout,document_store=store,
    )
    connection = sqlite3.connect(str(settings.database_path.with_name('checkpoints.sqlite3')),check_same_thread=False)
    saver = SqliteSaver(connection)
    saver.setup()
    notes = NoteMemory(store,get_embeddings(),settings.embedding_model+'@'+settings.embedding_model_revision+':mean700-v1')
    graph = build_research_graph(rag,get_chat_model(),checkpointer=saver,notes=notes,
                                 web_search=make_web_search(settings),citation_store=citations.store)
    return Runtime(
        settings=settings,
        store=store,
        rag=rag,
        agent=ResearchAgent(graph),
        notes=notes,
        checkpointer=saver,
        connection=connection,
        vectors=vector_store,
        sparse=sparse_store,
        citations=citations,
        mutation_lock=RLock(),
    )


def get_runtime() -> Runtime:
    # lru_cache alone may call the constructor twice on concurrent first requests.
    with _initialization_lock:
        return _cached_runtime()


get_runtime.cache_info = _cached_runtime.cache_info
get_runtime.cache_clear = _cached_runtime.cache_clear
