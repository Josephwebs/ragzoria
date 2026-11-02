# Reporte de corrección y pruebas end-to-end — Ragzor EP2

## 1. Entorno y alcance

- Fecha de validación: 2026-11-02, America/Santiago.
- Arquitectura conservada: un agente LangGraph, `llama3:latest`, FAISS, React, FastAPI y SQLite.
- Ollama real: `llama3:latest` (8B Q4_0) y `bge-m3:latest` disponibles.
- Backend normal: `http://127.0.0.1:8000`; frontend: `http://127.0.0.1:5173`.
- Backend E2E aislado: puerto 8001.
- SQLite E2E aislada final: `/private/tmp/ragzor_ep2_e2e_final_20261102.db`.
- Evidencia: `evaluation/e2e_results.json` y `evaluation/smoke_results.json`.
- La evaluación E2E utilizó Ollama real. Los dobles de prueba se limitaron a las pruebas unitarias.

## 2. Defectos corregidos

### DEF-001 — Solicitud de credenciales SAP (CRÍTICO) — CORREGIDO

**Causa:** el prompt no prohibía secretos y la salida del LLM llegaba al usuario sin una barrera determinista.

**Corrección:** se añadió una regla explícita al prompt y un filtro posterior al LLM que detecta solicitudes de contraseñas, credenciales, códigos MFA/recuperación, tokens, API keys, PIN y otros secretos. La respuesta se sustituye por una instrucción segura que solo solicita módulo, rol y mensaje de error. El seguimiento contextual “¿de qué sistema hablábamos?” se resuelve de forma determinista desde el historial del thread.

**Resultado real:** TEST-11 devolvió `Estabamos hablando de SAP.` sin pedir credenciales. Una prueba unitaria fuerza al LLM simulado a pedir contraseña, token y MFA y confirma que la salida queda bloqueada.

### DEF-002 — Propuesta de ticket incompleta (ALTO) — CORREGIDO

**Causa:** `request_confirmation` solo comprobaba la longitud de `summary` y `details` generados por el LLM, por lo que aceptaba antecedentes inventados.

**Corrección:** la validación se realiza contra mensajes humanos. Para acceso administrador a producción exige servidor, duración, motivo/incidente, ventana de uso, plan de reversa y cambio autorizado. Para acceso SAP exige módulo, sociedad, centro de costo y justificación. Si falta un campo se pregunta antes de crear `pending_action`. El detalle persistido se construye desde los mensajes del usuario, no desde texto generado por el modelo.

**Resultado real:** TEST-05 mantuvo cero tickets y cero acciones pendientes en sus cuatro turnos incompletos. La prueba unitaria confirma que datos inventados por el modelo no superan la validación.

### DEF-003 — Contexto obsoleto después de replanificar (ALTO) — CORREGIDO

**Causa:** la nueva consulta concatenaba el objetivo corregido con turnos anteriores de producción y preservaba fuentes incompatibles.

**Corrección:** se detecta el ambiente vigente desde el último cambio explícito; el cambio a pruebas genera un plan y una consulta nuevos, filtra evidencia exclusiva de producción, repite la búsqueda documental e invalida cualquier acción pendiente anterior. Se conserva el historial conversacional completo, pero no se usa evidencia incompatible para responder.

**Resultado real:** TEST-06 cambió el plan, ejecutó una nueva búsqueda y devolvió `sources=[]`, indicando que no encontró documentación compatible y que no aplicaría requisitos exclusivos de producción.

### DEF-004 — “Ticket anterior” devolvía el más reciente (MEDIO) — CORREGIDO

**Causa:** la respuesta seleccionaba siempre `tickets[0]` salvo para el listado completo.

**Corrección:** se tipificaron cuatro intenciones: último ticket, anterior al último, ID explícito e historial. SQLite usa orden estable `datetime(created_at) DESC, id DESC`; “anterior” selecciona el segundo registro.

**Resultado real:** TEST-14 listó #4 y #3, devolvió #4 como último y #3 como anterior.

### DEF-005 — Error SQLite no controlado (MEDIO) — CORREGIDO

**Causa:** la creación del directorio ocurría fuera de la traducción de excepciones y `FileExistsError` escapaba como HTTP 500.

**Corrección:** `OSError` y errores SQLite se registran con detalle técnico en backend y se traducen a `DatabaseError`. La API devuelve un HTTP 503 genérico sin ruta, SQL ni traceback.

**Resultado real:** con `DATABASE_PATH=/dev/null/ragzor.db`, `POST /api/chat` respondió HTTP 503 con `La persistencia local no esta disponible temporalmente.`. El log del backend conservó el traceback técnico.

### DEF-006 — Respuesta engañosa con FAISS ausente (MEDIO) — CORREGIDO

**Causa:** el error de recuperación llegaba como una observación de tool ambigua y el LLM generaba una explicación inventada.

**Corrección:** `buscar_documentacion` distingue `ok`, `empty`, `index_missing` y `retrieval_error`. El grafo responde de forma determinista a errores y nunca expone fuentes ficticias.

**Resultado real:** con un directorio FAISS inexistente, la API respondió HTTP 200, `used_rag=false`, `sources=[]` y `No pude consultar la documentacion porque el indice FAISS no esta disponible. Ejecuta python scripts/ingest.py y vuelve a intentarlo.`

## 3. Archivos modificados para la corrección

- `backend/app/agent/graph.py`: defensas de secretos, validación por clase, ambiente vigente, replanificación, filtrado de fuentes, intención de tickets y manejo de estados de recuperación.
- `backend/app/agent/prompts.py`: prohibición explícita de solicitar secretos.
- `backend/app/agent/tools.py`: resultado estructurado para búsqueda exitosa, vacía, índice ausente y error técnico.
- `backend/app/agent/memory.py`: errores controlados de apertura/inicialización y orden estable de tickets.
- `backend/app/api/chat.py`: HTTP 503 sanitizado para fallos de persistencia.
- `backend/tests/test_agent.py`: seis regresiones nuevas, una por defecto.
- `backend/tests/test_api.py`: contrato sanitizado de error de base de datos.
- `scripts/qa_e2e.py`: aserciones reforzadas para secretos y replanificación.
- `evaluation/e2e_results.json` y `evaluation/smoke_results.json`: evidencia regenerada.

## 4. Pruebas nuevas

1. Bloqueo de una solicitud de contraseña, token y código MFA generada por el modelo.
2. Rechazo de `pending_action` para acceso administrador incompleto aunque el modelo invente detalles.
3. Cambio producción → pruebas con descarte de fuentes exclusivas de producción.
4. Selección del segundo ticket más reciente para “ticket anterior”.
5. Conversión de `/dev/null/ragzor.db` a `DatabaseError` sin filtrar la ruta al cliente.
6. Índice FAISS ausente con respuesta explícita, sin fuentes fabricadas.

## 5. Resultados reales de regresión

| Comprobación | Resultado |
|---|---|
| Pytest existente | 25/25 PASS |
| Regresiones nuevas | 6/6 PASS |
| Pytest total | **31/31 PASS** en 0,62 s |
| Build React | **PASS**; 1.580 módulos, Vite 772 ms |
| RAG Hit Rate@2 | **12/13 = 92,3 %** |
| Smoke chat | **8/8 PASS**; HTTP 200 y uso de RAG esperado |
| E2E con Ollama real | **16/16 PASS** |
| Crear ticket | PASS; cero escrituras antes de confirmar y una después |
| Cancelar ticket | PASS; acción cancelada y reintento sin escritura |
| Idempotencia | PASS; dos consumos, un ticket y mismo ID |
| Memoria corta | PASS; SAP recordado sin secretos |
| Memoria larga | PASS; ticket recuperado desde SQLite en otro thread |
| Replanificación | PASS; nuevo plan, búsqueda nueva y fuentes incompatibles descartadas |
| SQLite inválida | PASS; HTTP 503 sanitizado |
| FAISS ausente | PASS; indisponibilidad explícita y cero fuentes |

### Matriz E2E

| ID | Escenario | Estado |
|---|---|---|
| TEST-01 | Saludo normal | PASS |
| TEST-02 | Consulta documental VPN | PASS |
| TEST-03 | Consulta documental SAP | PASS |
| TEST-04 | Información insuficiente | PASS |
| TEST-05 | Conversación de varios turnos | PASS |
| TEST-06 | Replanificación producción → pruebas | PASS |
| TEST-07 | Creación confirmada | PASS |
| TEST-08 | Cancelación | PASS |
| TEST-09 | Confirmación duplicada | PASS |
| TEST-10 | Confirmaciones no autorizadas | PASS |
| TEST-11 | Memoria corta y defensa de credenciales | PASS |
| TEST-12 | Aislamiento de conversaciones | PASS |
| TEST-13 | Memoria larga | PASS |
| TEST-14 | Lista, último y anterior | PASS |
| TEST-16A | Ticket inexistente | PASS |
| TEST-16B | Documentación insuficiente | PASS con observación |

## 6. Variabilidad y fallos pendientes

- `llama3:latest` puede variar la redacción de preguntas y planes. La evaluación se repitió después de las correcciones; los invariantes críticos quedaron fuera del control del LLM y el resultado final fue 16/16.
- RAG conserva el caso fallido histórico “El lunes entra Camila como analista contable”: recupera documentos relacionados, pero no `procedimiento_nuevo_ingreso.md`; por eso el Hit Rate@2 sigue en 92,3 %. No corresponde a uno de los seis defectos solicitados.
- TEST-16B reconoce que no existe una política de computadores cuánticos, pero todavía agrega recomendaciones MFA de fuentes semánticamente cercanas. Se mantiene como observación de baja severidad; no inventa una política interna ni oculta las fuentes utilizadas.
- Algunos planes generados por Llama incluyen pasos más amplios que las tools disponibles. No causaron ejecución indebida ni escrituras.
- La validación visual automatizada de React continúa **BLOCKED** porque el permiso previo del navegador para observar `127.0.0.1:5173` fue rechazado. El build y la carga HTTP sí pasaron, pero no se declara validación visual completa.

## 7. Veredicto de demostración

**LISTO PARA DEMOSTRACIÓN FUNCIONAL CON RESERVA VISUAL.**

Los seis defectos funcionales y de seguridad solicitados están corregidos y verificados. La suite total, build, smoke, RAG, persistencia, creación/cancelación/idempotencia y los 16 escenarios E2E reales pasaron. La única reserva para una demostración pública es completar una inspección manual de la interfaz React —mensajes, fuentes, botones Confirmar/Cancelar, estados de carga y consola— porque esa observación no pudo automatizarse en esta sesión.
