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

## 4. Las 7 normalizaciones del sistema

El sistema resuelve 7 categorías de error humano. Cada una tiene una capa asignada
que la resuelve — esto define cómo fluye el título dentro del MapperAgent.

| # | Tipo | Input ejemplo | Output esperado | Resuelta por |
|---|------|---------------|-----------------|--------------|
| 1 | **Typo** | `"Fronted Developer"` | `"Software Developers"` | rapidfuzz |
| 2 | **Casing / puntuación** | `"FULL-STACK DEVELOPER"` | `"Software Developers"` | pre_processor.py |
| 3 | **Seniority stripping** | `"Senior Frontend Developer"` | `"Software Developers"` | pre_processor.py |
| 4 | **Ruido / contexto** | `"Dev Frontend - Remoto (Contract)"` | `"Software Developers"` | pre_processor.py |
| 5 | **Idioma** | `"Desarrollador Backend"` | `"Software Developers"` | LLM |
| 6 | **Abreviatura / sinónimo** | `"RRHH"`, `"comercial"` | `"Human Resources Managers"` | LLM |
| 7 | **Género gramatical** | `"Desarrolladora"`, `"Analista de Datos"` | `"Data Scientists..."` | LLM |

**Regla clave:** los tipos 2, 3 y 4 se limpian con `pre_processor.py` antes de que el
título llegue a rapidfuzz. Esto convierte `"SENIOR FULL-STACK DEVELOPER - REMOTO"` en
`"full stack developer"` — un string que rapidfuzz puede comparar eficientemente sin
gastar tokens de LLM.

---

## 4b. El pre-processor — Python puro, cero tokens

`pre_processor.py` normaliza el título antes de la comparación. No usa LLM.
Se llama dentro del MapperAgent como primer paso, antes de rapidfuzz.

```python
# agents/pre_processor.py
import re
import unicodedata

SENIORITY_WORDS = {
    "senior", "sr", "junior", "jr", "lead", "staff",
    "principal", "mid", "entry", "associate", "head of",
}

def normalize_title(raw: str) -> str:
    # 1. lowercase + strip accents
    title = raw.lower().strip()
    title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()

    # 2. strip noise after separators (-, |, /, parentheses)
    title = re.split(r"[-|/\(]", title)[0].strip()

    # 3. strip seniority modifiers
    words = [w for w in title.split() if w not in SENIORITY_WORDS]
    title = " ".join(words)

    # 4. normalize punctuation (hyphens → space)
    title = re.sub(r"[-_]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()

    return title
```

**Ejemplos:**

| Input | Output de normalize_title() |
|-------|-----------------------------|
| `"SENIOR FULL-STACK DEVELOPER - REMOTO"` | `"full stack developer"` |
| `"Jr. Data Engineer \| Remote"` | `"data engineer"` |
| `"AWS Certified Developer (Contract)"` | `"aws certified developer"` |
| `"Desarrolladora Frontend"` | `"desarrolladora frontend"` ← pasa al LLM |

---

## 5. Cómo funciona la detección — tres capas en orden

### Capa 0 — pre_processor.py (normalización determinística, sin LLM)

Limpia el título antes de cualquier comparación. Sin tokens, sin latencia adicional.
Ver sección 4b para el código completo.

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

El golden dataset debe tener al menos 2 casos por tipo — uno fácil y uno límite.

| Tipo | Ejemplo input | Output esperado | Resuelta por |
|------|---------------|-----------------|--------------|
| Typo | `"Fronted Developer"`, `"data enginer"` | `"Software Developers"` | rapidfuzz |
| Casing / puntuación | `"FULL-STACK DEVELOPER"`, `"front-end dev"` | `"Software Developers"` | pre_processor |
| Seniority stripping | `"Senior Data Engineer"`, `"Jr. Frontend Dev"` | `"Data Engineers"` | pre_processor |
| Ruido / contexto | `"Backend Developer - Remoto"`, `"Dev (Contract)"` | `"Software Developers"` | pre_processor |
| Idioma | `"Desarrollador Frontend"`, `"Ing. Datos"` | `"Software Developers"` | LLM |
| Abreviatura / sinónimo | `"RRHH"`, `"comercial"`, `"ventas B2B"` | `"Human Resources Managers"` | LLM |
| Género gramatical | `"Desarrolladora"`, `"Analista de Datos"` | `"Data Scientists..."` | LLM |

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

Los tests viven en `tests/`. El golden path test corre el pipeline completo sobre
`tests/fixtures/golden_input.xlsx` — un Excel estático con 4 filas deliberadas:

| Fila | Input | Caso cubierto |
|------|-------|---------------|
| 1 | `"Software Developers"` | Ya es válido — no debe cambiar |
| 2 | `"Lead Accountants and Auditors"` | Seniority strip → autocorrección por fuzzy |
| 3 | `"Fronted Developer"` | Typo → banda LLM |
| 4 | `"RRHH"` | Abreviatura → banda LLM |

```bash
# Correr todos los tests
uv run pytest

# Correr solo los que no hacen llamadas reales al LLM
uv run pytest -m "not real_llm"

# Golden path test
uv run pytest tests/test_integration_golden_path.py
```

El golden path test verifica:
- El Excel de salida tiene las dos hojas requeridas ("Corrected" + "Review Queue")
- No hubo alucinaciones (ninguna corrección inventó un título fuera de `valid_categories.csv`)
- La corrección de seniority strip fue aplicada automáticamente

### Las tres métricas que importan

| Métrica | Qué mide | Umbral mínimo |
|---------|----------|--------------|
| `precision` | % de correcciones acertadas | ≥ 0.85 |
| `hallucination_rate` | % de correcciones que inventó el agente | ≤ 0.05 |
| `needs_review_rate` | % de casos que el agente no pudo resolver solo | referencia |

---

## 7. Flujo completo del sistema — para referencia

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

