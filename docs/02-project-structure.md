# Estructura del Proyecto

## Patrón de diseño

Estructura basada en el layout oficial de Agno, con dos extensiones propias:
`infrastructure/` (config de servicios externos) y `evaluation/` (métricas del agente).

Agno no impone capas como Clean Architecture — sus proyectos oficiales usan
carpetas planas al root. Eso hace que el código mapee directo a la documentación
y a los ejemplos del framework.

```
┌─────────────────────────────────────┐
│           API / Interfaces          │  ← FastAPI, Playground
├─────────────────────────────────────┤
│       Workflows / Teams             │  ← Orquestación con Step/Steps
├─────────────────────────────────────┤
│       Agents / Tools                │  ← Lógica de los agentes y Toolkits
├─────────────────────────────────────┤
│       Infrastructure                │  ← LLM provider, Storage, Observability
└─────────────────────────────────────┘
```

---

## Scaffold

```
py-agno-ai-agents/
│
├── agents/                          # Definiciones de agentes (Agno-nativo)
│   ├── ingest_agent.py              # Lee Excel, extrae categorías únicas
│   ├── validator_agent.py           # Compara contra DB de categorías válidas
│   ├── mapper_agent.py              # Fuzzy match + LLM para proponer correcciones
│   └── audit_writer.py             # Genera reporte de cambios + Excel corregido
│
├── workflows/                       # Orquestación con Step/Steps (Agno-nativo)
│   └── normalization_workflow.py   # Ingest → Validate → Map → Audit
│
├── teams/                           # Teams para colaboración multi-agente (Agno-nativo)
│
│
├── infrastructure/                  # Config de servicios externos (extensión propia)
│   ├── llm/
│   │   └── provider.py             # Modelo según ENV: LMStudio local / Groq cloud
│   ├── storage/
│   │   └── sqlite.py               # Persistencia entre pasos del workflow
│   └── observability/
│       └── traces.py               # Agno built-in traces / LangSmith
│
├── evaluation/                      # Evaluación del agente (extensión propia)
│   └── test_agent_accuracy.py      # Mide precision/recall de las correcciones
│
├── api/                             # Capa de entrega: FastAPI
│   └── routes.py
│
├── docs/                            # Documentación del proyecto
│   ├── 01-agno-core-concepts.md
│   ├── 02-project-structure.md     ← este archivo
│   ├── 03-market-research.md
│   └── 04-agent-orchestration-and-project-design.md
│
├── Dockerfile                       # Imagen de la app para deploy
├── compose.yml                      # Docker Compose: app + base de datos
├── playground.py                    # UI local de Agno para debug
├── main.py                          # Entry point
├── .env                             # API keys (NO commitear)
├── .env.example                     # Template de variables
├── pyproject.toml                   # Dependencias (equivalente a package.json)
└── requirements.txt                 # Generado desde pyproject.toml para Docker
```

---

## Por qué esta estructura y no Clean Architecture

Clean Architecture agrega capas (`domain/`, `application/`) que tienen sentido
en sistemas grandes con múltiples equipos. Para un proyecto de agentes con Agno:

- Los ejemplos oficiales del framework usan `agents/`, `teams/`, `workflows/` al root
- Menos indirección → más fácil seguir la documentación y debuggear
- `infrastructure/` alcanza para separar la config de servicios externos

Si el proyecto crece y necesita más separación, la migración a Clean Architecture
es directa — las carpetas ya tienen responsabilidades claras.

---

## Cómo funciona `infrastructure/llm/provider.py`

Este archivo es el único lugar donde se define qué modelo usa el proyecto.
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

En `.env` local: `ENV=development` → usa LMStudio.
En Render/Railway: `ENV=production` → usa Groq (o cualquier proveedor cloud).

---

## Equivalencias Python ↔ JavaScript

| Node / NPM          | Python              |
|---------------------|---------------------|
| `package.json`      | `pyproject.toml`    |
| `npm install`       | `uv sync`           |
| `node_modules/`     | `.venv/`            |
| `index.js` (módulo) | `__init__.py`       |
| `npx`               | `uvx`               |

---

## Flujo de datos del sistema

```
Input: Excel del usuario (con categorías potencialmente erróneas)
    ↓
normalization_workflow.py
    ├── Step 1: IngestAgent      →  lee el Excel, extrae categorías únicas
    ├── Step 2: ValidatorAgent   →  compara contra DB de categorías válidas
    ├── Step 3: MapperAgent      →  LLM matchea semánticamente con output_schema
    │                                 confidence ≥ 0.90  → corrección automática
    │                                 confidence 0.70–0.89 → needs_review = True
    │                                 confidence < 0.70  → human-in-the-loop
    └── Step 4: AuditWriter      →  genera Excel corregido + audit trail
                                         ↓
                                   Output: Excel limpio + reporte de cambios
```
