# Estrategia de Implementación y Validación del Sistema

Resumen de decisiones de diseño, fuentes de datos, capas de detección de errores,
y estrategia de evaluación del proyecto Smart Data Normalization Agent.

---

## 1. Qué problema resuelve el proyecto (en palabras simples)

Imaginá una empresa con un formulario donde los empleados escriben su puesto libremente:

```
Juan escribió:    "desarrollador front"
María escribió:   "Frontend Dev"
Carlos escribió:  "front-end developer"
Pedro escribió:   "Dev Front"
```

Cuatro personas, el mismo trabajo, cuatro nombres distintos. Para un humano son lo
mismo. Para un sistema de software son cuatro cosas incomparables.

El proyecto recibe ese Excel desordenado y lo convierte en esto:

```
Juan:    "Frontend Developer"   ✓ corregido automáticamente
María:   "Frontend Developer"   ✓ corregido automáticamente
Carlos:  "Frontend Developer"   ✓ corregido automáticamente
Pedro:   "Frontend Developer"   ✓ corregido automáticamente
```

Cada corrección queda registrada con: qué había, qué se puso, con qué nivel de
confianza, y si fue automático o necesitó revisión humana.

---

## 2. El agente no necesita una base de errores

**Pregunta clave:** ¿Cómo detecta "prodctos" si no tiene una lista de errores conocidos?

**Respuesta:** No necesita saber que "prodctos" es un error conocido.
Solo necesita saber que "productos" existe en la lista válida y que ambas palabras
se parecen mucho. El error se infiere por comparación, no por reconocimiento.

```
"prodctos"  →  compara contra lista válida  →  "productos" (similitud 0.92)
```

Lo único que el sistema necesita es la **lista de categorías válidas** (lo correcto).
Los errores no se registran — se detectan en el momento.

---

## 3. La lista `valid_categories` — fuente de datos

### Archivo disponible: `Related Occupations.xlsx`

El archivo descargado de O*NET (Departamento de Trabajo de EE.UU.) contiene
**923 ocupaciones canónicas** estandarizadas.

**Por qué el Excel tiene 18.461 filas pero solo 923 ocupaciones:**

El archivo es una tabla de relaciones — cada ocupación aparece varias veces,
una por cada ocupación relacionada:

```
Fila 1:  Chief Executives  →  General and Operations Managers   (Primary-Short)
Fila 2:  Chief Executives  →  Management Analysts               (Primary-Short)
Fila 3:  Chief Executives  →  Treasurers and Controllers        (Primary-Short)
...
```

Cuando se eliminan duplicados de la columna `Title` quedan 923 valores únicos.
Esos 923 son la lista válida.

**Estructura del archivo:**

| Columna | Contenido |
|---------|-----------|
| `O*NET-SOC Code` | Código oficial de la ocupación |
| `Title` | Nombre canónico (la categoría válida) |
| `Related O*NET-SOC Code` | Código de ocupación relacionada |
| `Related Title` | Nombre de ocupación relacionada |
| `Relatedness Tier` | Qué tan cercanas son: Primary-Short / Primary-Long / Supplemental |
| `Index` | Orden de relevancia |

### Cómo generar `valid_categories.csv` desde el archivo

```python
# scripts/build_valid_categories.py
import openpyxl, csv

wb = openpyxl.load_workbook("Related Occupations.xlsx")
ws = wb.active

titles = set()
for i, row in enumerate(ws.iter_rows(values_only=True)):
    if i == 0:
        continue
    titles.add(row[1])  # columna Title

with open("data/valid_categories.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["category"])
    for t in sorted(titles):
        writer.writerow([t])

print(f"Generadas {len(titles)} categorías válidas")  # → 923
```

### El grafo de relaciones como contexto adicional

La columna `Relatedness Tier` le dice al MapperAgent qué tan cercanas son dos
ocupaciones — útil cuando hay ambigüedad:

| Tier | Significado | Uso en el agente |
|------|-------------|-----------------|
| `Primary-Short` | Muy relacionadas | Primera opción de corrección en casos ambiguos |
| `Primary-Long` | Relacionadas | Segunda opción |
| `Supplemental` | Relacionadas indirectamente | Fallback |

---

## 4. Cómo funciona la detección — dos capas en orden

### Capa 1 — rapidfuzz (comparación de letras, sin LLM)

Compara los caracteres de las palabras y devuelve un score de similitud.
No entiende el significado — solo mide qué tan parecidas son las letras.

```python
from rapidfuzz import process, fuzz

valid_categories = ["productos", "electrónica", "ropa", "servicios"]

def fuzzy_match(raw: str, valid: list[str]) -> tuple[str, float]:
    best_match, score, _ = process.extractOne(
        raw,
        valid,
        scorer=fuzz.ratio
    )
    return best_match, score / 100

match, confidence = fuzzy_match("prodctos", valid_categories)
# → ("productos", 0.92)  — typo detectado sin gastar tokens
```

### Capa 2 — LLM con output_schema (comprensión del significado)

Cuando rapidfuzz no alcanza (sinónimos, cambios de idioma, abreviaturas),
el LLM evalúa si hay equivalencia semántica. Devuelve un objeto Pydantic validado.

```python
from pydantic import BaseModel, Field
from agno.agent import Agent

class MappingResult(BaseModel):
    original: str
    corrected: str = Field(description="Debe ser exactamente uno de los valores válidos")
    confidence: float = Field(ge=0, le=1)
    needs_review: bool

VALID_CATEGORIES = [...]  # las 923 ocupaciones de O*NET

mapper_agent = Agent(
    model=model,
    output_schema=MappingResult,
    instructions=[
        f"Las únicas categorías válidas son: {VALID_CATEGORIES}",
        "Tu output en 'corrected' debe ser exactamente uno de esos valores.",
        "Si no encontrás equivalencia clara, pon needs_review=True y confidence < 0.70",
    ],
)
```

### Cómo se integran las dos capas en el MapperAgent

```python
THRESHOLD_AUTO = 0.90   # rapidfuzz → corrección automática
THRESHOLD_LLM  = 0.70   # rapidfuzz → pasa al LLM
                         # < 0.70    → human-in-the-loop

def map_category(raw: str, valid: list[str]) -> MappingResult:
    match, score = fuzzy_match(raw, valid)

    if score >= THRESHOLD_AUTO:
        # typo claro — sin gastar tokens
        return MappingResult(original=raw, corrected=match,
                             confidence=score, needs_review=False)

    if score >= THRESHOLD_LLM:
        # ambigüedad semántica — LLM evalúa
        return mapper_agent.run(f"Corregí: '{raw}'").content

    # confianza baja — marcar para revisión humana
    return MappingResult(original=raw, corrected=match,
                         confidence=score, needs_review=True)
```

### Tabla de decisión por tipo de error

| Input | rapidfuzz score | Quién resuelve | Por qué |
|-------|----------------|----------------|---------|
| `"prodctos"` | 0.92 | rapidfuzz | Typo obvio, edit distance pequeño |
| `"electronica"` | 0.88 | LLM | Tilde ausente, ambiguo para edit distance |
| `"RRHH"` | 0.31 | LLM | Sinónimo / abreviatura |
| `"xyz123"` | 0.10 | human-in-the-loop | Sin match posible |

---

## 5. Dataset de prueba — construido sintéticamente con intención

**"Sintéticamente con intención"** significa: vos mismo escribís los datos de prueba
a mano, con errores deliberados que querés cubrir. No esperás usuarios reales.
Cada error que ponés tiene un propósito: testear typos, sinónimos, cambios de idioma.

### Tipos de errores que el dataset debe cubrir

| Tipo de error | Ejemplo input | Ejemplo output esperado |
|--------------|---------------|------------------------|
| Typo | `"Fronted Developer"` | `"Frontend Developer"` |
| Abreviatura | `"Dev Front"`, `"FE Dev"` | `"Frontend Developer"` |
| Idioma incorrecto | `"Desarrollador Frontend"` | `"Frontend Developer"` |
| Sinónimo | `"RRHH"` | `"Human Resources Managers"` |
| Formato distinto | `"data eng"` | `"Data Engineers"` |

### Script para generar el sample input

```python
# scripts/generate_sample_data.py
import openpyxl

error_variants = {
    "Frontend Developer": ["Dev Front", "front-end dev", "FE Developer", "Desarrollador Frontend", "Fronted Developer"],
    "Data Engineers": ["Data Eng", "Ing. Datos", "ingeniero datos", "data enginer"],
    "Human Resources Managers": ["RRHH", "Recursos Humanos", "HR Spec.", "especialista rrhh"],
    "Sales Representatives": ["vendedor", "ventas B2B", "sales rep", "Ventas"],
    "Software Developers": ["dev", "software dev", "desarrollador software", "SW Developer"],
}

wb = openpyxl.Workbook()
ws = wb.active
ws.append(["job_category_raw"])  # columna que el agente va a normalizar

for correct, wrongs in error_variants.items():
    for v in wrongs:
        ws.append([v])

wb.save("data/sample_input.xlsx")
```

### Golden dataset para evaluación

El golden dataset tiene la columna `expected_output` — solo lo usa el sistema
de evaluación, nunca el agente:

```python
# data/golden_dataset.csv
# job_category_raw,expected_output
# Dev Front,Frontend Developer
# RRHH,Human Resources Managers
# data enginer,Data Engineers
```

---

## 6. Evaluación — dónde está codeada y qué mide

Ubicación en el proyecto: `evaluation/test_agent_accuracy.py`

### Tipo 1 — AccuracyEval de Agno (consistencia por tipo de error)

Corre el agente N veces sobre el mismo input y mide si responde igual cada vez.
Si hay varianza, hay un problema de prompt o de temperatura.

```python
from agno.eval.accuracy import AccuracyEval

typo_eval = AccuracyEval(
    name="typos_test",
    model=model,
    input="prodctos, elctrónica, fronted developer",
    expected_output="productos, electrónica, Frontend Developer",
    agent=normalization_agent,
    num_iterations=5,
)
typo_eval.run(print_results=True)
```

### Tipo 2 — Precision/Recall sobre el golden dataset

Mide objetivamente cuántas correcciones acertó el agente sobre casos conocidos.

```python
import pandas as pd

def run_evaluation(agent, golden_dataset_path: str) -> dict:
    df = pd.read_csv(golden_dataset_path)
    valid = pd.read_csv("data/valid_categories.csv")["category"].tolist()

    correct = 0
    hallucinations = 0

    for _, row in df.iterrows():
        result = agent.run(row["job_category_raw"]).content
        if result.corrected == row["expected_output"]:
            correct += 1
        elif result.corrected not in valid:
            hallucinations += 1  # el agente inventó una categoría que no existe

    return {
        "precision": correct / len(df),
        "hallucination_rate": hallucinations / len(df),
    }
```

### Tipo 3 — Test de regresión con pytest

Cuando modificás el prompt o cambiás el modelo, pytest avisa si la calidad bajó.

```python
import pytest

def test_precision_above_threshold():
    metrics = run_evaluation(mapper_agent, "data/golden_dataset.csv")
    assert metrics["precision"] >= 0.85, f"Precision cayó a {metrics['precision']}"
    assert metrics["hallucination_rate"] <= 0.05, "Tasa de alucinación muy alta"
```

Corrés con: `pytest evaluation/`

### Las tres métricas que importan

| Métrica | Qué mide | Umbral mínimo |
|---------|----------|--------------|
| `precision` | % de correcciones acertadas | ≥ 0.85 |
| `hallucination_rate` | % de correcciones que inventó el agente | ≤ 0.05 |
| `needs_review_rate` | % de casos que el agente no pudo resolver solo | referencia |

---

## 7. Flujo completo del sistema — paso a paso

```
Input: Excel del usuario (con categorías potencialmente erróneas)
    ↓
IngestAgent
    Lee el Excel con openpyxl
    Extrae las categorías únicas de la columna target
    No modifica nada — solo lee y reporta
    ↓
ValidatorAgent
    Carga valid_categories.csv (las 923 ocupaciones de O*NET)
    Compara cada categoría del Excel contra la lista
    Marca las que no existen como anomalías
    ↓
MapperAgent
    Para cada anomalía:
        rapidfuzz score ≥ 0.90  → corrección automática (sin LLM)
        rapidfuzz score 0.70–0.89 → LLM evalúa semánticamente
        rapidfuzz score < 0.70  → needs_review = True (human-in-the-loop)
    Output: objeto Pydantic con corrected + confidence + needs_review
    ↓
AuditWriter
    Genera el Excel corregido (misma estructura que el input)
    Agrega hoja "Audit Log" con cada cambio registrado:
        columna | valor original | valor corregido | confidence | método
    ↓
Output:
    - Excel limpio con categorías normalizadas
    - Audit trail completo de cada corrección
```

---

## 8. Por qué este proyecto es relevante para AI Engineer roles

El dominio laboral (job search, ATS, HR tech) es el caso de uso ideal porque:

- Los ATS y job boards tienen exactamente este problema a escala masiva
- Las variantes de títulos de trabajo son infinitas y no se pueden cubrir con reglas manuales
- El audit trail es obligatorio en contextos enterprise (compliance, GDPR)

### Stack de keywords para CV / ATS

Términos que aparecen en ofertas de AI Engineer 2026 y que este proyecto cubre:

```
multi-agent systems · workflow orchestration · output schema · Pydantic
RAG-adjacent retrieval · evaluation layer · precision/recall · FastAPI
audit trail · human-in-the-loop · confidence scoring · data quality / ETL with LLM
```

### Rol recomendado al que apuntar

Con Fullstack + AI Engineering el título correcto es **AI Application Engineer**
o **AI Engineer (Full-Stack)**. Es el perfil más demandado en 2026 porque une
capacidades que escasean juntas: construir el backend/frontend Y integrar LLMs.

Puestos que activás con este stack:

| Puesto | Keywords que te matchean |
|--------|--------------------------|
| AI Engineer | Python, LLM, agents, RAG, API |
| ML Engineer (application) | FastAPI, model integration, inference |
| Full-Stack AI Developer | React/Next + Python + LLM |
| AI Solutions Engineer | deployment, FastAPI, Claude/OpenAI API |
