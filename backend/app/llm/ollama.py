import httpx

class OllamaError(RuntimeError):
    pass

def post(settings, path, payload):
    try:
        response = httpx.post(settings.ollama_base_url.rstrip("/") + path,
                              json=payload, timeout=settings.ollama_timeout)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OllamaError(
            f"No se pudo consultar Ollama en {settings.ollama_base_url}. "
            f"Revisa ollama serve y ollama pull {payload.get('model')}."
        ) from exc

def chat(settings, system, prompt, temperature=0.1):
    data = post(settings, "/api/chat", {
        "model": settings.ollama_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "stream": False, "options": {"temperature": temperature},
    })
    answer = data.get("message", {}).get("content", "").strip()
    if not answer:
        raise OllamaError("Ollama devolvio una respuesta vacia.")
    return answer
