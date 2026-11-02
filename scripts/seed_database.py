import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agent.memory import find_tickets, initialize_database, insert_ticket
from app.config.settings import get_settings


def seed() -> dict:
    settings = get_settings()
    initialize_database(settings.database_path)
    if not find_tickets(settings.database_path, user_id="demo-user"):
        insert_ticket(
            settings.database_path,
            "demo-user",
            "Problema de conexion VPN",
            "La VPN muestra gateway no disponible desde el equipo corporativo.",
        )
        insert_ticket(
            settings.database_path,
            "demo-user",
            "Acceso de lectura a SAP",
            "Solicitud de rol de consulta para ordenes de compra.",
        )
    return {"database": str(settings.database_path), "tickets": len(find_tickets(settings.database_path, user_id="demo-user"))}


if __name__ == "__main__":
    print(seed())
