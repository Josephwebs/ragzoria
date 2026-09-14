from app.llm.ollama import chat, OllamaError
from app.models.schemas import ChatResponse, Source
from app.prompts import DECISION, SYSTEM, CHAT_SYSTEM, RAG_PROMPT
from app.retrievers.faiss_retriever import retrieve

def debug_log(settings, title, value):
    if settings.rag_debug:
        line = "=" * 78
        print(f"\n{line}\n[RAG DEBUG] {title}\n{line}\n{value}\n{line}\n", flush=True)

def sources_summary(pairs):
    return "\n".join(
        f"{i}. documento={doc.metadata.get('source')} | "
        f"seccion={doc.metadata.get('seccion')} | "
        f"tipo={doc.metadata.get('tipo_fuente')} | "
        f"categoria={doc.metadata.get('categoria')} | "
        f"score={score}"
        for i, (doc, score) in enumerate(pairs, 1)
    )

def redacted_prompt(prompt, sources):
    context_summary = "\n".join(
        f"[{i}] {source.source} / {source.seccion} / {source.tipo_fuente}"
        for i, source in enumerate(sources, 1)
    ) or "Sin contexto documental disponible."
    start = prompt.find("<contexto>")
    end = prompt.find("</contexto>")
    if start == -1 or end == -1:
        return prompt
    return (
        prompt[:start]
        + "<contexto>\n"
        + context_summary
        + "\n</contexto>"
        + prompt[end + len("</contexto>"):]
    )

def history_text(history):
    return "\n".join(f"{item.role}: {item.content}" for item in history[-6:])

def needs_rag(message, history, settings):
    decision = chat(settings, DECISION,
                    f"<historial>{history_text(history)}</historial>\n"
                    f"<mensaje>{message}</mensaje>", temperature=0)
    if decision not in {"CHAT", "RAG"}:
        raise OllamaError("Ollama debe responder CHAT o RAG en la decision.")
    debug_log(settings, "decision", decision)
    return decision == "RAG"

def answer(request, settings):
    used_rag = needs_rag(request.message, request.history, settings)
    sources = []
    if used_rag:
        # Recent user turns give follow-ups context without business-specific rules.
        query = "\n".join([m.content for m in request.history[-6:] if m.role == "user"]
                          + [request.message])
        debug_log(settings, "1. QUERY USADA PARA BUSCAR EN FAISS", query)
        pairs = retrieve(query, settings)
        debug_log(settings, "2. DOCUMENTOS RECUPERADOS", sources_summary(pairs))
        sources = [Source(**doc.metadata, fragment=doc.page_content) for doc, _ in pairs]
    context = "\n\n".join(
        f"[{i}] {s.source} / {s.seccion}\n{s.fragment}"
        for i, s in enumerate(sources, 1)
    )
    prompt = RAG_PROMPT.format(
        context=context or "Sin contexto documental disponible.",
        history=history_text(request.history), message=request.message,
    )
    if used_rag:
        debug_log(settings, "3. PROMPT ENVIADO A OLLAMA (CONTEXTO RESUMIDO)", redacted_prompt(prompt, sources))
    return ChatResponse(answer=chat(settings, SYSTEM if used_rag else CHAT_SYSTEM, prompt),
                        used_rag=used_rag, sources=sources)
