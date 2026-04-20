# Stack y Dependencias del Proyecto

---

## Gestor de paquetes — uv (no pip)

`uv` es el gestor oficial del proyecto. Reemplaza `pip`, `venv` y `pip-tools` en un solo comando.
**No usar `pip` para instalar dependencias del proyecto** — solo para instalaciones puntuales fuera del entorno.

| Acción | Comando |
|--------|---------|
| Instalar todas las dependencias | `uv sync` |
| Agregar una dependencia nueva | `uv add nombre-paquete` |
| Agregar dependencia de dev | `uv add --dev nombre-paquete` |
| Crear entorno virtual | automático al correr `uv sync` |

---

## Capa de datos (Excel / CSV)

El proyecto gira alrededor de Excel. Sin esto no arranca:

| Librería | Para qué | Por qué |
|----------|----------|---------|
| `openpyxl` | Leer y escribir `.xlsx` | Agno's `CsvTools` no maneja Excel nativo — necesitás esto para que `IngestAgent` y `AuditWriter` abran/guarden el archivo real |
| `pandas` | Transformar DataFrames | Agno lo usa internamente en `PandasTools` y `CsvTools`; extraer columnas, deduplicar categorías, generar el reporte de cambios |
| `rapidfuzz` | Fuzzy matching de texto | Pre-filtro barato: con 1 línea filtrás typos obvios (score ≥ 0.95) antes de gastar tokens de LLM. Reduce costos significativamente en datasets grandes |
| `duckdb` | SQL sobre CSV | Para el `ValidatorAgent` sobre la tabla de categorías válidas |

---

## Capa de validación y schemas

`pydantic` — ya está en el plan con `output_schema`. Asegurarse de usar **Pydantic v2** (Agno requiere v2).

---

## Capa de persistencia

| Librería | Para qué |
|----------|----------|
| `sqlalchemy` | Agno's `PostgresDb` lo requiere como dependencia |
| `psycopg[binary]` | Driver PostgreSQL para producción |
| `aiosqlite` | SQLite async para dev local (Agno lo usa internamente) |

`SqliteDb` para dev y `PostgresDb` para prod — como está en `infrastructure/storage/sqlite.py`.

---

## Capa de UI — Chainlit

Chainlit es la interfaz visual del proyecto. Fue elegida sobre Streamlit y Gradio porque:
- Visualiza los pasos del agente automáticamente (IngestAgent → ValidatorAgent → MapperAgent → AuditWriter)
- Muestra cada tool call en tiempo real — el recruiter ve el razonamiento del agente
- Tiene autenticación y historial de sesiones integrados (señal de producción real)
- Es el framework de más crecimiento en AI Engineer job postings 2026

```
pip install chainlit   →   NO usar
uv add chainlit        →   correcto
```

---

## Capa de datos de referencia — O*NET

La lista `valid_categories` viene del archivo oficial del Departamento de Trabajo de EE.UU.:

| Archivo | Ubicación | Contenido |
|---------|-----------|-----------|
| `Related Occupations.xlsx` | raíz del proyecto | 923 ocupaciones canónicas + relaciones entre ellas |
| `data/valid_categories.csv` | generado por script | 923 títulos únicos extraídos de la columna `Title` |

El archivo tiene 18.460 filas porque cada ocupación aparece múltiples veces
(una por cada ocupación relacionada). Al extraer valores únicos de `Title` → 923.

Script que genera el CSV:

```python
# scripts/build_valid_categories.py
import openpyxl, csv

wb = openpyxl.load_workbook("Related Occupations.xlsx")
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

## Capa de API y runtime

| Librería | Para qué |
|----------|----------|
| `uvicorn` | ASGI server para FastAPI / AgentOS — `uvicorn main:app --reload` |
| `python-dotenv` | Cargar `.env` en dev — `load_dotenv()` al inicio de `main.py` |

---

## Testing

La evaluation layer es lo que diferencia el portfolio (ver `03-market-research.md`).

| Librería | Para qué |
|----------|----------|
| `pytest` | Framework de tests — `evaluation/test_agent_accuracy.py` |
| `pytest-asyncio` | Tests async (Agno usa async internamente) |
| `httpx` | Testear los endpoints de FastAPI sin levantar el server |

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
| `ruff` | Linter + formatter en uno (reemplaza flake8 + black + isort) | `ruff check . && ruff format .` |

```toml
# pyproject.toml
[tool.ruff]
line-length = 100
target-version = "py312"
```

---

## Observabilidad — elegir uno

| Opción | Cuándo elegirla |
|--------|----------------|
| **Agno built-in traces** | Zero-config, muestra el dashboard de `os.agno.com` en el portfolio — más integrado con el stack |
| **LangSmith** | Si se aplica a empresas que usan LangChain/LangSmith — más reconocible en CVs enterprise |

Para portfolio: **Agno traces** es más coherente con el stack actual.

---

## Proyecto 1 — Mastra / TypeScript (stack separado)

| Herramienta | Para qué |
|-------------|----------|
| **TypeScript** + **Node.js 22** | Lenguaje del proyecto 1 |
| **Mastra** | Framework agent TypeScript |
| **Zod** | Equivalente a Pydantic — output schema validation en TS |
| **Vitest** | Testing en TypeScript (más rápido que Jest) |
| **tsx** | Ejecutar TypeScript directo sin compilar en dev |

---

## pyproject.toml completo

```toml
[project]
name = "py-agno-ai-agents"
version = "0.1.0"
requires-python = ">=3.12"

dependencies = [
    "agno>=1.0",
    "openai",               # requerido para LMStudio (usa API compatible OpenAI) y Groq en prod
    "pydantic>=2.0",
    "fastapi",
    "uvicorn",
    "chainlit",             # UI del agente — visualiza pasos en tiempo real
    "pandas",
    "openpyxl",             # leer/escribir Excel (.xlsx)
    "rapidfuzz",            # pre-filtro typos antes del LLM (ver nota)
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

- `openpyxl` es **crítico** — sin esto no se puede abrir ni guardar el Excel del usuario
- `rapidfuzz` actúa como **pre-filtro antes del LLM**: score ≥ 0.90 → corrección automática sin gastar tokens; score 0.70–0.89 → pasa al LLM; score < 0.70 → human-in-the-loop. El doc `04` tenía una contradicción que decía "no necesitamos rapidfuzz" — eso fue corregido: sí se usa.
- `chainlit` es la UI elegida sobre Streamlit/Gradio — visualiza pasos del agente en tiempo real, señal de producción real en portfolios 2026
- `openai` se requiere aunque el proveedor sea LMStudio — Agno usa `OpenAILike` que depende del SDK de OpenAI para la comunicación con la API local de LMStudio
- La fuente de `valid_categories` es **O*NET** (`Related Occupations.xlsx`, 923 ocupaciones canónicas) — no se construye manualmente
- `pytest + httpx` habilitan la **evaluation layer** que diferencia el portfolio según el market research
- No usar LangSmith y Agno traces simultáneamente — elegir uno y mostrarlo bien
