# Agno Core Concepts

Source: https://docs.agno.com

---

## Los 3 bloques fundamentales

### 1. Agent (unidad básica)
Un agente individual que combina:
- Un modelo de lenguaje (Claude, GPT, etc.)
- Tools (capacidades: buscar web, leer archivos, ejecutar código)
- Memory (historial de conversación)
- Knowledge (base de conocimiento / RAG)

**Cuándo usar un solo Agent:**
- La tarea cabe en un dominio de expertise
- Querés minimizar costos de tokens
- Estás empezando — siempre empezar simple

---

### 2. Team (colaboración dinámica)
Una colección de agentes especializados que trabajan juntos.
Un "team leader" delega tareas a los miembros según sus roles.

**Modos de colaboración (TeamMode):**

| Modo | Comportamiento |
|------|---------------|
| `route` | El líder dirige cada tarea al agente más adecuado |
| `broadcast` | La tarea se delega a TODOS los miembros simultáneamente |
| `coordinate` | Modo por defecto — orquestación general colaborativa |

**Cuándo usar un Team:**
- La tarea requiere múltiples especialistas con tools distintas
- El contexto de un solo agente se queda corto
- Querés agentes enfocados en dominios muy específicos

**Importante:** Un Team NO es prerequisito para un Workflow. Son independientes.

---

### 3. Workflow (ejecución predecible)
Orquesta agentes, teams y funciones Python como una colección de pasos.

Los pasos pueden ejecutarse:
- Secuencialmente (uno tras otro)
- En paralelo
- En loops
- Condicionalmente (if/else)

El output de cada paso fluye como input del siguiente.

**Ventaja enterprise:** cada paso queda registrado automáticamente en un audit trail —
fundamental para compliance y debugging en producción.

**Cuándo usar un Workflow:**
- Necesitás ejecución predecible y repetible
- Querés audit trail (registro de cada paso)
- El proceso tiene pasos claros con inputs/outputs definidos

**Cuándo usar un Team en cambio:**
- Necesitás resolución flexible y adaptativa
- La interacción entre agentes debe ser orgánica

---

## Resumen de decisión

```
¿Tarea simple de un dominio?         → Agent
¿Múltiples especialistas colaborando? → Team
¿Proceso secuencial predecible?       → Workflow
¿Proceso complejo con especialistas
  en pasos definidos?                 → Workflow con Teams como pasos
```

---

## Tools en Agno

Agno incluye más de 100 toolkits nativos listos para usar. El primer paso siempre
es revisar si lo que necesitás ya existe — construir un toolkit custom es el
último recurso, no el primero.

### Toolkits nativos más relevantes para proyectos de datos

```python
from agno.tools.csv_toolkit import CsvTools    # leer, consultar y escribir CSV
from agno.tools.duckdb import DuckDbTools      # SQL sobre archivos CSV/Parquet
from agno.tools.pandas import PandasTools      # manipulación de DataFrames
from agno.tools.file import FileTools          # operaciones sobre archivos locales
from agno.tools.python import PythonTools      # ejecutar código Python dinámico
```

### CsvTools — leer y escribir archivos de datos

```python
from agno.tools.csv_toolkit import CsvTools
from pathlib import Path

agent = Agent(
    tools=[CsvTools(csvs=[Path("data/input.csv")])],
    instructions=[
        "Primero listá los archivos disponibles",
        "Luego revisá las columnas",
        "Ejecutá queries para responder la pregunta",
    ],
)
```

Por defecto CsvTools habilita lectura y consulta. Para habilitar escritura:

```python
CsvTools(csvs=[Path("data/input.csv")], enable_create_csv=True)
```

### DuckDbTools — SQL directo sobre archivos

Permite ejecutar queries SQL sobre CSV sin necesidad de una base de datos:

```python
from agno.tools.duckdb import DuckDbTools

duckdb_tools = DuckDbTools()
duckdb_tools.create_table_from_path(
    path="data/valid_categories.csv",
    table="valid_categories",
)

agent = Agent(
    tools=[duckdb_tools],
    additional_context="Tabla disponible: valid_categories (columna: name)",
)
agent.print_response("¿Cuántas categorías válidas hay que contengan 'electr'?")
```

### output_schema — output estructurado y validado con Pydantic

En vez de recibir texto libre, el agente devuelve un objeto Pydantic validado.
Reemplaza cualquier lógica custom de validación de outputs:

```python
from pydantic import BaseModel, Field
from agno.agent import Agent

class CorrectionResult(BaseModel):
    original: str = Field(description="Categoría tal como vino en el input")
    corrected: str = Field(description="Categoría correcta de la lista válida")
    confidence: float = Field(ge=0, le=1, description="Confianza de la corrección")
    needs_review: bool = Field(description="True si un humano debería verificar")

agent = Agent(
    model=model,
    output_schema=CorrectionResult,
)

response = agent.run("Corregí la categoría 'prodctos'")
result: CorrectionResult = response.content  # objeto tipado, no texto
print(result.corrected)    # "productos"
print(result.confidence)   # 0.97
```

### Estado persistente con session_state

Para pasar datos entre steps del workflow sin que los agentes los manejen
explícitamente:

```python
# Guardar en un step
workflow.session_state["categorias_anomalas"] = anomalias_detectadas

# Leer en el siguiente step
anomalias = workflow.session_state.get("categorias_anomalas", [])
```

### Cuándo construir un Toolkit custom

Solo cuando necesitás integrar algo que no existe en los 100+ toolkits nativos.
La clase base es `Toolkit` de `agno.tools`:

```python
from agno.tools import Toolkit

class MiToolkit(Toolkit):
    def __init__(self, **kwargs):
        super().__init__(name="mi_toolkit", tools=[self.mi_funcion], **kwargs)

    def mi_funcion(self, parametro: str) -> str:
        """Descripción clara de qué hace.

        Args:
            parametro (str): Descripción del parámetro.
        """
        ...
```

---

## Arquitectura del framework

Este diagrama describe las **capas internas de Agno como plataforma** — no es la
estructura de carpetas del proyecto (eso está en `02-project-structure.md`).

```
Framework Layer     →  Agents, Teams, Workflows + memory, knowledge, tools
Runtime Layer       →  FastAPI stateless backend para producción
Observability Layer →  Agno traces, LangSmith, MLflow — audit trail + MLOps
Control Plane       →  AgentOS UI para testing y monitoreo
```
