# Guía de orientación del proyecto

Documento explicativo completo para entender la estructura del proyecto,
sus carpetas, decisiones de diseño y conceptos clave.

---

## Mapa de carpetas — para qué existe cada una

```
py-agno-ai-workflow/
│
├── agents/          → Los 4 agentes del pipeline
├── domain/          → Lógica de negocio pura (sin dependencias externas)
├── infrastructure/  → Plomería técnica: modelo, estado y helpers de I/O
├── workflows/       → Orquestación Agno: une los 4 Steps en un Workflow
├── data/            → valid_categories.csv + Excel O*NET original
├── scripts/         → Utilidades de una sola vez (regenerar CSV, auditoría)
├── tests/           → Todo el testing (unit + integración + golden path)
├── tmp/             → Carpeta de runtime: uploads y outputs (no es código)
├── docs/            → Documentación del proyecto
└── __pycache__/     → Bytecodes compilados por Python (auto-generado, ignorar)
```

---

## `__pycache__/`

No es tuya ni la creaste vos. Python la genera automáticamente cuando ejecuta
cualquier `.py`. Contiene versiones precompiladas (`.pyc`) de tu código para
que las ejecuciones siguientes sean más rápidas. Aparece en TODAS las carpetas
que tienen archivos Python. Está en `.gitignore` — nunca la toques ni la analices.

---

## `domain/` — La capa de reglas de negocio

### ¿Qué es?

La carpeta `domain/` contiene la lógica de negocio pura del proyecto.
"Pura" significa que no importa Agno, no importa openpyxl, no importa
ningún framework externo. Solo contiene las reglas que definen qué es
verdad dentro de este negocio, independientemente de cómo esté implementado.

### `domain/onet.py` — ¿Para qué sirve?

```python
def is_valid_onet_title(title: str | None, valid_categories_set: set[str]) -> bool:
    if title is None:
        return False
    return title in valid_categories_set
```

Esta función responde a una pregunta de negocio crítica:
**"¿Este título es un título O*NET canónico válido?"**

Parece simple, pero su importancia viene de dónde se usa:

| Quién la llama | Por qué |
|---|---|
| `mapper_agent.py` | Antes de aceptar la respuesta del LLM — si el LLM inventa un título, esta función lo rechaza |
| `audit_writer_agent.py` | Antes de escribir cualquier corrección en el Excel de salida — última verificación |

Sin esta función, cada uno de esos dos archivos tendría su propia versión
del chequeo. Si la lógica necesita cambiar (por ejemplo, chequeo case-insensitive),
habría que actualizarla en dos lugares. Con `domain/onet.py`, se actualiza en uno.

### ¿Por qué "hoy solo tiene una función"?

Porque el proyecto está en construcción. La carpeta `domain/` existe como
concepto arquitectónico: es el lugar donde vive todo lo que pertenece al
negocio y no a la infraestructura. A medida que el proyecto crezca, acá
podrían aparecer más funciones o clases: validaciones de reglas de negocio,
cálculos de métricas de precisión, etc.

---

## `infrastructure/` — El pegamento técnico

### ¿Qué significa "pegamento técnico"?

No es documentación. Son archivos Python que se ejecutan. La diferencia
entre `domain/` e `infrastructure/` es conceptual:

- `domain/` contiene **qué** hace el negocio (las reglas)
- `infrastructure/` contiene **cómo** se implementan los detalles técnicos
  (cómo se crea el modelo, cómo se serializa el estado, cómo se envuelve un resultado)

Los agentes usan `infrastructure/` para no repetir el mismo código técnico
en los 4 archivos de agentes.

### Los agentes NO "recorren" los pipelines

La carpeta se llama `infrastructure/pipeline/` pero eso no significa que
sea el pipeline en sí. El pipeline real es el Workflow de Agno en `workflows/`.
`infrastructure/pipeline/` contiene solo helpers de ese pipeline: tipos de
datos y funciones auxiliares que todos los agentes necesitan.

### Explicación de cada archivo

#### `infrastructure/llm/provider.py` — Fábrica del modelo

```python
def get_model():
    provider = os.getenv("LLM_PROVIDER", "lmstudio").lower()
    if provider == "groq":
        return Groq(id=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))
    return LMStudio(id=os.getenv("LMSTUDIO_MODEL", "qwen/qwen3.5-9b"))
```

Problema que resuelve: si cada agente que necesita un modelo hiciera
`LMStudio(...)` directamente en su archivo, para cambiar al modelo de
producción (Groq) habría que editar varios archivos. Con este archivo,
el cambio se hace en un solo lugar: la variable de entorno `LLM_PROVIDER`.

En desarrollo: `LLM_PROVIDER` no está seteada → usa LM Studio local.
En producción: `LLM_PROVIDER=groq` → usa Groq con llama-3.3-70b.

#### `infrastructure/pipeline/contracts.py` — Contrato de dato

```python
class CategoryValidation(BaseModel):
    raw: str
    is_valid: bool
    closest_match: str | None
    similarity_score: float
```

`ValidatorAgent` produce este tipo. `MapperAgent` lo consume.
Es el "contrato" entre los dos: el ValidatorAgent promete devolver
siempre este formato, y el MapperAgent sabe exactamente qué va a recibir.
Si no existiera, el MapperAgent tendría que adivinar o el código estaría
acoplado.

#### `infrastructure/pipeline/session.py` — Estado compartido del pipeline

```python
@dataclass(frozen=True)
class PipelineSession:
    file_path: str
    target_column: str
    valid_categories: list[str]
    valid_categories_set: set[str]  # derivado automáticamente
```

El Workflow de Agno pasa un diccionario `session_state` a todos los Steps.
`PipelineSession` convierte ese diccionario crudo en un objeto tipado.

Sin esto, cada agente haría `session_state["file_path"]` y si algún día
se cambia el nombre de la clave, hay que buscar en todos los archivos.
Con `PipelineSession.from_dict(session_state)`, el error está en un lugar.

Es el estado de toda la ejecución — empieza cuando el usuario sube el Excel
y termina cuando el AuditWriter escribe el output. No es memoria entre
ejecuciones.

#### `infrastructure/pipeline/step_io.py` — Helpers de entrada/salida

```python
def ok(result: BaseModel) -> StepOutput:
    return StepOutput(content=result.model_dump_json())

def fail(exc: Exception) -> StepOutput:
    return StepOutput(content=str(exc), success=False, stop=True)

def deserialize(content: str, model_class: type[T]) -> T:
    return model_class.model_validate_json(content)
```

Agno pasa datos entre Steps como strings JSON (el `StepOutput.content`).
Estos tres helpers encapsulan ese detalle técnico. Sin ellos, cada agente
repetiría `StepOutput(content=result.model_dump_json())` o
`ValidatorResult.model_validate_json(step_input.previous_step_content)`.
Con ellos, cada agente solo llama `ok(result)` o `deserialize(content, Tipo)`.

---

## `scripts/` — Utilidades de una sola vez

### ¿Qué es O*NET y cuándo actualizás la base?

O*NET es el catálogo oficial del Departamento de Trabajo de EE.UU. con
~923 títulos canónicos de ocupaciones. El archivo original es
`data/raw/related_ocuppations.xlsx`. De ese archivo se genera
`data/valid_categories.csv` — la lista que el pipeline usa como referencia.

El script `scripts/build_valid_categories.py` hace exactamente eso:
lee el Excel O*NET y escribe el CSV. Se corre una sola vez así:

```bash
uv run python scripts/build_valid_categories.py
```

**¿Cuándo lo volvés a correr?** Solo cuando O*NET actualiza su catálogo
(ocurre periódicamente, no frecuentemente). Para un portfolio/demo,
probablemente nunca más.

**El pipeline de producción NO llama este script.** El pipeline carga
`data/valid_categories.csv` que ya fue generado. El script es una
herramienta de mantenimiento, no parte del flujo de usuario.

### ¿El pipeline acepta solo .xlsx o cualquier formato?

En su estado actual, **solo acepta `.xlsx`** porque todos los agentes
usan `openpyxl`, que es una librería específica para Excel. Aceptar
otros formatos (.csv, .ods, Google Sheets) sería una extensión futura
que requeriría trabajo adicional.

Lo que sí es flexible es el nombre de la columna: el usuario puede
indicar qué columna contiene los títulos de trabajo. No está hardcodeado
a un nombre específico.

---

## `tests/` — Todo el testing

### ¿Por qué existen los tests?

Los tests verifican que el código hace lo que se supone que debe hacer,
especialmente ante cambios futuros. Si mañana modificás el `ValidatorAgent`
y algo se rompe, los tests lo detectan antes de que llegue a producción.

### `tests/fixtures/golden_input.xlsx` — ¿Qué es el "golden input"?

Es un archivo Excel estático, comprometido en el repositorio, con 4 filas
diseñadas deliberadamente para cubrir los casos más importantes:

```
Row 1: "Software Developers"           → Ya es válido, no necesita corrección
Row 2: "Lead Accountants and Auditors" → Seniority strip → autocorregido por fuzzy
Row 3: "Fronted Developer"             → Typo → banda LLM
Row 4: "RRHH"                          → Abreviatura → banda LLM
```

"Golden" significa "el ejemplo canónico". El test pasa el pipeline completo
sobre este archivo y verifica invariantes:

- El Excel de salida tiene las dos hojas requeridas ("Corrected" + "Review Queue")
- No hubo alucinaciones (el pipeline nunca inventó un título)
- "Lead Accountants and Auditors" fue corregido automáticamente
- Ninguna corrección apunta a un título fuera de `valid_categories.csv`

Si algún día se rompe algo en el pipeline, este test lo detecta con un
ejemplo concreto y revisable — no con datos generados dinámicamente que
cambian en cada ejecución.

Los archivos `golden_input_corrected_YYYYMMDD_HHMMSS.xlsx` son outputs
generados por ejecuciones anteriores. En producción deberían limpiarse
o estar en `.gitignore` — son artefactos de ejecuciones de prueba.

### `tests/domain/` — Tests de la capa domain

```python
def test_exact_match():
    assert is_valid_onet_title("Software Engineers", CATEGORIES) is True

def test_none_is_invalid():
    assert is_valid_onet_title(None, CATEGORIES) is False

def test_case_mismatch_is_invalid():
    assert is_valid_onet_title("software engineers", CATEGORIES) is False
```

Estos tests verifican que `is_valid_onet_title()` cumple exactamente
su contrato: solo acepta `None` como inválido, distingue mayúsculas,
y reconoce títulos exactos. Si alguien cambia la función y rompe
alguna de estas reglas de negocio, el test falla.

### Los demás archivos de tests

| Archivo | Qué prueba |
|---|---|
| `test_pre_processor.py` | Normalización de texto (seniority, casing, ruido) |
| `test_validator.py` | Que el ValidatorAgent clasifica bien válidos vs. anomalías |
| `test_mapper.py` | Que el MapperAgent toma las decisiones correctas por banda |
| `test_mapping_pipeline.py` | Que `score()` y `routing_band()` devuelven los valores esperados |
| `test_integration_pipeline.py` | Que los 4 agentes conectados end-to-end funcionan juntos |
| `test_integration_golden_path.py` | Pipeline completo sobre el golden_input.xlsx estático |
| `test_integration_seams.py` | Que las juntas entre agentes (serialización/deserialización) son correctas |
| `test_smoke.py` | Que el proyecto arranca sin errores de importación |

---

## Los 4 agentes — cuáles usan LLM y cuáles no

Esta es una distinción importante que no siempre queda clara con el
nombre "agente":

| Agente | Tipo real | Usa LLM |
|---|---|---|
| `IngestAgent` | Función Python (openpyxl) envuelta en `Step` de Agno | No |
| `ValidatorAgent` | Función Python (rapidfuzz) envuelta en `Step` de Agno | No |
| `MapperAgent` | Agno `Agent` real con `output_schema=SemanticMatch` | Sí — solo en banda 0.70–0.89 |
| `AuditWriter` | Función Python (openpyxl) envuelta en `Step` de Agno | No |

Los tres "Pythonic puros" usan el framework Agno solo para orquestación
(el `Step`/`StepOutput` que conecta la cadena). El LLM solo entra cuando
el problema es semántico/lingüístico y ningún algoritmo es suficiente:
traducciones, abreviaciones, variantes de género.

---

## ¿Qué significa "el MapperAgent recibe un prompt estructurado y devuelve un SemanticMatch Pydantic"?

### El prompt estructurado

El `MapperAgent` no recibe texto libre ni conversación. Recibe exactamente esto:

```
Job title to normalize: "RRHH"
Preprocessed form: "rrhh"
Candidate canonical titles (ranked by similarity):
  1. Human Resources Managers (score: 0.75)
  2. Human Resources Specialists (score: 0.71)
  3. Training and Development Managers (score: 0.68)

Select the best match if semantically equivalent, or return null if none fit.
```

El LLM no tiene que adivinar qué formato usar ni qué se espera de él.
El prompt le da exactamente los datos relevantes y le dice exactamente
qué debe responder.

### El SemanticMatch Pydantic

En lugar de responder texto libre ("Creo que es Human Resources Managers"),
el LLM devuelve un objeto con estructura fija:

```python
class SemanticMatch(BaseModel):
    is_equivalent: bool               # ¿Encontró equivalente semántico?
    canonical_title: str | None       # El título exacto elegido (o None)
    normalization_type: Literal[      # Tipo de normalización detectada
        "language", "synonym",
        "abbreviation", "unknown"
    ]
```

Agno se encarga de parsear la respuesta del LLM y construir este objeto.
Si el LLM devuelve algo que no encaja en este esquema, Agno lo rechaza
antes de que llegue al código del agente.

### ¿Por qué esto importa?

Porque el código posterior (`_decide()` en `mapper_agent.py`) puede hacer
`semantic.is_equivalent` o `semantic.canonical_title` con certeza total.
No hay string parsing, no hay `if "yes" in response.lower()`, no hay
ambigüedad. El LLM es una pieza de la pipeline con inputs y outputs
controlados, igual que cualquier función Python.

---

## Memoria, conocimiento, ML y tools — por qué NO aplican aquí

### Memoria (Memory en Agno)

La memoria de agentes existe para chats: el usuario hace pregunta 1,
luego pregunta 2, y la respuesta 2 depende de la 1. Este pipeline es
**stateless por diseño**: recibe un Excel, lo procesa, devuelve otro Excel.
Cada ejecución es completamente independiente. Darle memoria a los agentes
no aportaría nada y añadiría complejidad innecesaria.

El estado que sí existe (`PipelineSession`) no es memoria de agente —
es un dato tipado que pasa entre pasos del mismo pipeline y se destruye
al terminar la ejecución.

### Conocimiento (Knowledge en Agno)

En Agno, "knowledge" significa una base vectorial (PDFs embebidos,
documentos indexados) que el agente consulta semánticamente. No aplica
aquí. El "conocimiento" del proyecto es `valid_categories.csv` —
923 títulos exactos — y se accede con búsqueda exacta + rapidfuzz,
no con embeddings. Eso es más rápido, más barato y completamente auditable.

### Machine Learning

rapidfuzz usa algoritmos de distancia de edición (Levenshtein, WRatio),
que son algoritmos deterministas — no son ML estadístico/entrenado.
El único componente de ML genuino es el LLM en el `MapperAgent`, y ese
LLM entra únicamente cuando la confianza está entre 0.70 y 0.89.

### Tools (en el sentido de Agno)

En Agno, "tools" son funciones que el agente puede llamar autónomamente
durante su razonamiento (buscar en web, ejecutar SQL, llamar APIs).
No aplica aquí. El `MapperAgent` recibe un prompt estructurado y devuelve
un `SemanticMatch` Pydantic. No necesita autonomía — necesita determinismo
y auditabilidad. Darle tools significaría que el agente podría tomar
decisiones no controladas, lo que rompería el invariante de auditoría.

---

## Flujo completo de una ejecución

```
Usuario sube Excel
      │
      ▼
  app.py (Chainlit)
      │  Lee valid_categories.csv
      │  Guarda Excel en tmp/uploads/
      │  Construye session_state dict
      ▼
  Workflow (workflows/pipeline.py)
      │
      ├─ Step 1: IngestAgent
      │    Lee el Excel con openpyxl
      │    Extrae categorías únicas
      │    Devuelve IngestResult (JSON)
      │
      ├─ Step 2: ValidatorAgent
      │    Compara cada categoría contra valid_categories.csv
      │    Usa rapidfuzz para encontrar el match más cercano
      │    Devuelve ValidatorResult con anomalías
      │
      ├─ Step 3: MapperAgent
      │    Para cada anomalía:
      │      ≥ 0.90 → autocorrige (rapidfuzz, sin LLM)
      │      0.70–0.89 → llama al LLM con candidatos
      │      < 0.70 → necesita revisión humana
      │    Devuelve MappingResult
      │
      └─ Step 4: AuditWriter
           Crea Excel de salida con hoja "Corrected" + "Review Queue"
           Verifica cada corrección con is_valid_onet_title()
           Guarda en tmp/output/ con timestamp
           Devuelve AuditResult (métricas)
      │
      ▼
  app.py muestra resultado en Chainlit
  Usuario descarga Excel corregido
```
