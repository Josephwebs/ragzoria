"""Run real Ollama cases and save inspectable results; not a semantic quality judge."""
import json
import sys
from uuid import uuid4
from pathlib import Path
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.main import app


def main():
    client = TestClient(app)
    results = []
    cases = [
        ("hola", False, False),
        ("Necesito acceso al servidor de produccion", True, False),
        ("Solo lectura hasta el viernes", True, True),
        ("El lunes entra Camila como analista contable", True, False),
        ("Denle a Juan los mismos permisos que Pedro", True, False),
        ("Cual es la politica interna para comprar computadoras cuanticas?", True, False),
        ("Necesito acceso administrador a produccion por dos semanas", True, False),
        ("Necesito audifonos para trabajar desde casa", True, False),
    ]
    thread_id = str(uuid4())
    for message, expected, follow_up in cases:
        if not follow_up:
            thread_id = str(uuid4())
        response = client.post("/api/chat", json={
            "message": message, "thread_id": thread_id, "user_id": "smoke-user"
        })
        payload = response.json()
        result = {"message": message, "status": response.status_code,
                  "expected_rag": expected, "response": payload}
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    output = ROOT / "evaluation/smoke_results.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    assert all(r["status"] == 200 and r["response"]["used_rag"] == r["expected_rag"]
               for r in results), "Review failing cases in evaluation/smoke_results.json"


if __name__ == "__main__":
    main()
