from uuid import uuid4

import pytest
from langchain_core.documents import Document

from app.agent import graph as graph_module
from app.agent import tools as tools_module
from app.agent.graph import build_graph
from app.agent.memory import (
    DatabaseError,
    PendingActionError,
    cancel_pending_action,
    confirm_pending_action,
    connect,
    create_pending_action,
    find_tickets,
    get_memories,
    get_pending_action,
    initialize_database,
    insert_ticket,
)
from app.agent.state import AgentDecision, Plan
from app.config.settings import Settings


def configure_agent(monkeypatch, tmp_path, decision_factory):
    settings = Settings(database_path=tmp_path / "ragzor.db", faiss_persist_dir=tmp_path / "faiss")
    monkeypatch.setattr(graph_module, "get_settings", lambda: settings)
    monkeypatch.setattr(tools_module, "get_settings", lambda: settings)

    def structured(settings, system, prompt, schema):
        if schema is Plan:
            return Plan(steps=["Revisar la solicitud.", "Decidir el siguiente paso."])
        return decision_factory(prompt)

    monkeypatch.setattr(graph_module, "structured_chat", structured)
    return settings


def test_graph_compiles():
    assert build_graph() is not None


def test_document_search_tool_reuses_retriever(monkeypatch):
    document = Document(
        page_content="Politica recuperada",
        metadata={"source": "p.md", "tipo_fuente": "internal", "categoria": "TI", "seccion": "Acceso"},
    )
    monkeypatch.setattr(tools_module, "retrieve", lambda query, settings: [(document, 0.25)])
    result = tools_module.buscar_documentacion.invoke({"query": "acceso"})
    assert result["sources"][0]["fragment"] == "Politica recuperada"
    assert result["sources"][0]["score"] == 0.25


def test_short_term_memory_keeps_previous_turn(monkeypatch, tmp_path):
    prompts = []

    def decide(prompt):
        prompts.append(prompt)
        return AgentDecision(action="ask_user", question="¿Puedes precisar el dato?")

    configure_agent(monkeypatch, tmp_path, decide)
    thread_id = f"memory-{uuid4()}"
    graph_module.run_agent("Necesito acceso a produccion", thread_id, "ana")
    graph_module.run_agent("Dos semanas", thread_id, "ana")
    assert "Necesito acceso a produccion" in prompts[-1]
    assert "Dos semanas" in prompts[-1]


def test_ticket_requires_confirmation_and_persists_memory(monkeypatch, tmp_path):
    def decide(prompt):
        return AgentDecision(
            action="request_confirmation",
            answer="Tengo los antecedentes necesarios. ¿Deseas que cree el ticket?",
            ticket_summary="Acceso temporal a produccion",
            ticket_details="Acceso administrador por dos semanas debido a INC-200.",
        )

    settings = configure_agent(monkeypatch, tmp_path, decide)
    thread_id = f"confirm-{uuid4()}"
    first = graph_module.run_agent(
        "Necesito acceso administrador por dos semanas debido a INC-200", thread_id, "ana"
    )
    assert first["pending_action"]["type"] == "create_ticket"
    assert find_tickets(settings.database_path, user_id="ana") == []

    second = graph_module.run_agent("Confirmar ticket", thread_id, "ana", "confirm")
    tickets = find_tickets(settings.database_path, user_id="ana")
    assert len(tickets) == 1
    assert f"Ticket #{tickets[0]['id']} creado" in second["final_answer"]
    memories = get_memories(settings.database_path, "ana")
    assert memories["last_ticket_id"] == str(tickets[0]["id"])
    assert memories["last_request_summary"] == "Acceso temporal a produccion"


def test_text_only_confirmation_never_writes(monkeypatch, tmp_path):
    def decide(prompt):
        return AgentDecision(
            action="request_confirmation",
            answer="¿Deseas crear el ticket?",
            ticket_summary="Acceso temporal",
            ticket_details="Acceso de lectura por siete dias",
        )

    settings = configure_agent(monkeypatch, tmp_path, decide)
    thread = f"text-confirm-{uuid4()}"
    first = graph_module.run_agent("Necesito acceso", thread, "ana")
    second = graph_module.run_agent("Confirmar ticket", thread, "ana")
    assert first["pending_action"]["id"] == second["pending_action"]["id"]
    assert "confirmacion textual no ejecuta" in second["final_answer"]
    assert find_tickets(settings.database_path, user_id="ana") == []


def test_create_ticket_tool_rejects_write_without_pending_action(monkeypatch, tmp_path):
    settings = Settings(database_path=tmp_path / "ragzor.db")
    monkeypatch.setattr(tools_module, "get_settings", lambda: settings)
    initialize_database(settings.database_path)
    with pytest.raises(ValueError):
        tools_module.crear_ticket.invoke({
            "user_id": "ana", "summary": "Prueba", "details": "Detalle", "confirmed": False
        })
    assert find_tickets(settings.database_path, user_id="ana") == []


def test_long_term_memory_can_drive_ticket_lookup(monkeypatch, tmp_path):
    seen = []

    def decide(prompt):
        seen.append(prompt)
        if "resultado_tool:consultar_ticket" in prompt:
            return AgentDecision(action="respond", answer="Tu ultima solicitud fue acceso temporal.")
        return AgentDecision(action="consult_ticket", ticket_id=1)

    settings = configure_agent(monkeypatch, tmp_path, decide)
    insert_ticket(settings.database_path, "ana", "Acceso temporal", "Dos semanas")
    result = graph_module.run_agent("¿Cual fue mi ultima solicitud?", f"new-{uuid4()}", "ana")
    assert result["final_answer"].startswith("Tu ultima")


def test_ticket_query_enforces_owner(tmp_path):
    database = tmp_path / "ragzor.db"
    ticket = insert_ticket(database, "ana", "Acceso SAP", "Rol de lectura")
    assert find_tickets(database, ticket_id=ticket["id"], user_id="ana")
    assert find_tickets(database, ticket_id=ticket["id"], user_id="bob") == []
    assert find_tickets(database, ticket_id=ticket["id"], user_id=None) == []


def test_pending_action_is_bound_and_confirmation_is_idempotent(tmp_path):
    database = tmp_path / "ragzor.db"
    pending = create_pending_action(
        database, "thread-a", "ana", "Acceso VPN", "Acceso por siete dias"
    )
    with pytest.raises(PendingActionError, match="no pertenece"):
        confirm_pending_action(database, pending["id"], "thread-b", "ana")
    with pytest.raises(PendingActionError, match="no pertenece"):
        confirm_pending_action(database, pending["id"], "thread-a", "bob")

    first, created_first = confirm_pending_action(
        database, pending["id"], "thread-a", "ana"
    )
    second, created_second = confirm_pending_action(
        database, pending["id"], "thread-a", "ana"
    )
    assert created_first is True
    assert created_second is False
    assert first["id"] == second["id"]
    assert len(find_tickets(database, user_id="ana")) == 1


def test_pending_action_cancel_expire_and_replace(tmp_path):
    database = tmp_path / "ragzor.db"
    first = create_pending_action(
        database, "thread-a", "ana", "Acceso SAP", "Rol temporal de lectura"
    )
    second = create_pending_action(
        database, "thread-a", "ana", "Acceso VPN", "Acceso temporal remoto"
    )
    assert get_pending_action(database, first["id"], "thread-a", "ana")["status"] == "cancelled"
    assert cancel_pending_action(database, second["id"], "thread-a", "ana") is True
    with pytest.raises(PendingActionError, match="cancelled"):
        confirm_pending_action(database, second["id"], "thread-a", "ana")

    expired = create_pending_action(
        database, "thread-a", "ana", "Acceso ERP", "Acceso temporal de pruebas"
    )
    with connect(database) as connection:
        connection.execute(
            "UPDATE pending_actions SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
            (expired["id"],),
        )
    with pytest.raises(PendingActionError, match="expiro"):
        confirm_pending_action(database, expired["id"], "thread-a", "ana")
    assert get_pending_action(database, expired["id"], "thread-a", "ana")["status"] == "expired"


def test_change_of_goal_allows_a_new_document_search(monkeypatch, tmp_path):
    settings = Settings(database_path=tmp_path / "ragzor.db", faiss_persist_dir=tmp_path / "faiss")
    monkeypatch.setattr(graph_module, "get_settings", lambda: settings)
    monkeypatch.setattr(tools_module, "get_settings", lambda: settings)
    searches = []
    monkeypatch.setattr(
        tools_module,
        "retrieve",
        lambda query, settings: searches.append(query) or [
            (Document(page_content="Politica", metadata={"source": "p.md"}), 0.2)
        ],
    )

    def structured(settings, system, prompt, schema):
        if schema is Plan:
            if "ambiente de prueba" in prompt:
                return Plan(steps=["Revisar alcance actualizado.", "Consultar politica de pruebas."])
            return Plan(steps=["Consultar politica de produccion.", "Revisar requisitos."])
        if schema.__name__ == "PostToolDecision":
            return graph_module.PostToolDecision(action="ask_user", question="¿Que rol necesitas?")
        return AgentDecision(action="search_documentation", query="acceso actualizado")

    monkeypatch.setattr(graph_module, "structured_chat", structured)
    thread = f"replan-{uuid4()}"
    graph_module.run_agent("Necesito acceso a produccion", thread, "ana")
    changed = graph_module.run_agent(
        "En realidad cambio a ambiente de prueba", thread, "ana"
    )
    assert len(searches) == 2
    assert "Actualizo el plan" in " ".join(changed["activity"])


def test_threads_are_isolated_by_user_even_with_same_client_thread(monkeypatch, tmp_path):
    prompts = []

    def decide(prompt):
        prompts.append(prompt)
        return AgentDecision(action="ask_user", question="¿Puedes precisar?")

    configure_agent(monkeypatch, tmp_path, decide)
    shared_thread = f"shared-{uuid4()}"
    graph_module.run_agent("Secreto de Ana", shared_thread, "ana")
    graph_module.run_agent("Consulta de Bob", shared_thread, "bob")
    assert "Secreto de Ana" not in prompts[-1]
    assert "Consulta de Bob" in prompts[-1]


def test_multiple_requests_remain_available(tmp_path):
    database = tmp_path / "ragzor.db"
    first = insert_ticket(database, "ana", "Acceso SAP", "Rol de lectura")
    second = insert_ticket(database, "ana", "Acceso VPN", "Acceso remoto")
    tickets = find_tickets(database, user_id="ana")
    assert [ticket["id"] for ticket in tickets] == [second["id"], first["id"]]
    assert {ticket["summary"] for ticket in tickets} == {"Acceso SAP", "Acceso VPN"}


def test_agent_never_requests_credentials_even_if_model_does(monkeypatch, tmp_path):
    def decide(prompt):
        return AgentDecision(
            action="ask_user",
            question="Comparte tu usuario, contraseña, token y código MFA para continuar.",
        )

    configure_agent(monkeypatch, tmp_path, decide)
    result = graph_module.run_agent(
        "No puedo entrar a SAP", f"credentials-{uuid4()}", "ana"
    )
    answer = result["final_answer"].lower()
    assert "no compartas credenciales" in answer
    assert "contraseña" not in answer
    assert "token" not in answer
    informative = "La politica requiere MFA para accesos de alto riesgo."
    assert graph_module._safe_visible_text(informative) == informative


def test_incomplete_privileged_request_cannot_create_pending_action(monkeypatch, tmp_path):
    def decide(prompt):
        return AgentDecision(
            action="request_confirmation",
            answer="¿Confirmas el ticket?",
            ticket_summary="Acceso administrador a produccion",
            ticket_details="Datos supuestamente completos inventados por el modelo.",
        )

    configure_agent(monkeypatch, tmp_path, decide)
    result = graph_module.run_agent(
        "Necesito acceso administrador a produccion por dos semanas",
        f"incomplete-{uuid4()}",
        "ana",
    )
    assert result.get("pending_action") is None
    assert "servidor" in result["final_answer"]
    assert "cambio autorizado" in result["final_answer"]


def test_replan_discards_production_only_evidence(monkeypatch, tmp_path):
    settings = Settings(database_path=tmp_path / "ragzor.db", faiss_persist_dir=tmp_path / "faiss")
    monkeypatch.setattr(graph_module, "get_settings", lambda: settings)
    monkeypatch.setattr(tools_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        tools_module,
        "retrieve",
        lambda query, settings: [(
            Document(
                page_content="Accesos a produccion requieren CHG.",
                metadata={"source": "prod.md", "seccion": "Produccion"},
            ),
            0.1,
        )],
    )

    def structured(settings, system, prompt, schema):
        if schema is Plan:
            return Plan(steps=["Consultar politica.", "Revisar requisitos."])
        if schema.__name__ == "PostToolDecision":
            return graph_module.PostToolDecision(action="ask_user", question="¿Que servidor?")
        return AgentDecision(action="search_documentation", query="acceso")

    monkeypatch.setattr(graph_module, "structured_chat", structured)
    thread = f"replan-filter-{uuid4()}"
    graph_module.run_agent("Necesito acceso administrador a produccion", thread, "ana")
    changed = graph_module.run_agent(
        "En realidad lo necesito para un servidor de pruebas", thread, "ana"
    )
    assert changed["sources"] == []
    assert "no aplicare requisitos exclusivos de produccion" in changed["final_answer"].lower()
    assert any("Actualizo el plan" in item for item in changed["activity"])


def test_ticket_anterior_selects_second_newest(monkeypatch, tmp_path):
    settings = configure_agent(
        monkeypatch,
        tmp_path,
        lambda prompt: pytest.fail("La consulta determinista no debe depender del LLM"),
    )
    older = insert_ticket(settings.database_path, "ana", "Ticket anterior", "Detalle uno")
    newer = insert_ticket(settings.database_path, "ana", "Ticket ultimo", "Detalle dos")
    result = graph_module.run_agent(
        "¿Que estado tiene el ticket anterior?", f"previous-{uuid4()}", "ana"
    )
    assert f"#{older['id']}" in result["final_answer"]
    assert f"#{newer['id']}" not in result["final_answer"]


def test_invalid_sqlite_path_raises_sanitized_database_error():
    with pytest.raises(DatabaseError) as captured:
        initialize_database("/dev/null/ragzor.db")
    assert str(captured.value) == "No fue posible abrir la base de datos local."
    assert "/dev/null" not in str(captured.value)


def test_missing_faiss_index_is_reported_without_fabricated_sources(monkeypatch, tmp_path):
    def decide(prompt):
        return AgentDecision(action="search_documentation", query="politica interna")

    configure_agent(monkeypatch, tmp_path, decide)
    monkeypatch.setattr(
        tools_module,
        "retrieve",
        lambda query, settings: (_ for _ in ()).throw(FileNotFoundError("ruta interna")),
    )
    result = graph_module.run_agent(
        "Consulta la politica interna", f"missing-faiss-{uuid4()}", "ana"
    )
    assert result["sources"] == []
    assert "indice faiss no esta disponible" in result["final_answer"].lower()
    assert "ruta interna" not in result["final_answer"]
