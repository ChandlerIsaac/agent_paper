"""State schema for the ResearchMate LangGraph workflow."""

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    knowledge_base_id: str
    query: str
    retry_count: int
    evidence: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    answer: str
    allow_web: bool
    sufficient: bool
    web_query: str
    notes: list[dict[str, Any]]
    web_results: list[dict[str, Any]]
    trace: list[dict[str, Any]]
