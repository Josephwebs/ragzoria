import pytest
import httpx
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from app.main import app
from app.rag import chat as flow
from app.llm import ollama

client = TestClient(app)

@pytest.mark.parametrize("message", ["hola", "gracias", "entiendo"])
def test_chat_without_retrieval(monkeypatch, message):
    replies = iter(["CHAT", "Hola, en que puedo ayudarte?"])
    monkeypatch.setattr(flow, "chat", lambda *a, **k: next(replies))
    monkeypatch.setattr(flow, "retrieve", lambda *a: pytest.fail("CHAT must not retrieve"))
    result = client.post("/api/chat", json={"message": message})
    assert result.status_code == 200
    assert result.json()["used_rag"] is False
    assert result.json()["sources"] == []

@pytest.mark.parametrize("message", [
    "Necesito acceso al servidor de produccion",
    "El lunes entra Camila como analista contable",
    "Denle a Juan los mismos permisos que Pedro",
    "Solo lectura hasta el viernes",
    "Cual es la politica TI sobre computacion cuantica",
])
def test_rag_contract_and_history(monkeypatch, message):
    seen = []
    def fake_chat(settings, system, prompt, **kwargs):
        seen.append(prompt)
        return "RAG" if len(seen) == 1 else "Respuesta basada en el contexto."
    def retrieve(query, settings):
        assert "servidor" in query
        return [(Document(page_content="Solicitar aprobacion y minimo privilegio.",
            metadata=dict(source="policy.md", tipo_fuente="internal", categoria="TI", seccion="Acceso")), 0.4)]
    monkeypatch.setattr(flow, "chat", fake_chat)
    monkeypatch.setattr(flow, "retrieve", retrieve)
    response = client.post("/api/chat", json={"message": message, "history": [
        {"role": "user", "content": "Necesito acceso al servidor"},
        {"role": "assistant", "content": "Que permiso necesitas?"}
    ]})
    assert response.status_code == 200
    assert response.json()["used_rag"]
    assert response.json()["sources"][0]["fragment"].startswith("Solicitar")
    assert "Que permiso necesitas?" in seen[0]
    assert "<contexto>" in seen[1] and "minimo privilegio" in seen[1]

def test_ollama_offline(monkeypatch):
    def offline(*a, **k):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(ollama.httpx, "post", offline)
    result = client.post("/api/chat", json={"message": "hola"})
    assert result.status_code == 503
    assert "ollama serve" in result.json()["detail"]

def test_invalid_decision(monkeypatch):
    monkeypatch.setattr(flow, "chat", lambda *a, **k: "MAYBE")
    assert client.post("/api/chat", json={"message": "hola"}).status_code == 503

def test_invalid_input():
    assert client.post("/api/chat", json={"message": " "}).status_code == 422
    assert client.post("/api/chat", json={"message": "hola", "history": [
        {"role": "user", "content": "x"} for _ in range(7)
    ]}).status_code == 422
