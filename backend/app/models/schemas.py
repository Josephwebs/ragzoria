from typing import Literal
from pydantic import BaseModel, Field, field_validator

class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=6000)

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1500)
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

class ChatResponse(BaseModel):
    answer: str
    used_rag: bool
    sources: list[Source] = Field(default_factory=list)
