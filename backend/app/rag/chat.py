from app.llm.ollama import chat, OllamaError
from app.models.schemas import ChatResponse, Source
from app.prompts import DECISION, SYSTEM, CHAT_SYSTEM, RAG_PROMPT
from app.retrievers.faiss_retriever import retrieve

def history_text(history):
    return "\n".join(f"{item.role}: {item.content}" for item in history[-6:])

def needs_rag(message, history, settings):
    decision = chat(settings, DECISION,
                    f"<historial>{history_text(history)}</historial>\n"
                    f"<mensaje>{message}</mensaje>", temperature=0)
    if decision not in {"CHAT", "RAG"}:
        raise OllamaError("Ollama debe responder CHAT o RAG en la decision.")
    return decision == "RAG"

def answer(request, settings):
    used_rag = needs_rag(request.message, request.history, settings)
    sources = []
    if used_rag:
        # Recent user turns give follow-ups context without business-specific rules.
        query = "\n".join([m.content for m in request.history[-6:] if m.role == "user"]
                          + [request.message])
        pairs = retrieve(query, settings)
        sources = [Source(**doc.metadata, fragment=doc.page_content) for doc, _ in pairs]
    context = "\n\n".join(
        f"[{i}] {s.source} / {s.seccion}\n{s.fragment}"
        for i, s in enumerate(sources, 1)
    )
    prompt = RAG_PROMPT.format(
        context=context or "Sin contexto documental disponible.",
        history=history_text(request.history), message=request.message,
    )
    return ChatResponse(answer=chat(settings, SYSTEM if used_rag else CHAT_SYSTEM, prompt),
                        used_rag=used_rag, sources=sources)
