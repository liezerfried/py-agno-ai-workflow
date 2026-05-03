# Contexto de Negocio y Human-in-the-Loop

Quién usa el sistema, en qué contexto laboral se implementa,
y cómo funciona la intervención humana cuando el agente no puede resolver solo.

---

## 1. Quién sube el Excel y desde dónde

El usuario sube un archivo Excel desde una interfaz web — como adjuntar un archivo
en cualquier formulario. No requiere conocimientos técnicos.

### Contextos laborales donde se implementaría

| Contexto | Usuario | Qué sube al sistema |
|----------|---------|---------------------|
| Job board (Bumeran, LinkedIn, Computrabajo) | Empresa que publica ofertas | Excel con puestos y categorías de sus vacantes |
| ATS (sistema de RRHH interno) | Analista de RRHH | Export del sistema con títulos de candidatos sin normalizar |
| Consultora de selección | Recruiter | Base de CVs con puestos tal como los escribieron los candidatos |
| Empresa con sistema legacy | Administrador de datos | Dump de la base de datos con categorías históricas sucias |
| Plataforma de cursos / upskilling | Equipo de contenido | Catálogo de habilidades con variantes y sinónimos |

En todos estos casos el problema es el mismo: **datos que un humano escribió
libremente que un sistema espera recibir en un formato exacto**. Hoy esos datos
se limpian a mano. El agente lo automatiza.

---

## 2. Por qué este problema existe en producción

Los sistemas de software no toleran variantes:

```
"Dev Front"             ≠  "Frontend Developer"   para una base de datos
"RRHH"                  ≠  "Human Resources"       para un ATS
"Desarrollador Backend" ≠  "Backend Developer"     para un filtro de búsqueda
```

Un humano entiende que son lo mismo. Un sistema de búsqueda, un filtro, o una
query SQL no — los trata como categorías distintas o directamente no los encuentra.

**El costo real del problema:**
- Candidatos que no aparecen en búsquedas porque su título está mal normalizado
- Reportes de RRHH incorrectos (cuenta "Dev Front" y "Frontend Developer" como dos puestos distintos)
- Integraciones entre sistemas que fallan porque las categorías no coinciden

---

## 3. Flujo completo con intervención humana

```
Usuario sube su Excel sucio
        ↓
POST /normalize  (FastAPI recibe el archivo)
        ↓
Workflow corre sobre ese archivo:

    IngestAgent
        Lee el Excel con openpyxl
        Extrae las categorías únicas de la columna target
        No modifica nada

    ValidatorAgent
        Compara cada categoría contra valid_categories.csv (O*NET, estático)
        Identifica cuáles no existen en la lista válida → anomalías

    MapperAgent
        Para cada anomalía evalúa con rapidfuzz + LLM:

        confidence ≥ 0.90  →  corrección automática
                               se aplica directamente, sin intervención
        confidence 0.70–0.89 →  corrección sugerida
                               se aplica pero queda marcada "revisar"
        confidence < 0.70  →  el agente NO corrige
                               va a la cola de revisión humana

    AuditWriter
        Genera el Excel con las correcciones automáticas aplicadas
        Genera el audit trail de cada cambio
        Genera la review queue con los ítems que el agente no pudo resolver

        ↓
Response al usuario:
    - Excel corregido (correcciones automáticas ya aplicadas)
    - Audit log (qué cambió, con qué confianza, qué método)
    - Review queue (lista de ítems que esperan decisión humana)
```

---

## 4. Cómo funciona la revisión humana

Cuando el agente no está seguro, **pausa y espera** — no adivina.
El humano recibe una lista de casos dudosos con la sugerencia del agente:

```json
// GET /review-queue
[
  {
    "id": "item_042",
    "original": "xyz developer pro",
    "suggested": "Software Developers",
    "confidence": 0.61,
    "reason": "no fuzzy match claro, coincidencia semántica parcial"
  },
  {
    "id": "item_087",
    "original": "consultor RR.HH senior",
    "suggested": "Human Resources Managers",
    "confidence": 0.68,
    "reason": "abreviatura con variante de puntuación"
  }
]
```

El humano tiene dos acciones:

```
POST /review/{id}/approve   →  acepta la sugerencia del agente
POST /review/{id}/reject    →  escribe la corrección correcta manualmente
```

Una vez que el humano procesa la cola, el Excel final queda completo.

---

## 5. Los tres niveles de confianza — resumen

| Nivel | confidence | Qué hace el sistema | Quién decide |
|-------|-----------|---------------------|--------------|
| Alto | ≥ 0.90 | Corrige automáticamente | Nadie — el agente |
| Medio | 0.70–0.89 | Corrige y marca para revisar | Humano puede revertir |
| Bajo | < 0.70 | No corrige, espera | Humano decide obligatoriamente |

Este diseño escalonado es lo que hace al sistema seguro para producción:
**el agente nunca sobreescribe datos cuando no está seguro**.

---

## 6. Endpoints de la API — mapa completo

```
POST /normalize
    Input:  archivo .xlsx (multipart/form-data)
    Output: Excel corregido + audit log + review queue

GET /review-queue
    Output: lista de ítems con confidence < 0.70 pendientes de revisión

POST /review/{id}/approve
    Input:  id del ítem
    Output: corrección confirmada, ítem removido de la queue

POST /review/{id}/reject
    Input:  id del ítem + corrección manual del humano
    Output: corrección aplicada, ítem removido de la queue

GET /audit/{run_id}
    Output: registro completo de una corrida — qué cambió, cómo, con qué confianza
```

---

## 7. Por qué la review queue diferencia el portfolio

La mayoría de proyectos de agentes en portfolio hacen todo automático o no hacen nada.
Un sistema que **sabe cuándo no sabe** y pausa para pedir ayuda humana es la
característica que distingue un proyecto enterprise de un script que llama a GPT.

En entrevistas técnicas, la pregunta frecuente es:
*"¿Qué pasa cuando el modelo se equivoca?"*

La review queue es la respuesta concreta a esa pregunta.
