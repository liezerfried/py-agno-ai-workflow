# Stack y Dependencias del Proyecto

---

## Gestor de paquetes — uv

`uv` reemplaza `pip`, `venv` y `pip-tools` en un solo comando. Es el único gestor autorizado
en este proyecto — no usar `pip` para instalar dependencias.

| Acción | Comando |
|--------|---------|
| Instalar todas las dependencias | `uv sync` |
| Agregar una dependencia | `uv add nombre-paquete` |
| Agregar dependencia de dev | `uv add --dev nombre-paquete` |
| Crear entorno virtual | automático al correr `uv sync` |

---

## Capa de datos de referencia — O*NET

La fuente de verdad de categorías válidas es el archivo oficial del Departamento de Trabajo de EE.UU.:

| Archivo | Ubicación | Contenido |
|---------|-----------|-----------|
| `related_ocuppations.xlsx` | `data/raw/` | 923 ocupaciones canónicas + relaciones entre ellas |
| `valid_categories.csv` | `data/` | 923 títulos únicos, generado por `scripts/build_valid_categories.py` |

El archivo tiene 18.460 filas porque cada ocupación aparece una vez por cada ocupación relacionada.
Al extraer valores únicos de la columna `Title` se obtienen exactamente 923.

---

## Capa de datos (Excel / CSV)

| Librería | Para qué | Por qué |
|----------|----------|---------|
| `openpyxl` | Leer y escribir `.xlsx` | Crítico: `IngestAgent` y `AuditWriter` abren y guardan el Excel del usuario |
| `pandas` | Transformar DataFrames | Extrae columnas, deduplica categorías, genera el reporte de cambios |
| `rapidfuzz` | Fuzzy matching de texto | Pre-filtro obligatorio: score ≥ 0.90 → corrección automática sin gastar tokens |

`rapidfuzz` corre **antes** de cada llamada al LLM — no es opcional.
Score ≥ 0.90 → corrección automática. Score 0.70–0.89 → pasa al LLM. Score < 0.70 → TranslatorAgent, luego human-in-the-loop.

---

## Capa de validación y schemas

`pydantic>=2.0` — Agno requiere v2; no degradar a v1.

Toda la salida de los agentes pasa por `output_schema` con modelos Pydantic.
Ningún agente devuelve texto libre — esto es un invariante del sistema.

---

## Capa de LLM

| Librería | Para qué |
|----------|----------|
| `agno>=1.0` | Framework de agentes — `Agent`, `Workflow`, `Step`, `AgentOS` |
| `openai` | Requerido por Agno's `LMStudio` — usa el SDK de OpenAI para comunicarse con cualquier endpoint OpenAI-compatible |
| `groq>=1.2.0` | SDK de Groq para producción |

`openai` se necesita aunque el proveedor sea LMStudio — Agno usa el protocolo OpenAI
para conectarse con cualquier API compatible.

---

## Capa de observabilidad

| Librería | Para qué |
|----------|----------|
| `opentelemetry-api` | API estándar de OpenTelemetry para tracing |
| `opentelemetry-sdk` | Implementación del SDK de OTel |
| `openinference-instrumentation-agno` | Instrumentación específica de Agno para OTel |

Configurado en `app.py`:
```python
from agno.db.sqlite import SqliteDb
from agno.tracing import setup_tracing

setup_tracing(db=SqliteDb(db_file="tmp/traces.db"), batch_processing=True)
```

Las trazas se almacenan localmente en `tmp/traces.db` y se pueden visualizar en `os.agno.com`.
No usar LangSmith — genera dependencia en un stack externo innecesario.

---

## Capa de persistencia

| Librería | Para qué |
|----------|----------|
| `sqlalchemy` | Requerido por Agno internamente como ORM base |
| `psycopg[binary]` | Driver PostgreSQL para producción |
| `aiosqlite` | SQLite async para dev local (Agno lo usa internamente) |

SQLite en dev (`tmp/traces.db`), PostgreSQL disponible para prod via variables de entorno.

---

## Capa de UI — Chainlit

Chainlit es la interfaz visual del proyecto. Fue elegida sobre Streamlit y Gradio porque:

- Visualiza cada paso del agente en tiempo real con `cl.Step`.
- El usuario ve el progreso (IngestAgent → ValidatorAgent → MapperAgent → AuditWriter) sin esperar al final.
- Acepta file upload nativo con `cl.AskFileMessage`.

```bash
# Correcto
uv add chainlit

# No usar
pip install chainlit
```

---

## Capa de API y runtime

| Librería | Para qué |
|----------|----------|
| `fastapi` | Requerido por `AgentOS` internamente — no se instancia `FastAPI()` manualmente |
| `uvicorn` | ASGI server para servir `agent_os.py` |
| `python-dotenv` | Carga `.env` en dev |

**Patrón correcto para `agent_os.py`** — AgentOS genera la FastAPI app:

```python
from agno.agent.os import AgentOS

agent_os = AgentOS(workflows=[normalization_workflow])
app = agent_os.get_app()
```

---

## Testing

| Librería | Para qué |
|----------|----------|
| `pytest` | Framework de tests |
| `pytest-asyncio` | Tests async (Agno usa async internamente) |
| `httpx` | Testear endpoints de FastAPI/AgentOS sin levantar el server |
| `ruff` | Linter + formatter (reemplaza flake8 + black + isort) |

```bash
# Correr todos los tests
uv run pytest

# Correr solo tests sin llamadas reales al LLM
uv run pytest -m "not real_llm"
```

---

## Dev tooling

```bash
ruff check .     # lint
ruff format .    # format
```

```toml
# pyproject.toml
[tool.ruff]
line-length = 100
target-version = "py312"
```

---

## pyproject.toml actual

```toml
[project]
name = "py-agno-ai-workflow"
version = "0.1.0"
requires-python = ">=3.12"

dependencies = [
    "agno>=1.0",
    "openai",
    "pydantic>=2.0",
    "fastapi",
    "uvicorn",
    "chainlit",
    "pandas",
    "openpyxl",
    "rapidfuzz",
    "duckdb",
    "sqlalchemy",
    "psycopg[binary]",
    "aiosqlite",
    "python-dotenv",
    "groq>=1.2.0",
    "opentelemetry-api>=1.41.0",
    "opentelemetry-sdk>=1.41.0",
    "openinference-instrumentation-agno>=0.1.31",
]

[dependency-groups]
dev = [
    "pytest",
    "pytest-asyncio",
    "httpx",
    "ruff",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "real_llm: marks tests that make live LLM calls (deselect with -m 'not real_llm')",
]
```

---

## Decisiones clave

- `openpyxl` es **crítico** — sin esto no se puede abrir ni guardar el Excel del usuario.
- `rapidfuzz` actúa como **pre-filtro obligatorio antes del LLM**: score ≥ 0.90 → corrección automática; score 0.70–0.89 → LLM; score < 0.70 → human-in-the-loop.
- `chainlit` fue elegida sobre Streamlit/Gradio porque visualiza los pasos del agente en tiempo real.
- `openai` se requiere aunque el proveedor sea LMStudio — Agno's `LMStudio` depende del SDK de OpenAI.
- `duckdb` está instalado pero actualmente no se usa en el código — fue considerado para el `ValidatorAgent` y puede ser relevante en implementaciones futuras.
- Observabilidad: **Agno traces** únicamente — coherente con el stack, visible en `os.agno.com`.
