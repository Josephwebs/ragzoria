"""Validacion real de Ragzor EP2 contra un backend y SQLite aislados."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.memory import (  # noqa: E402
    PendingActionError,
    cancel_pending_action,
    confirm_pending_action,
    connect,
    create_pending_action,
    find_tickets,
    get_pending_action,
    initialize_database,
    insert_ticket,
)

API = os.environ.get("RAGZOR_QA_API", "http://127.0.0.1:8001")
DATABASE = Path(os.environ["DATABASE_PATH"])
OUTPUT = ROOT / "evaluation/e2e_results.json"
results: list[dict[str, Any]] = []


def post(message: str, thread: str, user: str, confirmation: str | None = None) -> dict:
    payload: dict[str, Any] = {"message": message, "thread_id": thread, "user_id": user}
    if confirmation:
        payload["confirmation"] = confirmation
    response = httpx.post(f"{API}/api/chat", json=payload, timeout=180)
    body = response.json()
    body["_http_status"] = response.status_code
    return body


def add(test_id: str, scenario: str, passed: bool, evidence: Any, expected: str) -> None:
    results.append({
        "id": test_id,
        "scenario": scenario,
        "expected": expected,
        "status": "PASS" if passed else "FAIL",
        "evidence": evidence,
    })


def ticket_count(user: str) -> int:
    return len(find_tickets(DATABASE, user_id=user))


def complete_request(server: str, incident: str, change: str) -> str:
    return (
        f"Necesito acceso administrador a produccion en {server} por dos semanas "
        f"debido a {incident}, ventana 18:00-20:00, cambio {change} y el plan "
        "de reversa es retirar el rol."
    )


def main() -> None:
    initialize_database(DATABASE)

    greeting = post("Hola Ragzor, ¿qué puedes hacer?", "qa-01", "qa-greeting")
    add("TEST-01", "Saludo normal", greeting["_http_status"] == 200
        and not greeting["used_rag"] and not greeting["needs_confirmation"]
        and not greeting["activity"], greeting,
        "Respuesta coherente sin tools, RAG, tickets ni confirmacion.")

    vpn = post("¿Cómo configuro la VPN corporativa?", "qa-02", "qa-vpn")
    vpn_sources = [source.get("source") for source in vpn.get("sources", [])]
    add("TEST-02", "Consulta documental VPN", vpn["_http_status"] == 200
        and vpn["used_rag"] and "manual_vpn.md" in vpn_sources
        and "Consulto documentacion." in vpn["activity"], vpn,
        "Usar buscar_documentacion y citar contenido real de VPN.")

    sap = post("¿Qué requisitos necesito para solicitar acceso a SAP?", "qa-03", "qa-sap")
    sap_sources = [source.get("source") for source in sap.get("sources", [])]
    add("TEST-03", "Consulta documental SAP", sap["_http_status"] == 200
        and sap["used_rag"] and "procedimiento_acceso_sap.md" in sap_sources,
        sap, "Recuperar requisitos desde procedimiento_acceso_sap.md.")

    incomplete = post("Necesito acceso administrador", "qa-04", "qa-incomplete")
    add("TEST-04", "Informacion insuficiente", incomplete["_http_status"] == 200
        and ticket_count("qa-incomplete") == 0 and not incomplete["needs_confirmation"],
        incomplete, "Preguntar datos faltantes sin crear ticket ni inventar datos.")

    multi_messages = [
        "Necesito acceso administrador a producción",
        "Por dos semanas",
        "El servidor es srv-pagos-01",
        "Es por el incidente INC-200",
    ]
    multi_responses = [post(message, "qa-05", "qa-multi") for message in multi_messages]
    last_multi = multi_responses[-1]
    add("TEST-05", "Conversacion de varios turnos", all(r["_http_status"] == 200 for r in multi_responses)
        and ticket_count("qa-multi") == 0
        and not any(response["needs_confirmation"] for response in multi_responses),
        {"messages": multi_messages, "responses": multi_responses},
        "Conservar produccion, duracion, servidor e incidente; pedir solo datos restantes.")

    replan_first = post("Necesito acceso administrador a producción", "qa-06", "qa-replan")
    replan_second = post(
        "En realidad lo necesito para un servidor de pruebas", "qa-06", "qa-replan"
    )
    replan_sections = {source.get("seccion", "") for source in replan_second.get("sources", [])}
    add("TEST-06", "Replanificacion", replan_second["_http_status"] == 200
        and replan_first["plan"] != replan_second["plan"]
        and any("Actualizo el plan" in item for item in replan_second["activity"])
        and any("consulta documental" in item.lower() or "Consulto documentacion" in item
                for item in replan_second["activity"])
        and not replan_sections.intersection({"Produccion", "Ambientes productivos"}),
        {"initial": replan_first, "updated": replan_second},
        "Cambiar plan y ejecutar nueva busqueda al pasar de produccion a pruebas.")

    before_create = ticket_count("qa-create")
    prepared = post(complete_request("srv-qa-01", "INC-701", "CHG-701"), "qa-07", "qa-create")
    between_create = ticket_count("qa-create")
    confirmed = post("Confirmar ticket", "qa-07", "qa-create", "confirm")
    after_create = ticket_count("qa-create")
    add("TEST-07", "Creacion de ticket", prepared["needs_confirmation"]
        and before_create == between_create == 0 and after_create == 1
        and "Ticket #" in confirmed["answer"],
        {"before": before_create, "prepared": prepared, "between": between_create,
         "confirmed": confirmed, "after": after_create},
        "No escribir antes de confirmar y crear exactamente un ticket al confirmar.")

    before_cancel = ticket_count("qa-cancel")
    cancel_prepared = post(complete_request("srv-qa-02", "INC-702", "CHG-702"), "qa-08", "qa-cancel")
    action_id = cancel_prepared.get("pending_action", {}).get("id")
    cancelled = post("Cancelar ticket", "qa-08", "qa-cancel", "cancel")
    cancel_status = get_pending_action(DATABASE, action_id, "qa-08", "qa-cancel") if action_id else None
    cancel_retry = post("Confirmar ticket", "qa-08", "qa-cancel", "confirm")
    after_cancel = ticket_count("qa-cancel")
    add("TEST-08", "Cancelacion", before_cancel == after_cancel == 0
        and cancel_status and cancel_status["status"] == "cancelled"
        and not cancel_retry["needs_confirmation"],
        {"prepared": cancel_prepared, "cancelled": cancelled,
         "pending_row": cancel_status, "retry": cancel_retry, "tickets": after_cancel},
        "Cancelar invalida la accion y una confirmacion posterior no escribe.")

    duplicate_prepared = post(
        complete_request("srv-qa-03", "INC-703", "CHG-703"), "qa-09", "qa-duplicate"
    )
    duplicate_id = duplicate_prepared.get("pending_action", {}).get("id")
    first_ticket, first_created = confirm_pending_action(
        DATABASE, duplicate_id, "qa-09", "qa-duplicate"
    )
    second_ticket, second_created = confirm_pending_action(
        DATABASE, duplicate_id, "qa-09", "qa-duplicate"
    )
    add("TEST-09", "Confirmacion duplicada", first_created and not second_created
        and first_ticket["id"] == second_ticket["id"]
        and ticket_count("qa-duplicate") == 1,
        {"prepared": duplicate_prepared, "first": first_ticket,
         "first_created": first_created, "second": second_ticket,
         "second_created": second_created, "tickets": ticket_count("qa-duplicate")},
        "Dos consumos conservan un solo ticket y el mismo ID.")

    security: dict[str, Any] = {}
    security_before = ticket_count("qa-security")
    checks: list[tuple[str, str, str, str]] = []
    base = create_pending_action(DATABASE, "qa-sec", "qa-security", "Acceso VPN", "Temporal")
    checks.append(("usuario", base["id"], "qa-sec", "otro-usuario"))
    checks.append(("thread", base["id"], "otro-thread", "qa-security"))
    for name, pending_id, thread, user in checks:
        try:
            confirm_pending_action(DATABASE, pending_id, thread, user)
            security[name] = "UNEXPECTED_WRITE"
        except PendingActionError as exc:
            security[name] = str(exc)
    cancelled_action = create_pending_action(
        DATABASE, "qa-sec-cancel", "qa-security", "Acceso SAP", "Temporal"
    )
    cancel_pending_action(DATABASE, cancelled_action["id"], "qa-sec-cancel", "qa-security")
    try:
        confirm_pending_action(DATABASE, cancelled_action["id"], "qa-sec-cancel", "qa-security")
        security["cancelada"] = "UNEXPECTED_WRITE"
    except PendingActionError as exc:
        security["cancelada"] = str(exc)
    expired = create_pending_action(DATABASE, "qa-sec-exp", "qa-security", "Acceso ERP", "Temporal")
    with connect(DATABASE) as connection:
        connection.execute(
            "UPDATE pending_actions SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
            (expired["id"],),
        )
    try:
        confirm_pending_action(DATABASE, expired["id"], "qa-sec-exp", "qa-security")
        security["expirada"] = "UNEXPECTED_WRITE"
    except PendingActionError as exc:
        security["expirada"] = str(exc)
    replaced_old = create_pending_action(
        DATABASE, "qa-sec-replace", "qa-security", "Acceso A", "Detalle A"
    )
    replaced_new = create_pending_action(
        DATABASE, "qa-sec-replace", "qa-security", "Acceso B", "Detalle B"
    )
    try:
        confirm_pending_action(DATABASE, replaced_old["id"], "qa-sec-replace", "qa-security")
        security["reemplazada"] = "UNEXPECTED_WRITE"
    except PendingActionError as exc:
        security["reemplazada"] = str(exc)
    try:
        confirm_pending_action(DATABASE, "accion-inexistente", "qa-sec", "qa-security")
        security["inexistente"] = "UNEXPECTED_WRITE"
    except PendingActionError as exc:
        security["inexistente"] = str(exc)
    security_after = ticket_count("qa-security")
    add("TEST-10", "Confirmaciones no autorizadas", security_before == security_after
        and all(value != "UNEXPECTED_WRITE" for value in security.values()),
        {"results": security, "tickets_before": security_before,
         "tickets_after": security_after, "replacement_active": replaced_new["id"]},
        "Rechazar inexistente, expirada, cancelada, otro usuario/thread y reemplazada.")

    memory_first = post("Estoy trabajando en un problema de acceso a SAP", "qa-11", "qa-short")
    memory_second = post("¿De qué sistema estábamos hablando?", "qa-11", "qa-short")
    unsafe_terms = ("contraseña", "password", "codigo mfa", "token", "secreto")
    add("TEST-11", "Memoria corta", "sap" in memory_second["answer"].lower()
        and not any(term in memory_second["answer"].lower() for term in unsafe_terms),
        {"first": memory_first, "second": memory_second},
        "Recordar SAP en el mismo thread sin reenviar history.")

    isolation_a1 = post("Estoy revisando acceso a SAP", "demo-1", "qa-isolation-a")
    isolation_b1 = post("Estoy revisando acceso a VPN", "demo-1", "qa-isolation-b")
    isolation_a2 = post("Estoy revisando acceso MFA", "demo-2", "qa-isolation-a")
    isolation_answers = {
        "a1": post("¿De qué sistema hablábamos?", "demo-1", "qa-isolation-a"),
        "b1": post("¿De qué sistema hablábamos?", "demo-1", "qa-isolation-b"),
        "a2": post("¿De qué sistema hablábamos?", "demo-2", "qa-isolation-a"),
    }
    isolation_pass = (
        "sap" in isolation_answers["a1"]["answer"].lower()
        and "vpn" in isolation_answers["b1"]["answer"].lower()
        and "mfa" in isolation_answers["a2"]["answer"].lower()
    )
    add("TEST-12", "Aislamiento de conversaciones", isolation_pass,
        {"setup": [isolation_a1, isolation_b1, isolation_a2], "answers": isolation_answers},
        "Separar mismo thread entre usuarios y distintos threads del mismo usuario.")

    persistent = post("¿Cuál fue mi última solicitud?", "qa-13-new", "qa-create")
    created_ticket = find_tickets(DATABASE, user_id="qa-create")[0]
    add("TEST-13", "Memoria larga", str(created_ticket["id"]) in persistent["answer"]
        and created_ticket["summary"] in persistent["answer"],
        {"database_ticket": created_ticket, "new_thread_response": persistent},
        "Recuperar desde SQLite en un thread nuevo.")

    older = insert_ticket(DATABASE, "qa-many", "Acceso SAP lectura", "Perfil consulta")
    newer = insert_ticket(DATABASE, "qa-many", "Acceso VPN temporal", "Siete dias")
    many = post("¿Cuáles son mis solicitudes?", "qa-14-list", "qa-many")
    latest = post("¿Cuál fue mi última solicitud?", "qa-14-latest", "qa-many")
    previous = post("¿Qué estado tiene el ticket anterior?", "qa-14-previous", "qa-many")
    multiple_pass = (
        str(older["id"]) in many["answer"] and str(newer["id"]) in many["answer"]
        and str(newer["id"]) in latest["answer"]
        and str(older["id"]) in previous["answer"]
    )
    add("TEST-14", "Multiples tickets", multiple_pass,
        {"older": older, "newer": newer, "list": many,
         "latest": latest, "previous": previous},
        "Listar dos IDs, reconocer el mas reciente y consultar el anterior.")

    missing_ticket = post("¿Qué estado tiene el ticket #999999?", "qa-16", "qa-errors")
    insufficient = post(
        "¿Cuál es la política interna para comprar computadores cuánticos?",
        "qa-16-docs", "qa-errors",
    )
    add("TEST-16A", "Ticket inexistente", missing_ticket["_http_status"] == 200
        and "no encontre" in missing_ticket["answer"].lower(), missing_ticket,
        "Responder controladamente sin inventar ticket.")
    add("TEST-16B", "Documentacion insuficiente", insufficient["_http_status"] == 200
        and insufficient["used_rag"], insufficient,
        "No inventar una politica ausente y exponer las fuentes recuperadas.")

    OUTPUT.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    passed = sum(result["status"] == "PASS" for result in results)
    print(json.dumps({"output": str(OUTPUT), "passed": passed,
                      "failed": len(results) - passed, "total": len(results)}, ensure_ascii=False))
    for result in results:
        print(f"{result['id']} {result['status']} {result['scenario']}")


if __name__ == "__main__":
    main()
