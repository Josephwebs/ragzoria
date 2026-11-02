from __future__ import annotations

from typing import Annotated, Literal, Optional, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class Plan(BaseModel):
    steps: list[Annotated[str, Field(min_length=3, max_length=240)]] = Field(
        min_length=2, max_length=4
    )


class AgentDecision(BaseModel):
    action: Literal[
        "respond",
        "search_documentation",
        "consult_ticket",
        "ask_user",
        "request_confirmation",
    ]
    answer: str = Field(default="", max_length=1500)
    query: str = Field(default="", max_length=1500)
    ticket_id: Optional[int] = None
    question: str = Field(default="", max_length=1500)
    ticket_summary: str = Field(default="", max_length=200)
    ticket_details: str = Field(default="", max_length=4000)


class PostToolDecision(BaseModel):
    """Decision allowed after observing a tool; prevents repeated tool loops."""
    action: Literal["respond", "ask_user", "request_confirmation"]
    answer: str = Field(default="", max_length=1500)
    question: str = Field(default="", max_length=1500)
    ticket_summary: str = Field(default="", max_length=200)
    ticket_details: str = Field(default="", max_length=4000)


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    user_id: str
    thread_id: str
    plan: list[str]
    sources: list[dict]
    pending_action: Optional[dict]
    final_answer: str
    activity: list[str]
    tools_used: list[str]
    confirmation: Optional[Literal["confirm", "cancel"]]
    next_step: str
