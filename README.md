# Ragzor Assistant

Ragzor Assistant es un asistente conversacional para Mesa de Ayuda TI. Permite
analizar solicitudes de usuarios y responder usando informacion recuperada desde
documentos locales mediante RAG.

El proyecto usa un LLM local con Ollama, embeddings locales, FAISS como vector
store, FastAPI como backend y React como frontend.

## Que hace

- Responde saludos y conversacion simple sin consultar documentos.
- Detecta cuando una solicitud necesita informacion documental.
- Recupera evidencia desde documentos locales.
- Responde usando contexto recuperado.
- Muestra evidencia en un panel plegable.
- Mantiene historial corto de conversacion para entender seguimientos.

Ejemplo:

```text
Usuario: Necesito acceso administrador a produccion por dos semanas.
Ragzor: responde con requisitos, riesgos o datos faltantes segun documentos recuperados.
```

## Enfoque del asistente

Ragzor funciona como asistente conversacional con LLM + RAG. El modelo interpreta
el mensaje, considera el historial reciente y decide si corresponde responder
como conversacion normal (`CHAT`) o consultar documentos mediante recuperacion
documental (`RAG`).

El foco del proyecto es analizar solicitudes de Mesa de Ayuda, recuperar
evidencia relevante y entregar respuestas breves apoyadas en documentos.

## Arquitectura

```text
React
  |
  | POST /api/chat
  v
FastAPI
  |
  | decide CHAT o RAG con Ollama
  v
Ollama llama3
  |
  | si requiere RAG
  v
FAISS + embeddings bge-m3
  |
  | recupera top 2 chunks
  v
Ollama llama3 genera respuesta final
```

Componentes:

- Frontend: React + TypeScript.
- Backend: FastAPI.
- LLM: Ollama con `llama3:latest`.
- Embeddings: Ollama con `bge-m3`.
- Vector store: FAISS.
- Contratos de API: Pydantic.
- Fuentes: archivos Markdown/TXT en `data/internal` y `data/external`.

## Requisitos

Antes de ejecutar el proyecto, instalar:

- Python 3.11 o superior.
- Node.js 18 o superior.
- Ollama.
- Git.

Ollama debe estar ejecutandose localmente en:

```text
http://localhost:11434
```

## Instalacion

Clonar el repositorio:

```bash
git clone https://github.com/Josephwebs/ragzoria.git
cd ragzoria
```

Crear entorno Python e instalar dependencias:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

Instalar dependencias del frontend:

```bash
npm --prefix frontend install
```

Crear archivo de variables de entorno:

```bash
cp .env.example .env
```

Descargar modelos de Ollama:

```bash
ollama pull llama3
ollama pull bge-m3
```

Si Ollama no esta corriendo:

```bash
ollama serve
```

## Indexar documentos

Antes de usar el chat con RAG, crear el indice FAISS:

```bash
source .venv/bin/activate
python scripts/ingest.py
```

Este comando lee documentos desde:

```text
data/internal
data/external
```

Luego los divide en chunks, genera embeddings con `bge-m3` y guarda el indice en:

```text
backend/storage/faiss_simple
```

Si se modifican documentos o se cambia el modelo de embeddings, ejecutar este
comando nuevamente.

## Ejecutar backend

En una terminal:

```bash
source .venv/bin/activate
uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

La API queda disponible en:

```text
http://127.0.0.1:8000
```

Health check:

```text
http://127.0.0.1:8000/api/health
```

## Ejecutar frontend

En otra terminal:

```bash
npm --prefix frontend run dev
```

Abrir en navegador:

```text
http://127.0.0.1:5173
```

Si Vite usa otro puerto, abrir el puerto indicado en la terminal.

## Variables principales

El archivo `.env.example` contiene valores por defecto:

```env
OLLAMA_MODEL=llama3:latest
EMBEDDING_MODEL=bge-m3
OLLAMA_BASE_URL=http://localhost:11434
TOP_K=2
CHUNK_SIZE=350
CHUNK_OVERLAP=50
RAG_DEBUG=false
```

Significado:

- `OLLAMA_MODEL`: modelo usado para clasificar y responder.
- `EMBEDDING_MODEL`: modelo usado para generar vectores.
- `OLLAMA_BASE_URL`: URL local de Ollama.
- `TOP_K`: cantidad de chunks recuperados por consulta.
- `CHUNK_SIZE`: tamano de cada fragmento.
- `CHUNK_OVERLAP`: solapamiento entre fragmentos.
- `RAG_DEBUG`: si es `true`, imprime en terminal decision, query, chunks y prompt RAG.

## API principal

Endpoint:

```text
POST /api/chat
```

Ejemplo de entrada:

```json
{
  "message": "Necesito acceso al servidor de pagos en produccion",
  "history": []
}
```

Ejemplo de salida:

```json
{
  "answer": "Para procesar la solicitud necesito el usuario, servidor exacto, nivel de permiso y duracion.",
  "used_rag": true,
  "sources": [
    {
      "source": "politica_acceso_servidores.md",
      "tipo_fuente": "internal",
      "categoria": "internal",
      "seccion": "Accesos privilegiados",
      "fragment": "..."
    }
  ]
}
```

## Archivos importantes

- `backend/app/main.py`: crea la aplicacion FastAPI.
- `backend/app/api/chat.py`: define `POST /api/chat`.
- `backend/app/rag/chat.py`: coordina decision CHAT/RAG, retrieval y respuesta.
- `backend/app/llm/ollama.py`: comunica el backend con Ollama.
- `backend/app/embeddings/provider.py`: genera embeddings con Ollama.
- `backend/app/retrievers/faiss_retriever.py`: consulta el indice FAISS.
- `backend/app/rag/ingestion.py`: crea el indice FAISS.
- `backend/app/prompts.py`: prompts del asistente.
- `frontend/src/App.tsx`: estado principal del chat.
- `frontend/src/components/SourcesPanel.tsx`: evidencia recuperada.
- `docs/proyecto.md`: explicacion tecnica del proyecto.

## Pruebas

Ejecutar pruebas unitarias:

```bash
pytest -q
```

Construir frontend:

```bash
npm --prefix frontend run build
```

Evaluar retrieval:

```bash
python scripts/evaluate_rag.py
```

Probar chat real con Ollama:

```bash
python scripts/smoke_chat.py
```

Notas:

- `evaluate_rag.py` y `smoke_chat.py` requieren Ollama activo e indice FAISS creado.
- Las pruebas unitarias usan dobles del modelo para validar comportamiento tecnico.
- La evidencia recuperada ayuda a revisar la respuesta, pero no reemplaza revision humana.

## Docker opcional

Tambien se puede ejecutar con Docker:

```bash
docker compose up --build
```

Ollama debe estar corriendo en el host. Para crear el indice dentro del contenedor:

```bash
docker compose exec backend python -c "from app.rag.ingestion import ingest_all; print(ingest_all())"
```

## Documentacion

Para mas detalle tecnico, revisar:

```text
docs/proyecto.md
```
