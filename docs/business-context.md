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

### Interfaz web (Chainlit — `app.py`)

```
Usuario abre http://localhost:8000
        ↓
on_chat_start → Chainlit muestra widget de file upload
        ↓
Usuario sube el Excel → on_message recibe la ruta del archivo
        ↓
Pipeline corre con visualización en tiempo real:

    ▶ IngestAgent       Lee el Excel, extrae categorías únicas
    ▶ ValidatorAgent    Compara contra O*NET, detecta anomalías
    ▶ MapperAgent       rapidfuzz + TranslatorAgent + LLM
    ▶ AuditWriter       Escribe Excel corregido + audit log + review queue

        ↓
Chainlit muestra enlace de descarga: corrected_YYYYMMDD_HHMMSS.xlsx
El Excel descargado tiene:
    - Hoja "Corrected": categorías normalizadas
    - Hoja "Review Queue": filas que el agente no pudo resolver (confidence < 0.70)
```

### API REST (AgentOS — `agent_os.py`)

AgentOS expone el workflow automáticamente como endpoints REST.
Correr con: `uvicorn agent_os:app --reload`

Los casos con `needs_review=True` quedan en la hoja "Review Queue" del Excel.
La revisión humana se realiza sobre el Excel descargado — el usuario edita la hoja
"Review Queue" y la procesa manualmente.

---

## 4. Cómo funciona la revisión humana

Cuando el agente no está seguro (`confidence < 0.70`), **no adivina** — marca el row
con `needs_review=True` y lo incluye en la hoja "Review Queue" del Excel de salida.

La hoja "Review Queue" contiene:

| raw | closest_match | confidence | review_reason |
|-----|---------------|------------|---------------|
| xyz developer pro | Software Developers | 0.61 | no fuzzy match claro |
| consultor RR.HH senior | Human Resources Managers | 0.68 | abreviatura con variante |

El humano revisa esta hoja, decide qué corrección aplicar, y puede volver a subir
el archivo corregido si necesita reprocesarlo.

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

---

## 6. Por qué la review queue diferencia el portfolio

La mayoría de proyectos de agentes en portfolio hacen todo automático o no hacen nada.
Un sistema que **sabe cuándo no sabe** y pausa para pedir ayuda humana es la
característica que distingue un proyecto enterprise de un script que llama a GPT.

En entrevistas técnicas, la pregunta frecuente es:
*"¿Qué pasa cuando el modelo se equivoca?"*

La review queue es la respuesta concreta a esa pregunta.
