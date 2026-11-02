from uuid import uuid4

from fastapi import APIRouter, HTTPException
from langgraph.errors import GraphRecursionError

from app.agent.graph import run_agent
from app.agent.memory import DatabaseError, PendingActionError
from app.models.schemas import ChatRequest, ChatResponse, Source
from app.llm.ollama import OllamaError
router = APIRouter(prefix="/api")

@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    thread_id = request.thread_id or str(uuid4())
    try:
        result = run_agent(
            request.message, thread_id, request.user_id, request.confirmation
        )
        sources = [
            Source(**{key: value for key, value in item.items() if key != "score"})
            for item in result.get("sources", [])
        ]
        pending = result.get("pending_action")
        return ChatResponse(
            answer=result.get("final_answer", ""),
            thread_id=thread_id,
            used_rag=bool(sources),
            plan=result.get("plan", []),
            sources=sources,
            needs_confirmation=bool(pending),
            pending_action=pending,
            activity=result.get("activity", []),
            tools_used=result.get("tools_used", []),
        )
    except (OllamaError, FileNotFoundError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PendingActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(
            status_code=503,
            detail="La persistencia local no esta disponible temporalmente.",
        ) from exc
    except GraphRecursionError as exc:
        raise HTTPException(
            status_code=500,
            detail="El agente alcanzo su limite de pasos sin resolver la solicitud.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
