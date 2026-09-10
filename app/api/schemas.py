"""HTTP request and response schemas."""

from typing import Any

from pydantic import BaseModel, Field


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ChatRequest(BaseModel):
    knowledge_base_id: str
    question: str = Field(min_length=1, max_length=8000)
    thread_id: str = Field(min_length=1, max_length=100)
    allow_web: bool = False


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20000)


class ChatResponse(BaseModel):
    answer: str
    citations: list[dict[str, Any]]
    trace: list[dict[str, Any]] = Field(default_factory=list)
    duration_seconds: float | None = None
    usage: dict[str, Any] | None = None


class WebApprovalDecision(BaseModel):
    accepted: bool


class Credentials(BaseModel):
    username: str = Field(min_length=3,max_length=40,pattern=r"^[a-zA-Z0-9_\-]+$")
    password: str = Field(min_length=10,max_length=128)


class ConversationCreate(BaseModel):
    knowledge_base_id: str
    title: str = Field(default="新会话",min_length=1,max_length=100)


class Rename(BaseModel):
    title: str = Field(min_length=1,max_length=100)
