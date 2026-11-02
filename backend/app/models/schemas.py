from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator

class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=6000)

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1500)
    thread_id: Optional[str] = Field(default=None, min_length=1, max_length=100)
    user_id: str = Field(default="demo-user", min_length=1, max_length=100)
    confirmation: Optional[Literal["confirm", "cancel"]] = None
    # Kept temporarily for backwards-compatible clients; LangGraph owns context now.
    history: list[Message] = Field(default_factory=list, max_length=6)

    @field_validator("message")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("El mensaje no puede estar vacio.")
        return value.strip()

class Source(BaseModel):
    source: str
    tipo_fuente: str
    categoria: str
    seccion: str
    fragment: str

class PendingAction(BaseModel):
    id: str
    type: Literal["create_ticket"]
    summary: str
    details: str
    status: Literal["pending"]
    created_at: str
    expires_at: str

class ChatResponse(BaseModel):
    answer: str
    thread_id: str
    used_rag: bool
    plan: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    needs_confirmation: bool = False
    pending_action: Optional[PendingAction] = None
    activity: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
