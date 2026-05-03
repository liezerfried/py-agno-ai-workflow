# Estructura del Proyecto

## Patrón de diseño

La estructura sigue el layout oficial de Agno, con dos extensiones propias:
`infrastructure/` (configuración de servicios externos) y `evaluation/` (métricas del agente).

Agno no impone capas como Clean Architecture — sus proyectos oficiales usan carpetas planas al root.
Esto hace que el código mapee directamente a la documentación y a los ejemplos del framework.

```
┌─────────────────────────────────────┐
│           API / Interfaces          │  ← FastAPI, Chainlit
├─────────────────────────────────────┤
│           Workflows                 │  ← Orquestación con Step/Steps
├─────────────────────────────────────┤
│         Agents / Tools              │  ← Lógica de los agentes y Toolkits
├─────────────────────────────────────┤
│         Infrastructure              │  ← LLM provider, Storage, Observability
└─────────────────────────────────────┘
```

---

## Scaffold

```
py-agno-ai-workflow/
│
├── agents/                          # Definiciones de agentes (Agno-nativo)
│   ├── ingest_agent.py              # Lee Excel, extrae categorías únicas
│   ├── validator_agent.py           # Compara contra DB de categorías válidas
│   ├── mapper_agent.py              # Fuzzy match + LLM para proponer correcciones
│   └── audit_writer.py             # Genera Excel corregido + audit trail
│
├── workflows/                       # Orquestación con Step/Steps (Agno-nativo)
│   └── normalization_workflow.py   # Ingest → Validate → Map → Audit
│
├── infrastructure/                  # Config de servicios externos (extensión propia)
│   ├── llm/
│   │   └── provider.py             # Modelo según ENV: LMStudio local / Groq cloud
│   ├── storage/
│   │   └── sqlite.py               # Persistencia entre pasos del workflow
│   └── observability/
│       └── traces.py               # Agno built-in traces (os.agno.com)
│
├── evaluation/                      # Evaluación del agente (extensión propia)
│   └── test_agent_accuracy.py      # Mide precision/hallucination_rate de las correcciones
│
├── pre_processor.py                 # Normalización sin LLM: casing, seniority, ruido
│
├── data/
│   ├── raw/
│   │   └── related_ocuppations.xlsx  # Fuente original O*NET (US Dept. of Labor)
│   └── valid_categories.csv          # 923 títulos canónicos, generado por scripts/
│
├── scripts/
│   └── build_valid_categories.py    # Extrae títulos de O*NET → valid_categories.csv
│
├── api/                             # Capa de entrega: FastAPI
│   └── routes.py
│
├── docs/                            # Documentación del proyecto
│   ├── 01-agno-core-concepts.md
│   ├── 02-project-structure.md     ← este archivo
│   ├── 03-market-research.md
│   ├── 04-agent-orchestration-and-project-design.md
│   ├── 06-stack-and-dependencies.md
│   ├── 07-implementation-and-validation-strategy.md
│   └── 08-business-context-and-human-in-the-loop.md
│
├── Dockerfile                       # Imagen de la app para deploy
├── compose.yml                      # Docker Compose: app + base de datos
├── app.py                           # Entry point de Chainlit (UI)
├── main.py                          # Entry point de FastAPI
├── .env                             # API keys (NO commitear)
├── .env.example                     # Template de variables
├── pyproject.toml                   # Dependencias (equivalente a package.json)
└── requirements.txt                 # Generado desde pyproject.toml para Docker
```

---

## Por qué esta estructura y no Clean Architecture

Clean Architecture agrega capas (`domain/`, `application/`) que tienen sentido en sistemas grandes
con múltiples equipos. Para un proyecto de agentes con Agno:

- Los ejemplos oficiales del framework usan `agents/`, `workflows/` al root — seguirlos reduce fricción.
- Menos indirección → más fácil seguir la documentación y debuggear.
- `infrastructure/` alcanza para separar la config de servicios externos.

Si el proyecto crece y necesita más separación, la migración es directa — las carpetas
ya tienen responsabilidades claras.

**Por qué no hay carpeta `teams/`:** el flujo es lineal y determinista (Ingest → Validate → Map → Audit).
El patrón Team resuelve routing dinámico entre agentes, que aquí no agrega valor. Sin él, hay
menos superficie para bugs y el audit trail es más simple de seguir.

---

## Flujo de datos del sistema

```
Input: Excel del usuario (con categorías potencialmente erróneas)
    ↓
normalization_workflow.py
    ├── Step 1: IngestAgent      →  lee el Excel, extrae categorías únicas
    ├── Step 2: ValidatorAgent   →  compara contra valid_categories.csv
    ├── Step 3: MapperAgent      →  pre_processor → rapidfuzz → LLM (si necesario)
    │                                 confidence ≥ 0.90  → corrección automática
    │                                 confidence 0.70–0.89 → LLM evalúa equivalencia
    │                                 confidence < 0.70  → human-in-the-loop
    └── Step 4: AuditWriter      →  genera Excel corregido + audit trail
                                         ↓
                                   Output: Excel limpio + reporte de cambios
```

Cada paso produce un resultado tipado con Pydantic v2. Ningún agente escribe texto libre —
toda la salida pasa por `output_schema` antes de llegar al siguiente paso.

---

## Cómo funciona `infrastructure/llm/provider.py`

Este archivo es el único lugar donde se decide qué modelo usa el proyecto.
Todos los agentes lo importan — ninguno sabe si el modelo es local o cloud:

```python
# infrastructure/llm/provider.py
import os

if os.getenv("ENV") == "production":
    from agno.models.groq import Groq
    model = Groq(id="llama-3.3-70b-versatile")
else:
    from agno.models.openai import OpenAILike
    model = OpenAILike(id="llama-3.2-3b", base_url="http://localhost:1234/v1")
```

En `.env` local: `ENV=development` → LMStudio (sin costo, sin red).
En Render/Railway: `ENV=production` → Groq cloud.

Cambiar de proveedor no requiere tocar ningún agente — solo este archivo.

---

## Equivalencias Python ↔ JavaScript

| Node / NPM          | Python              |
|---------------------|---------------------|
| `package.json`      | `pyproject.toml`    |
| `npm install`       | `uv sync`           |
| `node_modules/`     | `.venv/`            |
| `index.js` (módulo) | `__init__.py`       |
| `npx`               | `uvx`               |
