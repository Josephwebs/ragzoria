import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document

from app.agent import graph as agent_graph
from app.agent import tools as agent_tools
from app.agent.memory import DatabaseError
from app.agent.state import AgentDecision, Plan
from app.llm import ollama
from app.main import app


client = TestClient(app)


def fake_plan_or_decision(decision_factory):
    def fake(settings, system, prompt, schema):
        if schema is Plan:
            return Plan(steps=["Comprender la solicitud.", "Responder al usuario."])
        return decision_factory(prompt)
    return fake


@pytest.mark.parametrize("message", ["hola", "gracias", "entiendo"])
def test_greeting_does_not_use_tools(monkeypatch, message):
    monkeypatch.setattr(
        agent_graph,
        "structured_chat",
        fake_plan_or_decision(
            lambda prompt: AgentDecision(action="respond", answer="Hola, ¿en que puedo ayudarte?")
        ),
    )
    monkeypatch.setattr(
        agent_tools, "retrieve", lambda *args: pytest.fail("Un saludo no debe buscar documentos")
    )
    result = client.post("/api/chat", json={"message": message, "thread_id": f"hello-{message}"})
    assert result.status_code == 200
    assert result.json()["used_rag"] is False
    assert result.json()["sources"] == []
    assert result.json()["tools_used"] == []
    assert len(result.json()["plan"]) == 2


def test_rag_contract_returns_evidence(monkeypatch):
    def decide(prompt):
        if "resultado_tool:buscar_documentacion" in prompt:
            return AgentDecision(action="ask_user", question="¿Cual es el servidor exacto?")
        return AgentDecision(action="search_documentation", query="acceso servidor produccion")

    monkeypatch.setattr(agent_graph, "structured_chat", fake_plan_or_decision(decide))
    monkeypatch.setattr(
        agent_tools,
        "retrieve",
        lambda query, settings: [(
            Document(
                page_content="Se requiere servidor, duracion y justificacion.",
                metadata={
                    "source": "policy.md",
                    "tipo_fuente": "internal",
                    "categoria": "TI",
                    "seccion": "Acceso",
                },
            ),
            0.4,
        )],
    )
    response = client.post("/api/chat", json={
        "message": "Necesito acceso a produccion",
        "thread_id": "rag-contract",
        "user_id": "ana",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["used_rag"] is True
    assert data["tools_used"] == ["buscar_documentacion"]
    assert data["sources"][0]["fragment"].startswith("Se requiere")
    assert data["answer"].startswith("¿Cual")


def test_ollama_offline(monkeypatch):
    def offline(*args, **kwargs):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(ollama.httpx, "post", offline)
    result = client.post("/api/chat", json={"message": "hola", "thread_id": "offline"})
    assert result.status_code == 503
    assert "ollama serve" in result.json()["detail"]


def test_invalid_structured_json_is_rejected(monkeypatch):
    monkeypatch.setattr(ollama, "chat", lambda *args, **kwargs: "no es json")
    with pytest.raises(ollama.OllamaError, match="decision valida"):
        ollama.structured_chat(None, "system", "prompt", Plan)


def test_invalid_input():
    assert client.post("/api/chat", json={"message": " "}).status_code == 422
    assert client.post("/api/chat", json={"message": "hola", "confirmation": "maybe"}).status_code == 422


def test_confirmation_without_pending_action_is_rejected_without_write(monkeypatch):
    monkeypatch.setattr(
        agent_graph,
        "structured_chat",
        fake_plan_or_decision(lambda prompt: AgentDecision(action="respond", answer="No aplica")),
    )
    response = client.post("/api/chat", json={
        "message": "Confirmar ticket",
        "thread_id": "without-pending",
        "user_id": "ana",
        "confirmation": "confirm",
    })
    assert response.status_code == 200
    assert response.json()["needs_confirmation"] is False
    assert "No hay una accion pendiente" in response.json()["answer"]


def test_database_error_has_controlled_http_response(monkeypatch):
    def fail(*args, **kwargs):
        raise DatabaseError("Base local no disponible.")

    monkeypatch.setattr("app.api.chat.run_agent", fail)
    response = client.post("/api/chat", json={"message": "hola", "thread_id": "db-error"})
    assert response.status_code == 503
    assert response.json()["detail"] == "La persistencia local no esta disponible temporalmente."
