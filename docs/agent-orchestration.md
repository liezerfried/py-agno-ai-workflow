# Orquestación y Diseño del Proyecto

---

## 1. Qué es la orquestación de agentes

Orquestación es el mecanismo que define **cómo y en qué orden trabajan los agentes**.
Un agente solo no alcanza para tareas complejas: necesitás coordinar varios, definir
quién hace qué, y cómo fluye la información entre ellos.

### LangGraph vs Agno

| | LangGraph | Agno |
|---|---|---|
| Modelo mental | Grafo dirigido (nodos + aristas) | Workflow lineal (Steps en orden) o Team (routing dinámico) |
| Bueno para | Flujos condicionales complejos, ciclos | Pipelines predecibles, APIs REST, UI en tiempo real |
| Observabilidad | LangSmith (externo) | Agno traces (integrado, `os.agno.com`) |

**Este proyecto usa Agno Workflow** — el flujo es lineal y determinista (Ingest → Validate → Map → Audit). No hay decisión dinámica sobre qué agente llamar ni ciclos de retroalimentación.

---

## 2. Los 4 agentes: responsabilidades

```
Excel del usuario
    ↓
[1] IngestAgent         Lee el archivo, extrae categorías únicas
    ↓
[2] ValidatorAgent      Compara contra O*NET, detecta anomalías
    ↓
[3] MapperAgent         Corrige anomalías — rapidfuzz + LLM + review queue
    ↓
[4] AuditWriter         Escribe Excel corregido + audit log + review queue sheet
    ↓
Excel limpio
```

| Agente | Tipo real | Usa LLM | Responsabilidad única |
|--------|-----------|---------|----------------------|
| `IngestAgent` | Python (openpyxl) wrapped in `Step` | No | Leer Excel, extraer categorías únicas |
| `ValidatorAgent` | Python (rapidfuzz) wrapped in `Step` | No | Comparar contra O*NET, identificar anomalías |
| `MapperAgent` | Agno `Agent` con `output_schema=SemanticMatch` | Sí — solo banda 0.70–0.89 | Proponer correcciones con confianza escalonada |
| `AuditWriter` | Python (openpyxl) wrapped in `Step` | No | Generar Excel corregido + reporte |

`TranslatorAgent` es un sub-agente interno de `MapperAgent` — no es un Step del pipeline.
Se llama cuando un título score < 0.70, intenta normalizarlo (traducción/abreviatura), y
re-scorea. Si el score sube, sigue; si no, va a review queue.

---

## 3. Sistema de confianza escalonada

```
pre_processor → normaliza texto (casing, seniority, ruido) — sin LLM, sin costo

rapidfuzz compara texto contra O*NET:
    score ≥ 0.90   →  corrección automática (sin LLM, cero tokens)
    score 0.70–0.89 →  MapperAgent LLM evalúa equivalencia semántica
    score < 0.70   →  TranslatorAgent intenta normalizar, re-scorea
                       si sigue < 0.70 → needs_review=True, human-in-the-loop
```

`rapidfuzz` maneja typos de forma instantánea y sin consumir tokens. El LLM entra solo
cuando hay ambigüedad semántica — sinónimos, cambios de idioma, abreviaturas.
Esto reduce costos y latencia en datasets grandes.

---

## 4. Módulos de Agno usados en este proyecto

### Agent

La unidad base. Combina modelo de lenguaje, instrucciones y `output_schema`. En este proyecto
`MapperAgent` y `TranslatorAgent` son `Agent` reales con Pydantic schema de salida.

```python
from agno.agent import Agent
agent = Agent(
    name="MapperAgent",
    model=get_model(),
    output_schema=SemanticMatch,
    instructions=["..."],
)
```

### Workflow + Step

Orquesta los pasos con orden fijo. El `StepOutput.content` de cada Step es un JSON string
que alimenta el `StepInput` del siguiente.

```python
from agno.workflow import Step, StepInput, StepOutput

ingest_step    = Step(name="IngestAgent",    executor=ingest_executor)
validate_step  = Step(name="ValidatorAgent", executor=validator_executor)
map_step       = Step(name="MapperAgent",    executor=mapper_executor)
audit_step     = Step(name="AuditWriter",    executor=audit_executor)
```

Los ejecutores son funciones Python (`executor=`) que reciben `StepInput` y devuelven `StepOutput`,
lo que permite testearlos en aislamiento sin instanciar el Workflow completo.

### ¿Por qué Workflow y no Team?

| Criterio | Workflow (elegido) | Team |
|----------|--------------------|------|
| Orden de los pasos | Fijo y predecible | Dinámico |
| El output de A alimenta a B | Sí, siempre | No necesariamente |
| Audit trail por paso | Sí, nativo | No nativo |
| Necesitamos routing dinámico | No | Sí |

### Memory y Knowledge — por qué no aplican

- **Memory:** existe para chats multi-turno. Este pipeline es stateless — recibe un Excel, lo procesa, devuelve otro Excel. Cada ejecución es independiente.
- **Knowledge (RAG):** aplica cuando el contenido es no estructurado y extenso. Aquí la referencia es `valid_categories.csv` — 923 títulos exactos consultados con búsqueda exacta + rapidfuzz, más rápido y más auditable que embeddings.

### Storage / AgentOS

El proyecto usa `agno.db.sqlite.SqliteDb` para tracing (`tmp/traces.db`).
`agent_os.py` expone el pipeline como API REST via `AgentOS`.

---

## 5. Decisiones de arquitectura

### Responsabilidades únicas

Cada agente tiene una sola responsabilidad. Si `ValidatorAgent` falla, sabés exactamente
dónde está el error. Podés reemplazar un agente sin tocar los demás, y las métricas de
cada paso son independientes.

### TranslatorAgent como sub-agente (no Step)

`TranslatorAgent` podría haberse implementado dentro de `MapperAgent` directamente, pero
separarlo permite:
1. Testearlo en aislamiento con `set_agent()` (patrón de inyección)
2. Reemplazarlo sin tocar `MapperAgent` (por ejemplo, con una API de traducción externa)

### Invariante de no alucinación

El sistema tiene tres capas para evitar que el LLM invente títulos:

1. **`output_schema` con Pydantic** — Agno valida la respuesta del LLM contra el schema antes
   de que llegue al código del agente.
2. **`is_valid_onet_title()` en `MapperAgent`** — antes de aceptar la sugerencia del LLM,
   verifica que el título exista en `valid_categories.csv`.
3. **`is_valid_onet_title()` en `AuditWriter`** — última verificación antes de escribir
   cualquier corrección en el Excel de salida.

### Herramienta de evaluación

Los tests en `tests/` son la capa de evaluación del proyecto:
- `test_integration_golden_path.py` — pipeline completo sobre `golden_input.xlsx`, verifica
  que no haya alucinaciones y que toda corrección sea un título O*NET válido.
- `test_mapper.py` — verifica las decisiones de routing por banda de confianza.
- Marcador `real_llm` para separar tests que hacen llamadas reales al LLM.

---

## 6. Cómo detectar alucinaciones

Una alucinación en este contexto es cuando el agente propone una corrección que no existe
en `valid_categories.csv` — inventó una respuesta.

La defensa tiene tres capas:

1. **`output_schema` con Pydantic** — fuerza al agente a devolver JSON estructurado y
   validado. Si el output no cumple el schema, Agno lo rechaza.

2. **Validación en `MapperAgent`** — antes de aceptar la respuesta del LLM, verifica
   con `is_valid_onet_title()` que el título propuesto exista en la lista.

3. **Validación en `AuditWriter`** — segunda verificación antes de escribir en el Excel.
   Si el `MapperAgent` pasó algo inválido, el `AuditWriter` lo rechaza antes del output.
