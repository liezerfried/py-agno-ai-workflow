# Agno SDK Reference — Guía Completa

Referencia de todos los módulos y secciones que expone el SDK de Agno, organizada en las tres grandes áreas: **Agno SDK**, **AgentOS API** y **Agno Infra CLI**.

---

## 1. Agno SDK Reference

### Agent

**`agno.agent.Agent`** — La clase central del SDK. Encapsula un agente de IA con modelo, instrucciones, herramientas, memoria y base de conocimiento.

Configuración clave:
- `model` — el LLM que usa el agente (OpenAI, Anthropic, Gemini, etc.)
- `tools` — lista de herramientas disponibles para el agente
- `knowledge` — base de conocimiento para RAG (Retrieval-Augmented Generation)
- `db` — base de datos para persistir sesiones y memorias
- `instructions` — instrucciones del sistema
- `update_memory_on_run` — si debe actualizar la memoria automáticamente en cada run
- `search_knowledge` — si debe buscar en la knowledge base automáticamente
- `add_history_to_context` — si debe incluir el historial de conversación en el contexto

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    name="My Agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions="Eres un asistente útil.",
    update_memory_on_run=True,
)
agent.print_response("Hola, ¿cómo estás?")
```

---

### RemoteAgent

**`agno.agent.RemoteAgent`** — Permite conectarse a un agente que corre remotamente en una instancia de AgentOS, en lugar de ejecutarlo localmente. Útil para sistemas distribuidos donde el agente está desplegado en un servidor separado y se lo consume como servicio.

```python
from agno.agent import RemoteAgent

agent = RemoteAgent(base_url="http://my-agent-os:7777", agent_id="my-agent")
```

---

### Team

**`agno.team.Team`** — Orquesta múltiples agentes trabajando en conjunto. El equipo tiene su propio modelo coordinador que delega tareas a los agentes miembro.

- `members` — lista de agentes del equipo
- `model` — el modelo del coordinador (decide qué agente actúa)
- `instructions` — guía al coordinador sobre cómo delegar
- `db` — base de datos compartida para sesiones

```python
from agno.team import Team

team = Team(
    name="Research Team",
    members=[agent_1, agent_2],
    instructions=["Delega preguntas de investigación al Researcher."],
)
```

---

### Workflows

El sistema de Workflows tiene **tres capas**: `Step` → `Steps` → `Workflow`.

**`agno.workflow.step.Step`** — Unidad mínima. Envuelve un Agent (o Team, o función custom) con nombre y descripción.

- `name` — identificador del paso
- `agent` — el agente que ejecuta este paso (también acepta `team` o `function`)
- `description` — descripción del paso (opcional, mejora trazas)

**`agno.workflow.steps.Steps`** — Agrupa una secuencia ordenada de `Step`s en una unidad nombrada. Permite componer sub-pipelines reutilizables. Los Steps se ejecutan en orden.

- `name` — nombre de la secuencia
- `steps` — lista de `Step` a ejecutar en orden
- `description` — descripción del grupo

**`agno.workflow.workflow.Workflow`** — Orquesta una o más secuencias de `Steps`. Persiste el estado entre ejecuciones.

- `steps` — lista de `Steps` (no de `Step` individuales — se agrupan antes)
- `db` — base de datos para persistir el estado del workflow
- `name`, `description` — metadatos del workflow

```python
from agno.workflow.step import Step
from agno.workflow.steps import Steps
from agno.workflow.workflow import Workflow
from agno.db.sqlite import SqliteDb

# Paso 1: definir steps individuales
ingest_step   = Step(name="ingest",    agent=ingest_agent,    description="Extraer categorías únicas del Excel")
validate_step = Step(name="validate",  agent=validator_agent, description="Comparar contra O*NET válidos")
map_step      = Step(name="map",       agent=mapper_agent,    description="Proponer correcciones con rapidfuzz + LLM")
audit_step    = Step(name="audit",     agent=audit_writer,    description="Escribir Excel corregido + audit log")

# Paso 2: agrupar en una secuencia
pipeline = Steps(
    name="normalization_pipeline",
    description="Pipeline completo de normalización de categorías O*NET",
    steps=[ingest_step, validate_step, map_step, audit_step],
)

# Paso 3: crear el Workflow
workflow = Workflow(
    name="ONet Normalization Workflow",
    steps=[pipeline],
    db=SqliteDb(session_table="workflow_session", db_file="tmp/workflow.db"),
)
```

**Ejecución directa (dev/testing):**
```python
workflow.print_response("Procesar archivo upload.xlsx", stream=True)
```

**Ejecución via AgentOS (producción)** — ver sección AgentOS más abajo.

---

### AgentOS

**`agno.os.AgentOS`** — Runtime y plano de control para desplegar y gestionar agentes, teams y workflows en producción. **Es el reemplazo de FastAPI puro** — en lugar de crear una app FastAPI manualmente, `AgentOS` la genera y expone una REST API completa con endpoints para agentes, workflows, sesiones, trazas, memoria, knowledge, evals y schedules.

Parámetros clave:
- `agents` — lista de agentes disponibles
- `teams` — lista de teams
- `workflows` — lista de workflows
- `knowledge` — lista de knowledge bases
- `db` — base de datos principal
- `id`, `name`, `description` — metadatos del OS

**Patrón estándar de wiring (producción):**
```python
from agno.os import AgentOS

agent_os = AgentOS(
    id="onet-normalizer",
    description="Pipeline de normalización de categorías O*NET",
    workflows=[onet_workflow],
    db=SqliteDb(db_file="tmp/app.db"),
)

# get_app() devuelve la FastAPI app lista para uvicorn
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="main:app", reload=True)
```

```bash
# Arrancar el servidor
uvicorn main:app --reload --port 7777
```

**NO hacer esto** (FastAPI manual sin AgentOS):
```python
# ❌ Patrón viejo — no usar
from fastapi import FastAPI
app = FastAPI()

@app.post("/run")
def run_workflow(...):
    ...
```

AgentOS ya expone `/workflows/{id}/runs` y `/workflows/{id}/runs/stream` automáticamente. No reimplementar lo que AgentOS da gratis.

---

### Clients

**`agno.client.AgentOSClient`** — Cliente Python para interactuar programáticamente con una instancia de AgentOS corriendo remotamente. Permite:

- Ejecutar agentes, teams y workflows (con o sin streaming)
- Gestionar sesiones de conversación
- Buscar y administrar knowledge bases
- Acceder a memorias de usuarios
- Monitorear trazas para debugging

```python
from agno.client import AgentOSClient

client = AgentOSClient(base_url="http://localhost:7777")

# Run con streaming
async for event in client.run_agent_stream(agent_id="my-agent", message="Hola"):
    print(event.content, end="")
```

---

### Runs

**`agno.run`** — Módulo que representa una ejecución (run) individual de un agente, team o workflow. Cada llamada a `.run()` o `.print_response()` genera un Run con su propio `run_id`.

Clases de eventos relevantes:
- `RunContentEvent` — chunk de contenido generado (streaming)
- `RunCompletedEvent` — señal de fin del run

Los Runs pueden ser persistidos en base de datos para auditoría, replay y observabilidad.

---

### Sessions

**`agno.db`** — Las sesiones permiten que un agente mantenga el contexto de conversación a lo largo de múltiples runs. Se identifican por `session_id` y se almacenan en la base de datos configurada.

- Permiten conversaciones multi-turno
- El historial de la sesión puede inyectarse automáticamente al contexto con `add_history_to_context=True`
- Soportan resúmenes automáticos con `enable_session_summaries=True`

---

### Memory

**`agno.memory`** — Sistema de memoria que permite a los agentes recordar información sobre usuarios entre sesiones distintas. A diferencia de las sesiones (historial de conversación), la memoria extrae y persiste *hechos* relevantes del usuario.

- Se activa con `update_memory_on_run=True` en el Agent
- `agent.get_user_memories(user_id="user_123")` — recupera memorias de un usuario
- Soporta estrategias de optimización: `SUMMARIZE` (resume memorias antiguas para reducir tokens)
- Permite alertas y poda cuando el volumen de memorias es alto

```python
# Verificar cantidad de memorias
memories = agent.get_user_memories(user_id="user_123")
if len(memories) > 500:
    print("Considerar poda de memorias.")
```

---

### Context Compression

Mecanismo para reducir el tamaño del contexto que se envía al modelo en cada run. Especialmente útil en conversaciones largas donde el historial completo supera el límite de tokens.

Estrategias disponibles:
- **Summarize** — genera un resumen comprimido de los turnos anteriores en lugar de enviarlos completos
- Reduce costos y latencia sin perder el hilo de la conversación

Se configura a nivel de Agent o a través del `memory_manager`.

---

### Database

**`agno.db`** — Capa de abstracción para la persistencia. Soporta múltiples backends:

- `agno.db.sqlite.SqliteDb` — SQLite para desarrollo local
- `agno.db.postgres.PostgresDb` — PostgreSQL para producción
- `agno.db.in_memory.InMemoryDb` — solo en memoria (testing/prototipado)

La base de datos almacena: sesiones, memorias, runs, knowledge metadata, trazas y más.

```python
from agno.db.sqlite import SqliteDb
from agno.db.postgres import PostgresDb

db = SqliteDb(db_file="tmp/app.db")
# o
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
```

---

### Tracing

**`agno.tracing`** — Sistema de observabilidad que registra cada run con sus pasos, herramientas usadas, tokens consumidos y tiempos de ejecución.

- Se integra con el `db` del AgentOS
- Visible desde el panel de AgentOS UI
- Permite debugging detallado de ejecuciones complejas (multi-agente, multi-paso)
- Los traces se pueden consultar via API: `GET /traces`

---

### Hooks

**`agno.hooks`** — Puntos de extensión del ciclo de vida del agente. Permiten ejecutar lógica custom antes/después de eventos clave sin modificar el agente en sí.

Hooks disponibles:
- `on_run_start` — antes de que comience un run
- `on_run_end` — cuando finaliza un run
- `on_tool_call` — cuando el agente invoca una herramienta
- `on_memory_update` — cuando se actualiza la memoria

Útiles para logging, auditoría, métricas custom, notificaciones, etc.

---

### Guardrails

**`agno.guardrails`** — Mecanismos de seguridad y control que filtran inputs/outputs del agente. Permiten:

- Bloquear contenido inapropiado o fuera de política
- Validar que las respuestas cumplan ciertos criterios
- Implementar filtros por categoría de contenido
- Aplicar límites de uso o rate limiting a nivel de agente

Se configuran declarativamente en el Agent y se ejecutan automáticamente en cada run.

---

### Models

**`agno.models`** — Adaptadores para distintos proveedores de LLM. Agno soporta:

| Módulo | Proveedor |
|--------|-----------|
| `agno.models.openai` | OpenAI (GPT-4o, GPT-5, etc.) |
| `agno.models.anthropic` | Anthropic (Claude 3.5, Claude 4, etc.) |
| `agno.models.google` | Google (Gemini) |
| `agno.models.groq` | Groq |
| `agno.models.lmstudio` | LM Studio (local) — clase dedicada |
| `agno.models.openai.like` | Cualquier endpoint OpenAI-compatible |
| `agno.models.ollama` | Modelos locales via Ollama |
| `agno.models.aws` | AWS Bedrock |
| `agno.models.azure` | Azure OpenAI |

Todos exponen la misma interfaz, lo que hace trivial cambiar de proveedor.

**Este proyecto — providers usados:**

```python
# Dev: LM Studio local (dos opciones equivalentes)
from agno.models.lmstudio import LMStudio          # clase dedicada (preferida)
from agno.models.openai.like import OpenAILike      # alternativa genérica, también válida

model_dev = LMStudio(id="qwen2.5-7b-instruct")
# base_url default: http://localhost:1234/v1 — no hace falta configurar si LM Studio corre local

# Alternativa con OpenAILike (útil si se necesita base_url custom)
model_dev = OpenAILike(
    id="qwen2.5-7b-instruct",
    base_url="http://localhost:1234/v1",
    api_key="not-provided",  # LM Studio no requiere key real
)

# Prod: Groq
from agno.models.groq import Groq
model_prod = Groq(id="llama-3.3-70b-versatile")
```

La selección dev/prod se centraliza en `infrastructure/llm/provider.py` — ningún agente instancia modelos directamente.

---

### Tools

**`agno.tools`** — Colección de herramientas listas para usar que los agentes pueden invocar. Permite a los agentes actuar sobre el mundo exterior.

Ejemplos incluidos en el SDK:
- `WebSearchTools` — búsqueda web
- `CalculatorTools` — operaciones matemáticas
- `HackerNewsTools` — scraping de HN
- `SQLTools` — queries a bases de datos
- `ReasoningTools` — herramientas de razonamiento explícito

También se pueden crear herramientas custom como funciones Python normales.

```python
from agno.tools.websearch import WebSearchTools
agent = Agent(tools=[WebSearchTools()])
```

---

### Knowledge

**`agno.knowledge`** — Sistema RAG (Retrieval-Augmented Generation) que permite a los agentes buscar en documentos propios antes de responder.

Componentes:
- `Knowledge` — contenedor principal, conecta vector DB con metadata DB
- `agno.vectordb` — backends vectoriales: ChromaDB, pgvector, Pinecone, etc.
- `agno.knowledge.embedder` — genera embeddings: `OpenAIEmbedder`, etc.

```python
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.chroma import ChromaDb
from agno.knowledge.embedder.openai import OpenAIEmbedder

knowledge = Knowledge(
    vector_db=ChromaDb(
        path="tmp/chroma",
        collection="docs",
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    contents_db=db,
)
```

---

## 2. AgentOS API Reference

AgentOS expone una API REST completa construida sobre FastAPI. A continuación se describen todos los grupos de endpoints.

---

### Overview

`GET /config` — Endpoint raíz que devuelve la configuración completa del AgentOS: ID, nombre, descripción, modelos disponibles, bases de datos, agentes, teams, workflows y configuración de las páginas (Chat, Memory, Knowledge, Evals, etc.).

---

### Home / Health

`GET /health` — Endpoint de health check. Devuelve el estado del servidor. Útil para load balancers, Kubernetes liveness probes y monitoreo de infraestructura.

---

### Core

Endpoints de configuración y estado general del sistema:
- `GET /config` — configuración completa del AgentOS
- `GET /health` — estado del servidor

---

### Agents

Endpoints para gestionar y ejecutar agentes:
- `GET /agents` — lista todos los agentes disponibles
- `GET /agents/{id}` — detalle de un agente específico
- `POST /agents/{id}/runs` — ejecuta un agente (no-streaming)
- `POST /agents/{id}/runs/stream` — ejecuta un agente con respuesta en streaming
- `GET /agents/{id}/sessions` — sesiones del agente
- `GET /agents/{id}/memories` — memorias asociadas al agente

---

### Teams

Endpoints para gestionar y ejecutar teams:
- `GET /teams` — lista todos los teams disponibles
- `GET /teams/{id}` — detalle de un team
- `POST /teams/{id}/runs` — ejecuta un team (no-streaming)
- `POST /teams/{id}/runs/stream` — ejecuta un team con streaming

---

### Workflows

Endpoints para gestionar y ejecutar workflows:
- `GET /workflows` — lista todos los workflows
- `GET /workflows/{id}` — detalle de un workflow
- `POST /workflows/{id}/runs` — ejecuta un workflow
- `POST /workflows/{id}/runs/stream` — ejecuta un workflow con streaming

---

### Slack

Integración nativa con Slack. AgentOS puede recibir mensajes de Slack y responder a través de agentes configurados. Los endpoints manejan el webhook de Slack y el protocolo de verificación de eventos.

---

### WhatsApp

Integración nativa con WhatsApp Business API. Permite que agentes respondan mensajes de WhatsApp directamente, habilitando chatbots conversacionales sobre la plataforma de mensajería.

---

### AGUI (Agent User Interface)

Protocolo estándar para comunicación entre el frontend y los agentes. Define el esquema de eventos SSE (Server-Sent Events) que usa el Agent UI de Agno. Permite conectar cualquier frontend compatible con el protocolo AGUI a un AgentOS.

---

### A2A (Agent-to-Agent)

Protocolo para comunicación entre agentes de distintos sistemas. Agno implementa el estándar **A2A Protocol** (a2a-protocol.org), lo que permite interoperabilidad con agentes de otros frameworks.

Endpoints expuestos automáticamente por agente/team/workflow:
- `GET /a2a/{type}/{id}/.well-known/agent-card.json` — metadata del agente en formato A2A
- `POST /a2a/{type}/{id}/v1/message:send` — ejecuta el agente (no-streaming)
- `POST /a2a/{type}/{id}/v1/message:stream` — ejecuta el agente con streaming

---

### Sessions

Endpoints para gestionar el historial de conversaciones:
- `GET /sessions` — lista todas las sesiones
- `GET /sessions/{id}` — detalle de una sesión
- `PATCH /sessions/{id}` — actualizar metadatos de sesión
- `DELETE /sessions/{id}` — eliminar una sesión

---

### Memory

Endpoints para gestionar las memorias de usuarios:
- `GET /memories` — lista memorias (filtrable por `user_id`, `db_id`)
- `POST /memories` — crear una memoria manual
- `PATCH /memories/{id}` — actualizar una memoria
- `DELETE /memories` — eliminar memorias

---

### Evals

Endpoints para gestionar evaluaciones de modelos y agentes:
- `GET /eval-runs` — lista todas las evals
- `GET /eval-runs/{id}` — detalle de una eval
- `POST /eval-runs` — crear una nueva eval run
- `PATCH /eval-runs/{id}` — actualizar estado de una eval
- `DELETE /eval-runs` — eliminar evals (filtrable por nombre)

---

### Metrics

Endpoints para monitoreo del sistema:
- `GET /metrics` — métricas del sistema (CPU, memoria, uso de tokens, etc.)
- `POST /metrics/refresh` — fuerza una actualización de las métricas

---

### Knowledge

Endpoints para gestionar el contenido de la knowledge base:
- `GET /knowledge` — lista los documentos/contenidos
- `POST /knowledge` — subir nuevo contenido
- `DELETE /knowledge/{id}` — eliminar contenido
- `POST /knowledge/search` — buscar en la knowledge base

---

### Traces

Endpoints para observabilidad y debugging:
- `GET /traces` — lista todas las trazas de ejecución
- `GET /traces/{id}` — detalle de una traza específica (pasos, herramientas, tokens, timing)

---

### Database

Endpoints para inspeccionar el estado de las bases de datos conectadas al AgentOS:
- `GET /databases` — lista las DBs configuradas
- `GET /databases/{id}` — detalle de una DB específica

---

### Components

Endpoints para listar todos los componentes registrados en el AgentOS (agentes, teams, workflows, knowledge bases, modelos). Útil para introspección del sistema.

---

### Registry

Registro central de componentes del AgentOS. Permite descubrir qué agentes, modelos y herramientas están disponibles en una instancia dada. Es la base del sistema de descubrimiento dinámico.

---

### Schedules

Endpoints para programar ejecuciones periódicas de agentes o workflows:
- `GET /schedules` — lista los schedules configurados
- `POST /schedules` — crear un nuevo schedule (cron-based)
- `DELETE /schedules/{id}` — eliminar un schedule

---

### Approvals

Sistema de aprobación humana para acciones de agentes que requieren validación antes de ejecutarse. Implementa el patrón **Human-in-the-Loop**:
- `GET /approvals` — lista aprobaciones pendientes
- `POST /approvals/{id}/approve` — aprobar una acción
- `POST /approvals/{id}/reject` — rechazar una acción

---

## 3. Agno Infra CLI

El CLI `ag infra` gestiona la infraestructura donde corre AgentOS. Pensado para deploys en la nube (AWS, GCP, etc.) usando herramientas IaC como Pulumi.

---

### `ag infra create`

Crea la infraestructura cloud desde cero (VPC, instancias, bases de datos, etc.) según la configuración definida. Equivale a un `pulumi up` inicial.

```bash
ag infra create
```

---

### `ag infra up`

Levanta los servicios/contenedores en la infraestructura ya creada. Similar a un `docker-compose up` pero sobre infra cloud. Usado para iniciar AgentOS después de `create`.

```bash
ag infra up
```

---

### `ag infra down`

Detiene los servicios corriendo en la infraestructura sin destruirla. Los recursos cloud siguen existiendo pero los procesos se apagan. Útil para mantenimiento.

```bash
ag infra down
```

---

### `ag infra restart`

Reinicia los servicios de AgentOS en la infraestructura. Equivale a `down` + `up`. Útil para aplicar cambios de configuración o recuperarse de un estado inconsistente.

```bash
ag infra restart
```

---

### `ag infra patch`

Aplica cambios incrementales a los recursos de infraestructura sin recrearlos. Útil para actualizar configuraciones, variables de entorno o versiones de imagen sin downtime completo.

```bash
ag infra patch
```

---

### `ag infra config`

Muestra o edita la configuración actual de la infraestructura: región, tipo de instancia, variables de entorno, secretos, etc.

```bash
ag infra config
```

---

### `ag infra delete`

**Destructivo** — Elimina completamente toda la infraestructura cloud creada. Borra VPC, instancias, bases de datos y todos los recursos asociados. Requiere confirmación explícita.

```bash
ag infra delete
```

---

## Resumen de Capas

```
┌─────────────────────────────────────────────────────────┐
│                     Tu Aplicación                        │
├─────────────────────────────────────────────────────────┤
│  Agno SDK  │  Agent · Team · Workflow · Tools · Memory   │
├─────────────────────────────────────────────────────────┤
│  AgentOS   │  FastAPI REST API · Sessions · Traces       │
├─────────────────────────────────────────────────────────┤
│  Infra CLI │  ag infra create/up/down/patch/delete        │
└─────────────────────────────────────────────────────────┘
```

- **Agno SDK** → código Python, lo que escribís en tus scripts y apps
- **AgentOS** → runtime de producción, expone REST API, gestión y observabilidad
- **Infra CLI** → aprovisionamiento de la infraestructura cloud donde corre AgentOS
