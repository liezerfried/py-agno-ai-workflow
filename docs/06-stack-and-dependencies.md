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
| `valid_categories.csv` | `data/` | 923 títulos únicos, generado por `scripts/` |

El archivo tiene 18.460 filas porque cada ocupación aparece una vez por cada ocupación relacionada.
Al extraer valores únicos de la columna `Title` se obtienen exactamente 923.

Script que genera el CSV:

```python
# scripts/build_valid_categories.py
import openpyxl, csv

wb = openpyxl.load_workbook("data/raw/related_ocuppations.xlsx")
ws = wb.active
titles = set()
for i, row in enumerate(ws.iter_rows(values_only=True)):
    if i == 0: continue
    titles.add(row[1])
with open("data/valid_categories.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["category"])
    for t in sorted(titles):
        writer.writerow([t])
```

---

## Capa de datos (Excel / CSV)

| Librería | Para qué | Por qué |
|----------|----------|---------|
| `openpyxl` | Leer y escribir `.xlsx` | Crítico: sin esto `IngestAgent` y `AuditWriter` no pueden abrir ni guardar el Excel del usuario |
| `pandas` | Transformar DataFrames | Extrae columnas, deduplica categorías, genera el reporte de cambios |
| `rapidfuzz` | Fuzzy matching de texto | Pre-filtro barato: score ≥ 0.90 → corrección automática sin gastar tokens de LLM |
| `duckdb` | SQL sobre CSV | `ValidatorAgent` consulta la tabla de categorías válidas con SQL estándar |

`rapidfuzz` corre **antes** de cada llamada al LLM — es un pre-filtro obligatorio, no opcional.
Score ≥ 0.90 → corrección automática. Score 0.70–0.89 → pasa al LLM. Score < 0.70 → human-in-the-loop.

---

## Capa de validación y schemas

`pydantic>=2.0` — Agno requiere v2; no degradar a v1.

Toda la salida de los agentes pasa por `output_schema` con modelos Pydantic.
Ningún agente devuelve texto libre — esto es un invariante del sistema.

---

## Capa de persistencia

| Librería | Para qué |
|----------|----------|
| `sqlalchemy` | Requerido por `PostgresDb` de Agno como dependencia interna |
| `psycopg[binary]` | Driver PostgreSQL para producción |
| `aiosqlite` | SQLite async para dev local (Agno lo usa internamente) |

`SqliteDb` en dev, `PostgresDb` en prod — configurado en `infrastructure/storage/sqlite.py`.

---

## Capa de UI — Chainlit

Chainlit es la interfaz visual del proyecto. Fue elegida sobre Streamlit y Gradio porque:

- Visualiza cada paso del agente en tiempo real (IngestAgent → ValidatorAgent → MapperAgent → AuditWriter).
- Muestra cada tool call mientras ocurre — el usuario ve el razonamiento del agente.
- Tiene autenticación e historial de sesiones integrados, señal de producción real.

```
pip install chainlit   →   NO usar
uv add chainlit        →   correcto
```

---

## Capa de API y runtime

| Librería | Para qué |
|----------|----------|
| `fastapi` | Requerido por `AgentOS` internamente — no se instancia manualmente |
| `uvicorn` | ASGI server — `uvicorn main:app --reload --port 7777` |
| `python-dotenv` | Carga `.env` en dev — `load_dotenv()` al inicio de `main.py` |
| `openai` | Requerido por Agno's `OpenAILike` y `LMStudio` para conectar con endpoints OpenAI-compatibles |

**Patrón de wiring correcto** — `AgentOS` genera la FastAPI app; no crear un `FastAPI()` manualmente:

```python
# main.py
from agno.os import AgentOS
from agno.db.sqlite import SqliteDb
from agents.workflow import onet_workflow

agent_os = AgentOS(
    id="onet-normalizer",
    workflows=[onet_workflow],
    db=SqliteDb(db_file="tmp/app.db"),
)

app = agent_os.get_app()  # ← esta es la FastAPI app que sirve uvicorn

if __name__ == "__main__":
    agent_os.serve(app="main:app", reload=True)
```

`openai` se necesita aunque el proveedor sea LMStudio — Agno usa el SDK de OpenAI
para comunicarse con cualquier API compatible con el protocolo OpenAI.

---

## Observabilidad — Agno built-in traces

El proyecto usa **Agno traces** exclusivamente. Zero-config, muestra el dashboard
en `os.agno.com`, y es coherente con el resto del stack.

No usar LangSmith — genera dependencia en un stack externo innecesario.

---

## Testing

La evaluation layer es lo que diferencia este portfolio de un proyecto sin métricas.

| Librería | Para qué |
|----------|----------|
| `pytest` | Framework de tests — `evaluation/test_agent_accuracy.py` |
| `pytest-asyncio` | Tests async (Agno usa async internamente) |
| `httpx` | Testear endpoints de FastAPI sin levantar el server |

```python
# evaluation/test_agent_accuracy.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_normalization_endpoint():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post("/agents/mapper/runs", json={"message": "prodctos"})
    assert response.status_code == 200
```

---

## Dev tooling

| Herramienta | Para qué | Comando |
|-------------|----------|---------|
| `uv` | Package manager | `uv sync` |
| `ruff` | Linter + formatter (reemplaza flake8 + black + isort) | `ruff check . && ruff format .` |

```toml
# pyproject.toml
[tool.ruff]
line-length = 100
target-version = "py312"
```

---

## pyproject.toml completo

```toml
[project]
name = "py-agno-ai-workflow"
version = "0.1.0"
requires-python = ">=3.12"

dependencies = [
    "agno>=1.0",
    "openai",               # requerido para LMStudio (OpenAI-compatible) y Groq en prod
    "pydantic>=2.0",
    "fastapi",
    "uvicorn",
    "chainlit",             # UI del agente — visualiza pasos en tiempo real
    "pandas",
    "openpyxl",             # leer/escribir Excel (.xlsx)
    "rapidfuzz",            # pre-filtro typos antes del LLM
    "duckdb",               # SQL sobre CSV de categorías válidas
    "sqlalchemy",           # requerido por PostgresDb de Agno
    "psycopg[binary]",      # driver PostgreSQL para producción
    "aiosqlite",            # SQLite async para dev
    "python-dotenv",        # cargar .env en dev
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
```

---

## Decisiones clave

- `openpyxl` es **crítico** — sin esto no se puede abrir ni guardar el Excel del usuario.
- `rapidfuzz` actúa como **pre-filtro obligatorio antes del LLM**: score ≥ 0.90 → corrección automática; score 0.70–0.89 → pasa al LLM; score < 0.70 → human-in-the-loop.
- `chainlit` fue elegida sobre Streamlit/Gradio porque visualiza los pasos del agente en tiempo real.
- `openai` se requiere aunque el proveedor sea LMStudio — Agno's `OpenAILike` depende del SDK.
- La fuente de `valid_categories` es **O*NET** (923 ocupaciones canónicas) — no se construye manualmente.
- `pytest + httpx` habilitan la evaluation layer que diferencia el portfolio.
- Observabilidad: **Agno traces** únicamente — coherente con el stack, visible en `os.agno.com`.
