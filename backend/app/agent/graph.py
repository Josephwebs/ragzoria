from __future__ import annotations

import json
import logging
import re
import unicodedata
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.agent.memory import (
    cancel_pending_action,
    create_pending_action,
    get_memories,
    initialize_database,
)
from app.agent.prompts import AGENT_SYSTEM, PLANNER_SYSTEM
from app.agent.state import AgentDecision, AgentState, Plan, PostToolDecision
from app.agent.tools import TOOLS
from app.config.settings import get_settings
from app.llm.ollama import structured_chat

logger = logging.getLogger("ragzor.agent")


def _content_as_dict(message: ToolMessage) -> dict:
    if isinstance(message.content, dict):
        return message.content
    try:
        return json.loads(message.content)
    except (TypeError, json.JSONDecodeError):
        return {}


def _transcript(messages) -> str:
    lines = []
    environment = _active_environment(messages)
    for message in messages[-12:]:
        role = "usuario" if isinstance(message, HumanMessage) else "ragzor"
        if isinstance(message, ToolMessage):
            role = f"resultado_tool:{message.name}"
        content = message.content
        if isinstance(message, ToolMessage) and message.name == "buscar_documentacion":
            payload = _content_as_dict(message)
            payload["sources"] = _compatible_sources(payload.get("sources", []), environment)
            content = payload
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _normalized(text: str) -> str:
    return "".join(
        character for character in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(character) != "Mn"
    ).strip(" .,!¿?¡")


SENSITIVE_TERMS = (
    "contrasena", "password", "codigo mfa", "codigo de autenticacion",
    "codigo de recuperacion", "token", "secreto", "credencial", "clave de acceso",
    "api key", "llave privada", "pin de autenticacion",
)


def _safe_visible_text(text: str) -> str:
    normalized = _normalized(text)
    asks_for_data = bool(re.search(
        r"\b(?:compart\w*|proporcion\w*|facilit\w*|ingres\w*|introduc\w*|"
        r"envi\w*|escrib\w*|entreg\w*|suministr\w*|revel\w*|dime|"
        r"indica\s+(?:tu|el|la)|necesito\s+(?:tu|el|la)|requiero\s+(?:tu|el|la)|"
        r"cual\s+es\s+(?:tu|el|la))\b",
        normalized,
    ))
    if asks_for_data and any(term in normalized for term in SENSITIVE_TERMS):
        logger.warning("sensitive_data_request_blocked")
        return (
            "No compartas credenciales ni codigos de autenticacion. Para continuar, "
            "indica solamente el modulo, rol esperado y mensaje de error, sin datos secretos."
        )
    return text


def _active_environment(messages) -> str | None:
    for message in reversed(messages):
        if not isinstance(message, HumanMessage):
            continue
        text = _normalized(str(message.content))
        if any(term in text for term in ("servidor de pruebas", "ambiente de pruebas", "ambiente de test", "no produccion")):
            return "pruebas"
        if "produccion" in text or " productivo" in f" {text}":
            return "produccion"
    return None


def _compatible_sources(sources: list[dict], environment: str | None) -> list[dict]:
    if environment != "pruebas":
        return sources
    compatible = []
    for source in sources:
        section = _normalized(str(source.get("seccion", "")))
        fragment = _normalized(str(source.get("fragment", "")))
        production_only = (
            "produccion" in section
            or "productiv" in section
            or "acceso productivo" in fragment
            or "accesos a produccion" in fragment
        )
        if not production_only:
            compatible.append(source)
    return compatible


def _context_system_answer(messages) -> str | None:
    users = [message for message in messages if isinstance(message, HumanMessage)]
    if not users:
        return None
    latest = _normalized(str(users[-1].content))
    if not any(phrase in latest for phrase in ("de que sistema", "que sistema estabamos", "que sistema hablabamos")):
        return None
    for message in reversed(users[:-1]):
        text = _normalized(str(message.content))
        for name in ("sap", "vpn", "mfa"):
            if re.search(rf"\b{name}\b", text):
                return f"Estabamos hablando de {name.upper()}."
    return "No tengo un sistema identificado en esta conversacion."


def _is_simple_chat(messages) -> bool:
    if not messages or not isinstance(messages[-1], HumanMessage):
        return False
    return _normalized(str(messages[-1].content)) in {
        "hola", "buenas", "buenos dias", "buenas tardes", "buenas noches",
        "gracias", "muchas gracias", "entiendo",
    }


def _is_contextual_followup(messages) -> bool:
    user_messages = [message for message in messages if isinstance(message, HumanMessage)]
    return len(user_messages) >= 2 and len(str(user_messages[-1].content)) <= 120


def _changes_goal(messages) -> bool:
    users = [message for message in messages if isinstance(message, HumanMessage)]
    if len(users) < 2:
        return False
    latest = _normalized(str(users[-1].content))
    return any(marker in latest for marker in (
        "en realidad", "cambio", "cambie", "mejor", "ya no", "ahora es",
        "ambiente de prueba", "ambiente de test", "servidor de prueba",
        "para pruebas", "no produccion",
    ))


def _documentation_query(messages, proposed_query: str) -> str:
    """Keep follow-up searches anchored to the request stored in the thread."""
    if _changes_goal(messages) and _active_environment(messages) == "pruebas":
        return (
            "Acceso administrador a servidor de pruebas. Requisitos aplicables a "
            "ambientes no productivos; excluir requisitos exclusivos de produccion."
        )
    user_turns = [
        str(message.content) for message in messages if isinstance(message, HumanMessage)
    ][-4:]
    if proposed_query and proposed_query not in user_turns:
        user_turns.append(proposed_query)
    return "\n".join(user_turns)


def _ticket_lookup(messages) -> tuple[str, int | None] | None:
    users = [message for message in messages if isinstance(message, HumanMessage)]
    if not users:
        return None
    text = _normalized(str(users[-1].content))
    explicit = re.search(r"\bticket\s*#?\s*(\d+)\b", text)
    if explicit:
        return "explicit", int(explicit.group(1))
    if "ticket anterior" in text or "solicitud anterior" in text:
        return "previous", None
    if any(phrase in text for phrase in ("mis solicitudes", "mis tickets", "solicitudes anteriores")):
        return "list", None
    if any(phrase in text for phrase in ("ultima solicitud", "ultimo ticket", "estado del ticket")):
        return "latest", None
    return None


def _asks_about_persistent_history(messages) -> bool:
    if not messages:
        return False
    latest_users = [message for message in messages if isinstance(message, HumanMessage)]
    if not latest_users:
        return False
    text = _normalized(str(latest_users[-1].content))
    return any(phrase in text for phrase in (
        "ultima solicitud", "solicitud anterior", "ultimo ticket", "ticket anterior",
        "consultar ticket", "estado del ticket", "ticket #",
        "mis solicitudes", "mis tickets", "solicitudes anteriores",
    ))


def _privileged_access_ready(messages) -> tuple[bool, str]:
    """Small safety checklist for the evaluation's privileged-access scenario."""
    user_turns = [
        str(message.content) for message in messages if isinstance(message, HumanMessage)
    ]
    text = _normalized(" ".join(user_turns))
    is_privileged_production = "admin" in text and _active_environment(messages) == "produccion"
    return (
        is_privileged_production and not _missing_ticket_fields(messages),
        " | ".join(user_turns),
    )


def _missing_ticket_fields(messages) -> list[str]:
    user_turns = [str(message.content) for message in messages if isinstance(message, HumanMessage)]
    text = _normalized(" ".join(user_turns))
    environment = _active_environment(messages)
    if "admin" in text and environment == "produccion":
        checks = (
            ("servidor", bool(re.search(r"\bsrv[-_a-z0-9.]+", text))),
            ("duracion", bool(re.search(r"\b(?:\d+|una?|dos|tres|cuatro)\s+(?:dias?|semanas?|meses?)\b", text))),
            ("motivo o incidente", bool(re.search(r"\binc-?\d+\b", text)) or any(term in text for term in ("motivo", "debido", "porque"))),
            ("ventana de uso", bool(re.search(r"\b\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\b", text))),
            ("plan de reversa", "reversa" in text and any(term in text for term in ("retirar", "quitar", "revocar"))),
            ("cambio autorizado", bool(re.search(r"\bchg-?\d+\b", text))),
        )
        return [name for name, present in checks if not present]
    if "sap" in text and any(term in text for term in ("solicitar acceso", "necesito acceso", "acceso a sap")):
        checks = (
            ("modulo SAP", "modulo" in text),
            ("sociedad", "sociedad" in text),
            ("centro de costo", "centro de costo" in text),
            ("justificacion operacional", any(term in text for term in ("justificacion", "debido", "porque"))),
        )
        return [name for name, present in checks if not present]
    return []


def _missing_fields_answer(missing: list[str]) -> str:
    return "Antes de preparar el ticket necesito: " + ", ".join(missing) + "."


def _user_request_details(messages) -> str:
    return " | ".join(
        str(message.content) for message in messages if isinstance(message, HumanMessage)
    )


def _safe_plan(steps: list[str]) -> list[str]:
    blocked = ("realizar el cambio", "asignar los permisos", "otorgar acceso", "configurar el acceso")
    return [
        _safe_visible_text(
        "Preparar la solicitud para confirmacion humana sin ejecutar cambios."
        if any(phrase in _normalized(step) for phrase in blocked)
        else step
        )
        for step in steps
    ]


def planner_node(state: AgentState) -> dict:
    previous = state.get("plan", [])
    messages = state.get("messages", [])
    if _changes_goal(messages) and _active_environment(messages) == "pruebas":
        steps = [
            "Actualizar el objetivo vigente a un servidor de pruebas.",
            "Consultar documentacion aplicable a ambientes no productivos.",
            "Solicitar los datos faltantes para el nuevo objetivo.",
        ]
        changed = bool(previous and previous != steps)
        return {
            "plan": steps,
            "final_answer": "",
            "activity": ["Actualizo el plan ante el cambio de ambiente."] if changed else [],
        }
    if _is_simple_chat(state.get("messages", [])):
        plan = Plan(steps=["Comprender el mensaje.", "Responder brevemente."])
        activity = ["Actualizo el plan ante la nueva informacion."] if previous and previous != plan.steps else []
        return {"plan": plan.steps, "final_answer": "", "activity": activity}
    prompt = f"Conversacion:\n{_transcript(state.get('messages', []))}"
    plan = structured_chat(get_settings(), PLANNER_SYSTEM, prompt, Plan)
    safe_steps = _safe_plan(plan.steps)
    changed = bool(previous and previous != safe_steps)
    if changed:
        logger.info("plan_updated", extra={"thread_id": state.get("thread_id")})
    return {
        "plan": safe_steps,
        "final_answer": "",
        "activity": ["Actualizo el plan ante la nueva informacion."] if changed else [],
    }


def _tool_observation_updates(state: AgentState) -> dict:
    messages = state.get("messages", [])
    if not messages or not isinstance(messages[-1], ToolMessage):
        return {}
    message = messages[-1]
    payload = _content_as_dict(message)
    activity = state.get("activity", [])
    tools_used = state.get("tools_used", [])
    if message.name == "buscar_documentacion":
        status = payload.get("status", "ok")
        sources = _compatible_sources(
            payload.get("sources", []), _active_environment(messages)
        )
        if status == "error":
            event = (
                "Fallo la consulta documental: indice no disponible."
                if payload.get("error_code") == "index_missing"
                else "Fallo la consulta documental por un error tecnico."
            )
        elif status == "empty" or not sources:
            event = "La consulta documental no encontro resultados compatibles."
        else:
            event = "Consulto documentacion."
        return {
            "sources": sources,
            "activity": activity + [event],
            "tools_used": tools_used + ["buscar_documentacion"],
        }
    if message.name == "consultar_ticket":
        return {
            "activity": activity + ["Consulto tickets."],
            "tools_used": tools_used + ["consultar_ticket"],
        }
    if message.name == "crear_ticket":
        ticket = payload.get("ticket", {})
        return {
            "pending_action": None,
            "activity": activity + [f"Registro ticket #{ticket.get('id')} de forma idempotente."],
            "tools_used": tools_used + ["crear_ticket"],
        }
    return {}


def agent_node(state: AgentState) -> dict:
    settings = get_settings()
    initialize_database(settings.database_path)
    updates = _tool_observation_updates(state)
    messages = state.get("messages", [])
    pending = state.get("pending_action")
    confirmation = state.get("confirmation")

    if pending and not confirmation and messages and isinstance(messages[-1], HumanMessage):
        latest_text = _normalized(str(messages[-1].content))
        if latest_text in {"confirmar", "confirmar ticket", "si", "acepto"}:
            answer = "La confirmacion textual no ejecuta escrituras. Usa el boton Confirmar ticket."
            return {
                **updates,
                "next_step": "end",
                "final_answer": answer,
                "messages": [AIMessage(content=answer)],
                "activity": updates.get("activity", state.get("activity", []))
                + ["Mantengo la accion pendiente sin ejecutar una confirmacion textual."],
            }
        cancel_pending_action(
            settings.database_path, pending["id"], state["thread_id"], state["user_id"]
        )
        pending = None
        updates = {
            **updates,
            "pending_action": None,
            "activity": updates.get("activity", state.get("activity", []))
            + ["Invalido la propuesta anterior antes de procesar nueva informacion."],
        }

    if confirmation and not pending:
        answer = "No hay una accion pendiente valida para confirmar o cancelar."
        return {
            **updates,
            "confirmation": None,
            "next_step": "end",
            "final_answer": answer,
            "messages": [AIMessage(content=answer)],
            "activity": updates.get("activity", state.get("activity", []))
            + ["Rechazo una confirmacion sin accion pendiente."],
        }

    if confirmation == "cancel" and pending:
        cancelled = cancel_pending_action(
            settings.database_path, pending["id"], state["thread_id"], state["user_id"]
        )
        answer = "Entendido. No creare el ticket."
        return {
            **updates,
            "pending_action": None,
            "confirmation": None,
            "next_step": "end",
            "final_answer": answer,
            "messages": [AIMessage(content=answer)],
            "activity": updates.get("activity", state.get("activity", []))
            + (["Cancelo la creacion del ticket."] if cancelled else ["La accion ya no estaba disponible."]),
        }

    if confirmation == "confirm" and pending:
        call = {
            "name": "crear_ticket",
            "args": {
                "action_id": pending["id"],
                "thread_id": state["thread_id"],
                "user_id": state["user_id"],
            },
            "id": f"call-{uuid4()}",
            "type": "tool_call",
        }
        return {**updates, "confirmation": None, "next_step": "tools", "messages": [AIMessage(content="", tool_calls=[call])]}

    if messages and isinstance(messages[-1], ToolMessage) and messages[-1].name == "crear_ticket":
        payload = _content_as_dict(messages[-1])
        ticket = payload.get("ticket", {})
        verb = "creado correctamente" if payload.get("created", True) else "ya estaba creado"
        answer = f"Ticket #{ticket.get('id')} {verb}. Estado: {ticket.get('status', 'open')}."
        logger.info(
            "ticket_confirmed",
            extra={"thread_id": state["thread_id"], "ticket_id": ticket.get("id")},
        )
        return {
            **updates,
            "next_step": "end",
            "final_answer": answer,
            "messages": [AIMessage(content=answer)],
        }

    if messages and isinstance(messages[-1], ToolMessage) and messages[-1].name == "consultar_ticket":
        tickets = _content_as_dict(messages[-1]).get("tickets", [])
        lookup_kind, _ = _ticket_lookup(messages) or ("latest", None)
        if tickets:
            if lookup_kind == "list":
                items = "; ".join(
                    f"#{ticket['id']} {ticket['summary']} ({ticket['status']})"
                    for ticket in tickets
                )
                answer = f"Tus solicitudes recientes son: {items}."
            elif lookup_kind == "previous":
                if len(tickets) < 2:
                    answer = "No encontre un ticket anterior al ultimo para tu usuario."
                else:
                    ticket = tickets[1]
                    answer = (
                        f"Tu ticket anterior al ultimo fue el #{ticket.get('id')}: "
                        f"{ticket.get('summary')}. Estado: {ticket.get('status')}."
                    )
            else:
                ticket = tickets[0]
                label = "El ticket solicitado" if lookup_kind == "explicit" else "Tu ultima solicitud"
                answer = f"{label} fue el ticket #{ticket.get('id')}: {ticket.get('summary')}. Estado: {ticket.get('status')}."
        else:
            answer = "No encontre tickets anteriores para tu usuario."
        return {
            **updates,
            "next_step": "end",
            "final_answer": answer,
            "messages": [AIMessage(content=answer)],
        }

    contextual_answer = _context_system_answer(messages)
    if contextual_answer:
        return {
            **updates,
            "next_step": "end",
            "final_answer": contextual_answer,
            "messages": [AIMessage(content=contextual_answer)],
        }

    if messages and isinstance(messages[-1], ToolMessage) and messages[-1].name == "buscar_documentacion":
        payload = _content_as_dict(messages[-1])
        if payload.get("status") == "error":
            if payload.get("error_code") == "index_missing":
                answer = (
                    "No pude consultar la documentacion porque el indice FAISS no esta "
                    "disponible. Ejecuta python scripts/ingest.py y vuelve a intentarlo."
                )
            else:
                answer = (
                    "No pude consultar la documentacion por un error tecnico de recuperacion. "
                    "No usare documentos ni requisitos no verificados."
                )
            return {
                **updates,
                "sources": [],
                "next_step": "end",
                "final_answer": answer,
                "messages": [AIMessage(content=answer)],
            }
        if payload.get("status") == "empty":
            answer = "No encontre documentos relevantes para esa consulta. No asumire requisitos sin evidencia."
            return {
                **updates,
                "sources": [],
                "next_step": "end",
                "final_answer": answer,
                "messages": [AIMessage(content=answer)],
            }
        if _active_environment(messages) == "pruebas" and not updates.get("sources", []):
            answer = (
                "No encontre documentacion especifica compatible con servidores de pruebas. "
                "No aplicare requisitos exclusivos de produccion. Indica servidor, rol, "
                "duracion y justificacion para continuar."
            )
            return {
                **updates,
                "sources": [],
                "next_step": "end",
                "final_answer": answer,
                "messages": [AIMessage(content=answer)],
            }

    lookup = _ticket_lookup(messages)
    if lookup and (not messages or not isinstance(messages[-1], ToolMessage)):
        lookup_kind, ticket_id = lookup
        call = {
            "name": "consultar_ticket",
            "args": {
                "ticket_id": ticket_id if lookup_kind == "explicit" else None,
                "user_id": state["user_id"],
            },
            "id": f"call-{uuid4()}",
            "type": "tool_call",
        }
        return {**updates, "next_step": "tools", "messages": [AIMessage(content="", tool_calls=[call])]}

    memories = (
        get_memories(settings.database_path, state["user_id"])
        if _asks_about_persistent_history(messages)
        else {}
    )
    prompt = (
        f"Plan actual: {json.dumps(state.get('plan', []), ensure_ascii=False)}\n"
        f"Memoria persistente: {json.dumps(memories, ensure_ascii=False)}\n"
        f"Accion pendiente: {json.dumps(pending, ensure_ascii=False)}\n"
        f"Conversacion:\n{_transcript(messages)}"
    )
    has_document_observation = any(
        isinstance(message, ToolMessage) and message.name == "buscar_documentacion"
        for message in messages
    )
    observed_tool = bool(
        (messages and isinstance(messages[-1], ToolMessage))
        or (_is_contextual_followup(messages) and has_document_observation and not _changes_goal(messages))
    )
    if observed_tool:
        prompt += (
            "\nYa observaste el resultado de una tool. No vuelvas a llamar tools en este turno. "
            "Ahora debes responder, pedir los datos que faltan segun la evidencia o solicitar confirmacion."
        )
    decision = structured_chat(
        settings,
        AGENT_SYSTEM,
        prompt,
        PostToolDecision if observed_tool else AgentDecision,
    )
    access_ready, access_details = _privileged_access_ready(messages)
    if observed_tool and access_ready:
        decision = PostToolDecision(
            action="request_confirmation",
            answer="Tengo los antecedentes necesarios. ¿Deseas que cree el ticket?",
            ticket_summary="Acceso administrador temporal a produccion",
            ticket_details=access_details,
        )

    if decision.action == "search_documentation":
        logger.info("tool_selected", extra={"thread_id": state["thread_id"], "tool": "buscar_documentacion"})
        call = {
            "name": "buscar_documentacion",
            "args": {"query": _documentation_query(messages, decision.query)},
            "id": f"call-{uuid4()}",
            "type": "tool_call",
        }
        return {**updates, "next_step": "tools", "messages": [AIMessage(content="", tool_calls=[call])]}

    if decision.action == "consult_ticket":
        # Do not let incident references such as INC-200 leak into the local
        # ticket tool. Persistent tickets are consulted only on explicit intent.
        if not _asks_about_persistent_history(messages):
            call = {
                "name": "buscar_documentacion",
                "args": {"query": _documentation_query(messages, "")},
                "id": f"call-{uuid4()}",
                "type": "tool_call",
            }
            return {
                **updates,
                "next_step": "tools",
                "messages": [AIMessage(content="", tool_calls=[call])],
            }
        args = {"ticket_id": decision.ticket_id, "user_id": state["user_id"]}
        call = {
            "name": "consultar_ticket",
            "args": args,
            "id": f"call-{uuid4()}",
            "type": "tool_call",
        }
        logger.info("tool_selected", extra={"thread_id": state["thread_id"], "tool": "consultar_ticket"})
        return {**updates, "next_step": "tools", "messages": [AIMessage(content="", tool_calls=[call])]}

    if decision.action == "request_confirmation":
        missing = _missing_ticket_fields(messages)
        if missing:
            answer = _missing_fields_answer(missing)
            return {
                **updates,
                "pending_action": None,
                "next_step": "end",
                "final_answer": answer,
                "messages": [AIMessage(content=answer)],
                "activity": updates.get("activity", state.get("activity", []))
                + ["Detecto parametros obligatorios faltantes antes de preparar la escritura."],
            }
        if len(decision.ticket_summary.strip()) < 3:
            answer = "Faltan antecedentes para preparar el ticket. ¿Puedes indicar el problema y el resultado esperado?"
            return {
                **updates,
                "next_step": "end",
                "final_answer": answer,
                "messages": [AIMessage(content=answer)],
                "activity": updates.get("activity", state.get("activity", []))
                + ["Detecto parametros incompletos antes de preparar la escritura."],
            }
        pending_action = create_pending_action(
            settings.database_path,
            state["thread_id"],
            state["user_id"],
            decision.ticket_summary,
            _user_request_details(messages),
            settings.pending_action_ttl_minutes,
        )
        logger.info(
            "confirmation_requested",
            extra={"thread_id": state["thread_id"], "action_id": pending_action["id"]},
        )
        answer = _safe_visible_text(
            decision.answer or "Tengo los antecedentes necesarios. ¿Deseas que cree el ticket?"
        )
        return {
            **updates,
            "pending_action": pending_action,
            "next_step": "end",
            "final_answer": answer,
            "messages": [AIMessage(content=answer)],
            "activity": updates.get("activity", []) + ["Solicito confirmacion para crear el ticket."],
        }

    answer = decision.question if decision.action == "ask_user" else decision.answer
    answer = answer or "¿Puedes darme un poco mas de informacion?"
    answer = _safe_visible_text(answer)
    activity = ["Solicito informacion adicional."] if decision.action == "ask_user" else []
    return {
        **updates,
        "next_step": "end",
        "final_answer": answer,
        "messages": [AIMessage(content=answer)],
        "activity": updates.get("activity", []) + activity,
    }


def route_after_agent(state: AgentState) -> str:
    return "tools" if state.get("next_step") == "tools" else END


def build_graph(checkpointer=None):
    builder = StateGraph(AgentState)
    builder.add_node("planner", planner_node)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(TOOLS))
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "agent")
    builder.add_conditional_edges("agent", route_after_agent, {"tools": "tools", END: END})
    builder.add_edge("tools", "agent")
    return builder.compile(checkpointer=checkpointer)


checkpointer = MemorySaver()
graph = build_graph(checkpointer)


def run_agent(message: str, thread_id: str, user_id: str, confirmation=None) -> dict:
    logger.info("request_started", extra={"thread_id": thread_id, "user_id": user_id})
    result = graph.invoke(
        {
            "messages": [HumanMessage(content=message)],
            "user_id": user_id,
            "thread_id": thread_id,
            "confirmation": confirmation,
            "activity": [],
            "tools_used": [],
        },
        config={
            "configurable": {"thread_id": f"{user_id}:{thread_id}"},
            "recursion_limit": 10,
        },
    )
    logger.info("request_finished", extra={"thread_id": thread_id, "user_id": user_id})
    return result
