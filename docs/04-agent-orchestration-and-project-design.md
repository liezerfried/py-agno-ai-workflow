# Orquestación, Diseño del Proyecto y Módulos de Agno

---

## 1. Qué es la orquestación de agentes

Orquestación es el mecanismo que define **cómo y en qué orden trabajan los agentes**.
Un agente solo no alcanza para tareas complejas — necesitás coordinar varios, decidir
quién hace qué, cuándo habla cada uno, y cómo se pasa información de uno al siguiente.

### LangChain / LangGraph vs Agno

Probablemente escuchaste mencionar LangChain, LangSmith y LangGraph. Son tres cosas
distintas del mismo ecosistema:

| Herramienta | Qué es |
|-------------|--------|
| **LangChain** | Framework base para construir con LLMs (cadenas, prompts, tools) |
| **LangSmith** | Plataforma de observabilidad — ver trazas, evaluar, debuggear |
| **LangGraph** | Orquestador de agentes usando el concepto de **grafo** (nodos + aristas) |

LangGraph piensa la orquestación como un diagrama de flujo: cada agente es un nodo,
y las conexiones entre ellos son aristas con condiciones. Es poderoso pero conceptualmente
más pesado — hay que pensar en grafos dirigidos, estados del grafo, ciclos, etc.

**Agno toma otro camino.** En vez de grafos, usa abstracciones más directas:

| Agno | Equivalente conceptual |
|------|----------------------|
| `Workflow` + `Step` | Flujo lineal predecible, como una receta de pasos |
| `Team` | Colaboración dinámica entre agentes especializados |
| `Agent` individual | Nodo simple con tools propias |

No es mejor ni peor que LangGraph — es más Pythónico, más directo, y para proyectos
de portfolio con flujos claros y predecibles, es la elección correcta.

---

## 2. Proyecto 1 vs Proyecto 2: qué cambia

### Proyecto 1 — Multi-Agent Research System (Mastra, TypeScript)

```
Input: "Investigar tema X"
    ↓
ResearcherAgent → busca fuentes en la web
    ↓
AnalystAgent → analiza y estructura hallazgos
    ↓
WriterAgent → genera reporte final en markdown
    ↓
Output: reporte.md
```

- **Framework:** Mastra (TypeScript)
- **Tipo de problema:** síntesis de información no estructurada
- **Lo que muestra al recruiter:** multi-agent, workflow, web search, output estructurado

---

### Proyecto 2 — Smart Data Normalization Agent (Agno, Python)

```
Input: archivo Excel con categorías potencialmente erróneas
    ↓
IngestAgent → extrae categorías únicas de la columna target
    ↓
ValidatorAgent → compara contra base de datos de categorías válidas
    ↓
MapperAgent → detecta errores y propone correcciones
    ↓
AuditWriter → aplica cambios, genera Excel corregido + reporte
    ↓
Output: Excel limpio + audit trail de cada corrección
```

- **Framework:** Agno (Python)
- **Tipo de problema:** calidad de datos empresarial (data quality / ETL con LLM)
- **Lo que muestra al recruiter:** datos reales, confianza escalonada, evaluation layer, deploy

**La diferencia clave entre ambos:** el proyecto 1 trabaja con texto libre (investigación).
El proyecto 2 trabaja con datos estructurados reales (Excel) que tienen un formato esperado
y un resultado verificable — podés medir objetivamente si el agente se equivocó o no.
Eso lo hace más enterprise y más evaluable.

---

## 3. Qué hace exactamente el proyecto actual

El problema que resuelve: **las empresas tienen sistemas que esperan datos en un formato
específico** (categorías con nombres exactos). Cuando un usuario carga un Excel con
errores de tipeo o categorías en otro idioma, el sistema rechaza el archivo o lo procesa
mal.

**Ejemplos concretos del problema:**

| Lo que el usuario cargó | Lo que el sistema espera | Error |
|------------------------|--------------------------|-------|
| `prodctos` | `productos` | typo |
| `Electrónica` | `electronics` | idioma incorrecto |
| `Ropa de Invierno` | `winter_clothing` | formato distinto |
| `celulares` | `mobile_phones` | sinónimo |

El agente recibe el Excel, detecta estos casos, propone la corrección y genera un
archivo limpio. Para cada corrección registra: qué cambió, cuánta confianza tuvo,
y qué método usó (matching automático, LLM, o intervención humana).

**El sistema de confianza escalonada:**

```
rapidfuzz compara texto plano:
    score ≥ 0.90  → corrección automática sin preguntar
    score 0.70–0.89 → corrección marcada como "revisar"

LLM evalúa semántica (sinónimos, idiomas, variantes):
    modelo decide si hay equivalencia semántica

    score < 0.70 → human-in-the-loop: pausa y espera confirmación
```

El `rapidfuzz` maneja typos baratos y rápido (sin consumir tokens del LLM).
El LLM entra solo cuando hay ambigüedad semántica — esto reduce costos y latencia.

---

## 4. Módulos de Agno: qué hace cada uno

### Agent
La unidad base. Un agente combina un modelo de lenguaje + tools + instrucciones.
Razona en un loop: recibe input → decide qué tool llamar → ejecuta → vuelve a razonar.

```python
from agno.agent import Agent
agent = Agent(
    name="ValidatorAgent",
    model=model,
    tools=[CategoryDBTools()],
    instructions="Comparás categorías del Excel contra la base de datos válida.",
)
```

---

### Team
Grupo de agentes especializados con un líder que delega. El líder decide en tiempo
real qué agente es el más adecuado para cada tarea.

Tres modos:
- `route` — el líder enruta cada tarea al agente más adecuado
- `broadcast` — todos los agentes reciben la tarea simultáneamente
- `coordinate` — orquestación colaborativa general (default)

**Para el proyecto actual no usamos Team** — el flujo es secuencial y predecible,
no necesitamos decisión dinámica sobre quién hace qué.

---

### Workflow + Step + Steps
Orquesta agentes en pasos con orden definido. El output de cada `Step` es el
input del siguiente. Genera audit trail automático de cada paso.

```python
from agno.workflow.step import Step
from agno.workflow.steps import Steps
from agno.workflow.workflow import Workflow

ingest_step = Step(name="ingest", agent=ingest_agent)
validate_step = Step(name="validate", agent=validator_agent)
map_step = Step(name="map", agent=mapper_agent)
audit_step = Step(name="audit", agent=audit_writer)

normalization_sequence = Steps(
    name="normalization",
    steps=[ingest_step, validate_step, map_step, audit_step],
)

workflow = Workflow(
    name="Data Normalization Workflow",
    steps=[normalization_sequence],
)
```

---

### Tools / Toolkit
Las capacidades concretas que puede ejecutar un agente. Agno incluye más de 100
toolkits nativos — el primer paso siempre es verificar si lo que necesitás ya
existe (ver lista completa en `01-agno-core-concepts.md`).

Para este proyecto todos los toolkits son nativos:
- `CsvTools` — leer y escribir archivos CSV (ingest y output)
- `DuckDbTools` — ejecutar SQL sobre el CSV de categorías válidas
- `output_schema` con Pydantic — el LLM matchea semánticamente y retorna JSON validado

---

### Memory
Historial de conversación del agente. Con `add_history_to_context=True` el agente
recuerda lo que dijo antes dentro de la misma sesión. Útil para chatbots y
conversaciones multi-turno. Para el proyecto actual no es crítico (cada run
procesa un Excel nuevo), pero es relevante para el proyecto 1.

---

### Knowledge (RAG)
Base de conocimiento vectorial. Cargás documentos (PDFs, URLs, texto) y el agente
puede buscar en ellos semánticamente. Internamente usa embeddings + vector database
(ChromaDB, LanceDB, etc.).

Para el proyecto actual, la "base de categorías válidas" es una SQLite simple —
no necesitamos RAG. RAG entra cuando el contenido es no estructurado y extenso.

---

### Storage / db
Persistencia de sesiones y estado entre runs. Con `SqliteDb` o `PostgreSQL` el
agente guarda historial de conversaciones, métricas, y resultados de evaluaciones.

```python
from agno.db.sqlite import SqliteDb
db = SqliteDb(db_file="tmp/agents.db")
agent = Agent(model=model, db=db)
```

---

### AgentOS
Runtime de producción que convierte tus agentes en una API FastAPI + interfaz web.
Es el equivalente a Mastra Studio pero de Agno.

```python
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

agent_os = AgentOS(
    agents=[mi_agente],
    interfaces=[AGUI(agent=mi_agente)],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="playground:app", reload=True, port=9001)
```

Levantás esto con `python playground.py` y tenés una UI de chat en
`http://localhost:9001`. Desde ahí podés hablar con el agente, ver las tool calls
en tiempo real, y monitorear métricas.

---

### AGUI
La interfaz web que usa AgentOS. Es el "estudio" visual que te permite:
- Chatear con el agente directamente
- Ver qué tools llamó y con qué argumentos
- Revisar si las respuestas son coherentes
- Ver métricas de tokens y latencia

---

### Evaluaciones (AccuracyEval)
Agno tiene un sistema de evaluación para medir objetivamente si el agente responde
bien. Para el proyecto de normalización, vas a poder crear un dataset de prueba
con 20-30 casos conocidos (input con error → output esperado) y medir precision/recall:

```python
from agno.eval.accuracy import AccuracyEval

evaluation = AccuracyEval(
    db=db,
    name="Normalization Accuracy",
    model=model,
    input="productos, electrónica, ropa invierno",
    expected_output="products, electronics, winter_clothing",
    agent=normalization_agent,
)
evaluation.run(print_results=True)
```

---

## 5. Arquitectura del proyecto: decisiones de diseño

### ¿Cuántos agentes?

**4 agentes especializados**, uno por responsabilidad:

| Agente | Responsabilidad única |
|--------|----------------------|
| `IngestAgent` | Leer el Excel y extraer categorías únicas — no hace nada más |
| `ValidatorAgent` | Comparar contra DB de válidas e identificar anomalías |
| `MapperAgent` | Proponer correcciones (rapidfuzz + LLM + human-loop) |
| `AuditWriter` | Generar el Excel corregido y el reporte de cambios |

Tener 4 agentes con responsabilidades únicas tiene ventajas concretas:
- Si `ValidatorAgent` falla, sabés exactamente dónde está el error
- Podés reemplazar o mejorar un agente sin tocar los demás
- Las métricas de cada paso son independientes

---

### ¿Workflow o Team?

**Workflow.** Las razones:

| Criterio | Workflow | Team |
|----------|----------|------|
| Orden de los pasos | Fijo y predecible | Dinámico |
| El output de A alimenta a B | Sí, siempre | No necesariamente |
| Necesitamos audit trail por paso | Sí | No nativo |
| El flujo puede cambiar en runtime | No | Sí |

El flujo del proyecto es siempre: ingest → validate → map → audit. No hay decisión
dinámica sobre qué agente llamar. Eso es un Workflow.

---

### ¿Qué tools necesitamos?

Todos los toolkits son nativos de Agno — no hay nada custom que construir:

| Agente | Toolkit nativo | Import | Para qué |
|--------|---------------|--------|----------|
| `IngestAgent` | `CsvTools` | `agno.tools.csv_toolkit` | Leer CSV/Excel, extraer categorías únicas |
| `ValidatorAgent` | `DuckDbTools` | `agno.tools.duckdb` | SQL sobre el CSV de categorías válidas |
| `MapperAgent` | `output_schema` + Pydantic | nativo en `Agent` | El LLM matchea semánticamente y devuelve JSON validado |
| `AuditWriter` | `CsvTools` (write) | `agno.tools.csv_toolkit` | Escribir el CSV corregido con los cambios |

**Por qué sí usamos `rapidfuzz` como pre-filtro:** antes de gastar tokens del LLM,
rapidfuzz compara caracteres y detecta typos obvios (score ≥ 0.90) de forma
instantánea y sin costo. El LLM entra solo cuando rapidfuzz no alcanza —
sinónimos, cambios de idioma, abreviaturas. Esto reduce costos y latencia
significativamente en datasets grandes.

El flujo es: rapidfuzz primero → LLM solo si el score está entre 0.70 y 0.89 →
human-in-the-loop si score < 0.70.

---

## 6. Cómo probar el proyecto

Agno tiene cuatro modos de testing, de más simple a más completo:

### Modo 1 — CLI interactivo (terminal)

```python
# en cualquier agente
agent.cli_app(stream=True)
```

Levantás una conversación en la terminal. Útil para testear un agente específico
rápido sin levantar nada extra.

---

### Modo 2 — AgentOS + AGUI (UI web local)

```python
# playground.py — ya está en el scaffold
agent_os.serve(app="playground:app", reload=True, port=9001)
```

Ejecutás `python playground.py` y abrís `http://localhost:9001` en el browser.
Desde ahí podés interactuar con el agente visualmente, ver tool calls, respuestas,
y métricas de tokens en tiempo real.

Para conectar el dashboard externo:
1. Entrás a `os.agno.com`
2. Agregás una instancia nueva → seleccionás "Local"
3. Ponés la URL `http://localhost:9001`
4. Desde ahí ves el estado de los agentes, sesiones activas, y logs

---

### Modo 3 — debug_mode en el código

```python
agent = Agent(
    model=model,
    tools=[ExcelTools()],
    debug_mode=True,   # imprime cada tool call y su resultado
)
```

Con `debug_mode=True` el agente imprime en consola cada vez que llama una tool,
con qué argumentos, y qué devolvió. Útil para detectar alucinaciones o tool calls
incorrectos durante el desarrollo.

---

### Modo 4 — Evaluación automática (evaluation/)

```python
# evaluation/test_agent_accuracy.py
evaluation = AccuracyEval(
    db=db,
    name="Normalization Test",
    model=model,
    input="prodctos, elctronica, ropas",
    expected_output="products, electronics, clothing",
    agent=normalization_agent,
    num_iterations=3,
)
evaluation.run(print_results=True)
```

Esto corre el agente N veces sobre el mismo input y mide cuántas veces acertó.
Los resultados quedan en la DB y se pueden consultar vía la API de AgentOS
(`http://localhost:9001/eval-runs`).

---

## 7. Cómo detectar alucinaciones

Una "alucinación" en este contexto es cuando el agente corrige una categoría
por algo que no existe en la base de datos válida — inventó una respuesta.

La defensa tiene tres capas:

1. **Siempre validar el output del MapperAgent contra la DB** antes de escribir
   el Excel corregido — el `AuditWriter` verifica que cada corrección propuesta
   exista en la lista de categorías válidas.

2. **`output_schema` con Pydantic** — forzar al agente a devolver un JSON
   estructurado y validado. Si el output no cumple el schema, Agno lo rechaza.

3. **Evaluaciones con casos conocidos** — el dataset de prueba en `evaluation/`
   tiene los outputs esperados. Si el agente empieza a inventar, los tests lo
   detectan antes de que llegue a producción.
