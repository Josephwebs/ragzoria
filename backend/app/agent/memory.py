from __future__ import annotations

import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger("ragzor.database")


class DatabaseError(RuntimeError):
    """Error controlado de persistencia."""


class PendingActionError(ValueError):
    """La accion pendiente no puede ejecutarse en el contexto indicado."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    details TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, key)
);
CREATE TABLE IF NOT EXISTS pending_actions (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    details TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ticket_id INTEGER,
    FOREIGN KEY(ticket_id) REFERENCES tickets(id)
);
CREATE INDEX IF NOT EXISTS idx_pending_owner
ON pending_actions(thread_id, user_id, status);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: str, field: str, minimum: int, maximum: int) -> str:
    cleaned = " ".join(value.split())
    if not minimum <= len(cleaned) <= maximum:
        raise ValueError(f"{field} debe tener entre {minimum} y {maximum} caracteres.")
    return cleaned


def connect(database_path: Path | str) -> sqlite3.Connection:
    path = Path(database_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
    except (sqlite3.Error, OSError) as exc:
        logger.exception("database_open_failed", extra={"database_parent": str(path.parent)})
        raise DatabaseError("No fue posible abrir la base de datos local.") from exc


def initialize_database(database_path: Path | str) -> None:
    try:
        with connect(database_path) as connection:
            connection.executescript(SCHEMA)
    except DatabaseError:
        raise
    except sqlite3.Error as exc:
        logger.exception("database_initialize_failed")
        raise DatabaseError("No fue posible inicializar la base de datos local.") from exc


def _upsert_memory(connection: sqlite3.Connection, user_id: str, key: str, value: str) -> None:
    connection.execute(
        """INSERT INTO memory(user_id, key, value, updated_at) VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id, key) DO UPDATE SET
           value=excluded.value, updated_at=excluded.updated_at""",
        (user_id, key, value, _now().isoformat()),
    )


def save_memory(database_path: Path | str, user_id: str, key: str, value: str) -> None:
    initialize_database(database_path)
    try:
        with connect(database_path) as connection:
            _upsert_memory(connection, _clean(user_id, "user_id", 1, 100), key, value)
    except sqlite3.Error as exc:
        raise DatabaseError("No fue posible guardar la memoria local.") from exc


def get_memories(database_path: Path | str, user_id: str) -> dict[str, str]:
    initialize_database(database_path)
    try:
        with connect(database_path) as connection:
            rows = connection.execute(
                "SELECT key, value FROM memory WHERE user_id = ?", (user_id,)
            ).fetchall()
    except sqlite3.Error as exc:
        raise DatabaseError("No fue posible consultar la memoria local.") from exc
    return {row["key"]: row["value"] for row in rows}


def insert_ticket(database_path: Path | str, user_id: str, summary: str, details: str) -> dict:
    """Insercion administrativa usada por el seed; el agente usa confirm_pending_action."""
    initialize_database(database_path)
    user_id = _clean(user_id, "user_id", 1, 100)
    summary = _clean(summary, "summary", 3, 200)
    details = _clean(details, "details", 3, 4000)
    created_at = _now().isoformat()
    try:
        with connect(database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "INSERT INTO tickets(user_id, summary, details, status, created_at) VALUES (?, ?, ?, 'open', ?)",
                (user_id, summary, details, created_at),
            )
            ticket_id = int(cursor.lastrowid)
            _upsert_memory(connection, user_id, "last_ticket_id", str(ticket_id))
            _upsert_memory(connection, user_id, "last_request_summary", summary)
    except sqlite3.Error as exc:
        raise DatabaseError("No fue posible crear el ticket local.") from exc
    return {"id": ticket_id, "user_id": user_id, "summary": summary, "details": details,
            "status": "open", "created_at": created_at}


def create_pending_action(
    database_path: Path | str, thread_id: str, user_id: str, summary: str,
    details: str, ttl_minutes: int = 15,
) -> dict:
    initialize_database(database_path)
    thread_id = _clean(thread_id, "thread_id", 1, 100)
    user_id = _clean(user_id, "user_id", 1, 100)
    summary = _clean(summary, "summary", 3, 200)
    details = _clean(details, "details", 3, 4000)
    if not 1 <= ttl_minutes <= 1440:
        raise ValueError("ttl_minutes debe estar entre 1 y 1440.")
    created_at = _now()
    action = {
        "id": str(uuid4()), "type": "create_ticket", "thread_id": thread_id,
        "user_id": user_id, "summary": summary, "details": details,
        "status": "pending", "created_at": created_at.isoformat(),
        "expires_at": (created_at + timedelta(minutes=ttl_minutes)).isoformat(),
    }
    try:
        with connect(database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE pending_actions SET status='cancelled' WHERE thread_id=? AND user_id=? AND status='pending'",
                (thread_id, user_id),
            )
            connection.execute(
                """INSERT INTO pending_actions
                   (id, thread_id, user_id, action_type, summary, details, status, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (action["id"], thread_id, user_id, action["type"], summary, details,
                 action["status"], action["created_at"], action["expires_at"]),
            )
    except sqlite3.Error as exc:
        raise DatabaseError("No fue posible guardar la accion pendiente.") from exc
    return action


def get_pending_action(database_path: Path | str, action_id: str, thread_id: str, user_id: str) -> dict | None:
    initialize_database(database_path)
    try:
        with connect(database_path) as connection:
            row = connection.execute(
                """SELECT id, action_type AS type, thread_id, user_id, summary, details,
                          status, created_at, expires_at, ticket_id
                   FROM pending_actions WHERE id=? AND thread_id=? AND user_id=?""",
                (action_id, thread_id, user_id),
            ).fetchone()
    except sqlite3.Error as exc:
        raise DatabaseError("No fue posible consultar la accion pendiente.") from exc
    return dict(row) if row else None


def cancel_pending_action(database_path: Path | str, action_id: str, thread_id: str, user_id: str) -> bool:
    initialize_database(database_path)
    try:
        with connect(database_path) as connection:
            cursor = connection.execute(
                """UPDATE pending_actions SET status='cancelled'
                   WHERE id=? AND thread_id=? AND user_id=? AND status='pending'""",
                (action_id, thread_id, user_id),
            )
            return cursor.rowcount == 1
    except sqlite3.Error as exc:
        raise DatabaseError("No fue posible cancelar la accion pendiente.") from exc


def confirm_pending_action(
    database_path: Path | str, action_id: str, thread_id: str, user_id: str,
) -> tuple[dict, bool]:
    """Confirma una vez. Los reintentos devuelven el mismo ticket sin duplicarlo."""
    initialize_database(database_path)
    try:
        with connect(database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM pending_actions WHERE id=? AND thread_id=? AND user_id=?",
                (action_id, thread_id, user_id),
            ).fetchone()
            if not row:
                raise PendingActionError("La accion pendiente no pertenece a este usuario y conversacion.")
            if row["status"] == "consumed" and row["ticket_id"]:
                ticket = connection.execute(
                    "SELECT * FROM tickets WHERE id=? AND user_id=?", (row["ticket_id"], user_id)
                ).fetchone()
                if ticket:
                    return dict(ticket), False
            if row["status"] != "pending":
                raise PendingActionError(f"La accion ya no esta disponible: {row['status']}.")
            if datetime.fromisoformat(row["expires_at"]) <= _now():
                connection.execute("UPDATE pending_actions SET status='expired' WHERE id=?", (action_id,))
                connection.commit()
                raise PendingActionError("La confirmacion expiro; prepara una nueva solicitud.")
            created_at = _now().isoformat()
            cursor = connection.execute(
                "INSERT INTO tickets(user_id, summary, details, status, created_at) VALUES (?, ?, ?, 'open', ?)",
                (user_id, row["summary"], row["details"], created_at),
            )
            ticket_id = int(cursor.lastrowid)
            connection.execute(
                "UPDATE pending_actions SET status='consumed', ticket_id=? WHERE id=? AND status='pending'",
                (ticket_id, action_id),
            )
            _upsert_memory(connection, user_id, "last_ticket_id", str(ticket_id))
            _upsert_memory(connection, user_id, "last_request_summary", row["summary"])
            ticket = connection.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
            return dict(ticket), True
    except PendingActionError:
        raise
    except sqlite3.Error as exc:
        raise DatabaseError("No fue posible confirmar el ticket local.") from exc


def find_tickets(
    database_path: Path | str, ticket_id: int | None = None, user_id: str | None = None,
) -> list[dict]:
    initialize_database(database_path)
    if not user_id:
        return []
    try:
        with connect(database_path) as connection:
            if ticket_id is not None:
                rows = connection.execute(
                    "SELECT * FROM tickets WHERE id=? AND user_id=?", (ticket_id, user_id)
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT * FROM tickets WHERE user_id=?
                       ORDER BY datetime(created_at) DESC, id DESC LIMIT 10""",
                    (user_id,),
                ).fetchall()
    except sqlite3.Error as exc:
        raise DatabaseError("No fue posible consultar los tickets locales.") from exc
    return [dict(row) for row in rows]
