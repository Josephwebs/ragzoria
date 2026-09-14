# Ragzor Assistant

## Estado actual

Ragzor Assistant es un chat para Mesa de Ayuda TI. Recibe mensajes del usuario,
decide si necesita consultar documentos y responde usando un LLM local con
Ollama. Cuando la consulta requiere informacion interna, usa RAG con FAISS para
recuperar evidencia desde documentos locales.

El sistema se centra en analizar solicitudes, recuperar evidencia y responder
con base en documentos cargados.

## Stack

- Frontend: React + TypeScript.
- Backend: FastAPI.
- LLM local: Ollama con `llama3:latest`.
- Embeddings: Ollama con `bge-m3`.
- Vector store: FAISS.
- Validacion API: Pydantic.
- Documentos fuente: Markdown/TXT locales en `data/internal` y `data/external`.

## Flujo general

1. Usuario escribe en el chat.
2. React envia mensaje e historial corto a FastAPI.
3. FastAPI valida entrada con Pydantic.
4. Ollama decide si el mensaje es `CHAT` o `RAG`.
5. Si es `CHAT`, responde sin buscar documentos.
6. Si es `RAG`, FAISS recupera los 2 chunks mas relevantes.
7. Backend arma prompt con contexto, historial y pregunta.
8. Ollama genera respuesta final.
9. React muestra respuesta.
10. Si se uso RAG, aparece boton `Ver evidencia`.

## Flujo backend

```text
React
POST /api/chat
backend/app/api/chat.py::chat()
backend/app/rag/chat.py::answer()
backend/app/rag/chat.py::needs_rag()
backend/app/llm/ollama.py::chat()
Ollama decide CHAT o RAG
```

Si es `CHAT`:

```text
backend/app/llm/ollama.py::chat()
Ollama genera respuesta natural
ChatResponse used_rag=false
```

Si es `RAG`:

```text
backend/app/retrievers/faiss_retriever.py::retrieve()
FAISS.load_local()
backend/app/embeddings/provider.py::embed_query()
Ollama bge-m3 genera vector
FAISS devuelve top 2 chunks
backend/app/rag/chat.py arma contexto
backend/app/llm/ollama.py::chat()
Ollama llama3 genera respuesta con evidencia
ChatResponse used_rag=true + sources
```

## Archivos principales

- `backend/app/main.py`: crea FastAPI, CORS, health check y monta rutas.
- `backend/app/api/chat.py`: endpoint `POST /api/chat`.
- `backend/app/models/schemas.py`: contratos Pydantic de entrada y salida.
- `backend/app/config/settings.py`: variables de configuracion.
- `backend/app/rag/chat.py`: orquesta decision CHAT/RAG, retrieval y respuesta.
- `backend/app/llm/ollama.py`: cliente HTTP hacia Ollama.
- `backend/app/embeddings/provider.py`: embeddings con Ollama `bge-m3`.
- `backend/app/retrievers/faiss_retriever.py`: carga FAISS y busca top 2.
- `backend/app/rag/loaders.py`: lee documentos locales.
- `backend/app/rag/chunking.py`: divide documentos en chunks.
- `backend/app/rag/ingestion.py`: crea y guarda indice FAISS.
- `backend/app/prompts.py`: prompts de decision, chat y RAG.
- `frontend/src/App.tsx`: estado principal del chat.
- `frontend/src/components/ChatWindow.tsx`: vista de conversacion.
- `frontend/src/components/SourcesPanel.tsx`: evidencia plegable.

## Indexacion

La indexacion se ejecuta con:

```bash
python scripts/ingest.py
```

Flujo:

```text
scripts/ingest.py
ingest_all()
load_documents()
split_documents()
OllamaEmbeddings.embed_documents()
FAISS.from_documents()
FAISS.save_local()
```

Configuracion actual:

- `chunk_size`: 350 caracteres.
- `chunk_overlap`: 50 caracteres.
- `top_k`: 2.
- indice FAISS: `backend/storage/faiss_simple`.

## API

Endpoint principal:

```text
POST /api/chat
```

Entrada:

```json
{
  "message": "Necesito acceso a produccion",
  "history": []
}
```

Salida:

```json
{
  "answer": "respuesta del asistente",
  "used_rag": true,
  "sources": []
}
```

`sources` contiene documento, tipo, categoria, seccion y fragmento. El frontend
lo muestra solo cuando el usuario abre `Ver evidencia`.

## Por que usa RAG

El LLM por si solo puede inventar informacion. RAG reduce ese riesgo porque la
respuesta se genera con fragmentos recuperados desde documentos definidos por el
proyecto. La evidencia permite revisar de donde salio la informacion.

Importante: RAG no elimina totalmente errores. Si el retrieval trae contexto
incompleto, el LLM puede responder con informacion parcial. Por eso se muestra
evidencia y existen pruebas de retrieval.

## Como ejecutar

Ollama:

```bash
ollama serve
ollama pull llama3
ollama pull bge-m3
```

Backend:

```bash
cd "/Users/josephwebs/Documents/ragzor ia"
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python scripts/ingest.py
uvicorn app.main:app --app-dir backend --reload --port 8000
```

Frontend:

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

Abrir:

```text
http://127.0.0.1:5173
```

## Pruebas

```bash
pytest -q
npm --prefix frontend run build
python scripts/evaluate_rag.py
python scripts/smoke_chat.py
```

Resultado actual:

- pruebas backend: 14 aprobadas.
- build frontend: aprobado.
- retrieval: 12/13 Hit Rate@2.
- smoke chat: 8 casos CHAT/RAG aprobados.

## Alcance

- Analiza solicitudes de Mesa de Ayuda TI.
- Usa documentos locales como base de conocimiento.
- Mantiene historial reciente en el frontend.
- Muestra evidencia recuperada para revisar la respuesta.
- La calidad depende de documentos, embeddings y chunks recuperados.
