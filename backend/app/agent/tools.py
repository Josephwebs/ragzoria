from __future__ import annotations

import logging
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.memory import confirm_pending_action, find_tickets
from app.config.settings import get_settings
from app.retrievers.faiss_retriever import retrieve

logger = logging.getLogger("ragzor.tools")


@tool
def buscar_documentacion(query: str) -> dict:
    """Busca politicas y procedimientos TI en FAISS y devuelve los dos mejores chunks."""
    try:
        pairs = retrieve(query, get_settings())
    except FileNotFoundError:
        logger.exception("document_index_missing")
        return {
            "status": "error",
            "error_code": "index_missing",
            "message": "El indice documental no esta disponible.",
            "query": query,
            "sources": [],
        }
    except Exception:
        logger.exception("document_retrieval_failed")
        return {
            "status": "error",
            "error_code": "retrieval_error",
            "message": "La recuperacion documental fallo temporalmente.",
            "query": query,
            "sources": [],
        }
    sources = [
        {
            **doc.metadata,
            "fragment": doc.page_content,
            "score": float(score),
        }
        for doc, score in pairs
    ]
    return {
        "status": "ok" if sources else "empty",
        "query": query,
        "sources": sources,
    }


class ConsultarTicketInput(BaseModel):
    user_id: str = Field(min_length=1, max_length=100)
    ticket_id: Optional[int] = Field(default=None, ge=1)


class CrearTicketInput(BaseModel):
    action_id: str = Field(min_length=1, max_length=100)
    thread_id: str = Field(min_length=1, max_length=100)
    user_id: str = Field(min_length=1, max_length=100)


@tool(args_schema=ConsultarTicketInput)
def consultar_ticket(user_id: str, ticket_id: Optional[int] = None) -> dict:
    """Consulta tickets locales por identificador o usuario. Es una operacion de solo lectura."""
    return {"tickets": find_tickets(get_settings().database_path, ticket_id, user_id)}


@tool(args_schema=CrearTicketInput)
def crear_ticket(action_id: str, thread_id: str, user_id: str) -> dict:
    """Consume una accion pendiente confirmada y crea como maximo un ticket local."""
    ticket, created = confirm_pending_action(
        get_settings().database_path, action_id, thread_id, user_id
    )
    return {"ticket": ticket, "created": created}


TOOLS = [buscar_documentacion, consultar_ticket, crear_ticket]
