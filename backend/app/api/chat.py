from fastapi import APIRouter, HTTPException
from app.config.settings import get_settings
from app.models.schemas import ChatRequest, ChatResponse
from app.rag.chat import answer
from app.llm.ollama import OllamaError
router = APIRouter(prefix="/api")

@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    try:
        return answer(request, get_settings())
    except (OllamaError, FileNotFoundError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
