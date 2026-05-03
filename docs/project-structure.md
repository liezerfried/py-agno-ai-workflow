# Estructura del Proyecto

## Patrón de diseño

La estructura sigue el layout de Agno con dos capas propias: `infrastructure/` (plomería técnica
compartida entre agentes) y `domain/` (reglas de negocio puras sin dependencias de framework).

Agno no impone Clean Architecture — sus proyectos oficiales usan carpetas planas al root.
Esto hace que el código mapee directamente a la documentación oficial y a los ejemplos del framework.

```
┌─────────────────────────────────────┐
│          UI / API                   │  ← Chainlit (app.py), AgentOS (agent_os.py)
├─────────────────────────────────────┤
│          Workflows                  │  ← Orquestación: normalization_workflow.py
├─────────────────────────────────────┤
│          Agents                     │  ← 4 steps + helpers (pre_processor, translator)
├─────────────────────────────────────┤
│          Domain                     │  ← Reglas de negocio (onet.py)
├─────────────────────────────────────┤
│          Infrastructure             │  ← LLM provider, pipeline contracts, step I/O
└─────────────────────────────────────┘
```

---

## Scaffold actual

```
py-agno-ai-workflow/
│
├── agents/
│   ├── ingest_agent.py           Step 1: lee Excel (openpyxl), extrae categorías únicas
│   ├── validator_agent.py        Step 2: compara contra O*NET con rapidfuzz, detecta anomalías
│   ├── mapper_agent.py           Step 3: rapidfuzz + LLM — corrige o escala a review queue
│   ├── mapping_pipeline.py       Helpers de scoring: score(), routing_band() — usados por mapper
│   ├── pre_processor.py          Normalización sin LLM: seniority, casing, ruido
│   ├── translator_agent.py       Sub-agente de mapper: traduce/expande antes de re-scorear
│   └── audit_writer_agent.py     Step 4: escribe Excel corregido + audit log + review queue
│
├── domain/
│   └── onet.py                   is_valid_onet_title() — única fuente de verdad del negocio
│
├── infrastructure/
│   ├── llm/
│   │   └── provider.py           get_model() — factory LLM; todos los agentes importan de acá
│   └── pipeline/
│       ├── contracts.py          CategoryValidation — contrato entre ValidatorAgent y MapperAgent
│       ├── session.py            PipelineSession — typed wrapper del session_state de Agno
│       └── step_io.py            ok(), fail(), deserialize() — I/O entre Steps del Workflow
│
├── workflows/
│   ├── normalization_workflow.py load_valid_categories() — carga valid_categories.csv
│   └── pipeline.py               PipelineError — error type del workflow
│
├── data/
│   ├── valid_categories.csv      923 títulos O*NET canónicos (generado por scripts/)
│   └── raw/
│       └── related_ocuppations.xlsx  Fuente original O*NET (US Dept. of Labor)
│
├── tests/
│   ├── conftest.py               Fixtures compartidos: Excel fake, stub LLM
│   ├── fixtures/
│   │   └── golden_input.xlsx     4 filas estáticas que cubren los casos clave
│   ├── domain/
│   │   └── test_onet.py          Tests de is_valid_onet_title()
│   ├── test_pre_processor.py     Tests de normalización de texto
│   ├── test_validator.py         Tests de ValidatorAgent
│   ├── test_mapper.py            Tests de MapperAgent por banda de confianza
│   ├── test_mapping_pipeline.py  Tests de score() y routing_band()
│   ├── test_translator.py        Tests de TranslatorAgent en aislamiento
│   ├── test_column_detection.py  Tests de detección automática de columna en Excel
│   ├── test_integration_pipeline.py   Pipeline end-to-end con 4 agentes
│   ├── test_integration_golden_path.py  Pipeline sobre golden_input.xlsx estático
│   ├── test_integration_seams.py  Serialización/deserialización entre Steps
│   └── test_smoke.py             Imports sin errores de startup
│
├── scripts/
│   ├── build_valid_categories.py Genera valid_categories.csv desde el Excel O*NET
│   ├── audit_collisions.py       Verifica colisiones fuzzy en la lista de categorías
│   └── generate_test_files.py    Genera Excel de muestra para testing
│
├── docs/                         Documentación del proyecto
├── tmp/                          Runtime: uploads y outputs (no es código, en .gitignore)
│
├── app.py                        Entry point 1: Chainlit web UI
├── agent_os.py                   Entry point 2: REST API via AgentOS
├── pyproject.toml                Dependencias del proyecto (uv)
└── .env.example                  Template de variables de entorno
```

---

## Por qué esta estructura

| Decisión | Razón |
|----------|-------|
| `agents/` al root | Los ejemplos oficiales de Agno usan este layout — reduce fricción al leer docs |
| `domain/onet.py` separado | La función `is_valid_onet_title()` la llaman tanto `mapper_agent` como `audit_writer_agent`; centralizarla evita duplicación |
| `infrastructure/pipeline/` | Plomería técnica que los 4 agentes necesitan — `PipelineSession`, `ok()`, `deserialize()` — sin repetirla en cada archivo |
| Sin carpeta `teams/` | El flujo es lineal y determinista; Team resuelve routing dinámico, que acá no agrega valor |
| Sin carpeta `evaluation/` | Los tests viven en `tests/`; no hay capa de evaluación separada en la implementación actual |
| `translator_agent.py` en `agents/` | Es un sub-agente de `MapperAgent`, no un Step del pipeline; vive en `agents/` porque usa el mismo patrón de inyección que los demás |

---

## Flujo de datos

```
Usuario sube Excel
    ↓
app.py  →  lee valid_categories.csv  →  guarda Excel en tmp/uploads/
    ↓
[Step 1] IngestAgent
    Lee el Excel con openpyxl
    Extrae categorías únicas → IngestResult (JSON)
    ↓
[Step 2] ValidatorAgent
    Compara cada categoría contra valid_categories.csv con rapidfuzz
    Devuelve ValidatorResult con lista de anomalías (JSON)
    ↓
[Step 3] MapperAgent
    Para cada anomalía:
      pre_processor → normaliza texto
      score() → rapidfuzz contra O*NET
      ≥ 0.90  → auto-corrección directa
      0.70–0.89 → LLM evalúa equivalencia semántica
      < 0.70  → TranslatorAgent intenta normalizar, re-scorea
                 si sigue < 0.70 → needs_review=True
    Devuelve MappingResult (JSON)
    ↓
[Step 4] AuditWriter
    Verifica cada corrección con is_valid_onet_title()
    Escribe Excel con hoja "Corrected" + hoja "Review Queue"
    Devuelve AuditResult con métricas
    ↓
app.py muestra resultado al usuario
```

---

## Cómo funciona `infrastructure/llm/provider.py`

Es el único lugar donde se decide qué modelo usa el proyecto.
Todos los agentes importan `get_model()` — ninguno instancia `LMStudio` o `Groq` directamente.

```python
# infrastructure/llm/provider.py
def get_model():
    provider = os.getenv("LLM_PROVIDER", "lmstudio").lower()
    if provider == "groq":
        return Groq(id=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))
    return LMStudio(id=os.getenv("LMSTUDIO_MODEL", "qwen/qwen3.5-9b"))
```

En dev: `LLM_PROVIDER` no seteada → LMStudio local (sin costo, sin red).
En producción: `LLM_PROVIDER=groq` → Groq cloud con llama-3.3-70b.

---

## Equivalencias Python ↔ JavaScript

| Node / NPM          | Python              |
|---------------------|---------------------|
| `package.json`      | `pyproject.toml`    |
| `npm install`       | `uv sync`           |
| `node_modules/`     | `.venv/`            |
| `index.js` (módulo) | `__init__.py`       |
| `npx`               | `uvx`               |
