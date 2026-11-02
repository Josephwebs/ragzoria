import json

import httpx
from pydantic import BaseModel, ValidationError

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

def chat(settings, system, prompt, temperature=0.1, response_format=None):
    payload = {
        "model": settings.ollama_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "stream": False, "options": {"temperature": temperature},
    }
    if response_format is not None:
        payload["format"] = response_format
    data = post(settings, "/api/chat", payload)
    answer = data.get("message", {}).get("content", "").strip()
    if not answer:
        raise OllamaError("Ollama devolvio una respuesta vacia.")
    return answer


def structured_chat(settings, system, prompt, schema: type[BaseModel]):
    """Request JSON from Ollama and validate it without requiring native tool calling."""
    raw = chat(
        settings,
        system,
        prompt,
        temperature=0,
        response_format=schema.model_json_schema(),
    )
    try:
        return schema.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise OllamaError(
            f"Ollama no devolvio una decision valida para {schema.__name__}."
        ) from exc
