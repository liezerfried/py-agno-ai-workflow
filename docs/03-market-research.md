# Market Research: AI Agents en 2026

Sources:
- https://cloud.google.com/resources/content/ai-agent-trends-2026
- https://www.databricks.com/blog/enterprise-ai-agent-trends-top-use-cases-governance-evaluations-and-more
- https://agenticcareers.co/blog/ai-agent-portfolio-projects-get-hired-2026
- https://bernardmarr.com/5-amazing-ai-agent-use-cases-that-will-transform-any-business-in-2026/
- https://www.secondtalent.com/resources/most-in-demand-ai-engineering-skills-and-salary-ranges/
- https://www.indeed.com/hire/job-description/ai-engineer

---

## El contexto del mercado

Según Gartner, el **40% de las aplicaciones enterprise** integrarán agentes de IA para fin de 2026 — frente a menos del 5% en 2025.

El **51% de las enterprises ya tiene agentes en producción**, y un 23% adicional los está escalando activamente.

El **78% de los deployments LLM en producción usan RAG**. Ya no es una ventaja diferencial — es el baseline mínimo esperado.

---

## Casos de uso más demandados en empresas

| Caso de uso | Demanda | Por qué |
|------------|---------|---------|
| Automatización de workflows internos (HR, finanzas, onboarding) | Muy alta | Reduce tareas repetitivas entre sistemas |
| Soporte al cliente autónomo | Muy alta | ROI inmediato y medible |
| RAG sobre documentación interna | Alta | Empresas tienen docs internas sin explotar |
| Análisis financiero + detección de anomalías | Alta | Finanzas opera 24/7, agentes también |
| Multi-agent para investigación de mercado | Alta | Research que antes tomaba días → minutos |
| Data quality / normalización (ETL con LLM) | Alta | Datos legacy sucios; LLM reemplaza reglas manuales de limpieza |
| Automatización de ventas / CRM | Media | En la práctica lo cubren herramientas no-code — no diferencia a un ingeniero |

---

## Qué buscan los recruiters en un portfolio 2026

**Principio clave:** 2–3 proyectos profundos y bien documentados valen más que 10 proyectos superficiales.

### Lo que diferencia un portfolio mediocre de uno que consigue entrevistas:
- Error handling real — no solo el happy path
- Evaluación de los agentes: ¿cómo medís que funciona bien?
- Deployment real — no "corre en mi máquina"
- README con demo o link en vivo: recruiters gastan <10 segundos en el CV, pero el engagement sube 80% con demos accesibles
- Documentación honesta de limitaciones

### Stack que impresiona en 2026:
- Multi-agent systems con roles definidos
- RAG (Retrieval Augmented Generation)
- API expuesta con FastAPI
- Docker + deploy cloud (Render/Railway para free tier; AWS para señal enterprise)
- Observabilidad nombrada explícitamente: este proyecto usa **Agno built-in traces** (alternativa a LangSmith/MLflow, coherente con el stack)
- Prompt Engineering como skill técnica — demanda subió 135.8%, CAGR proyectado 32.8% hasta 2030

---

## Proyecto recomendado: Smart Data Normalization Agent

### Qué hace

Un agente recibe un Excel con categorías potencialmente erróneas, las compara contra una base de datos de categorías válidas, detecta typos y errores de mapeo mediante fuzzy matching + LLM, y devuelve el Excel corregido con un audit trail completo de cada cambio.

### Agentes involucrados

- `IngestAgent` — lee el Excel, extrae las categorías únicas de la columna target
- `ValidatorAgent` — compara contra la DB de categorías válidas, identifica anomalías
- `MapperAgent` — usa LLM con `output_schema` Pydantic para matching semántico; devuelve `confidence` y `needs_review` por corrección
- `AuditWriter` — genera el Excel corregido + reporte de cambios (valor original, valor corregido, confianza, método)

### Arquitectura

```
Input: Excel del usuario
    ↓
IngestAgent      → extrae categorías únicas
    ↓
ValidatorAgent   → detecta anomalías contra DB
    ↓
MapperAgent      → matching semántico (output_schema Pydantic):
                    confidence ≥ 0.90   → corrección automática
                    confidence 0.70–0.89 → needs_review = True
                    confidence < 0.70   → human-in-the-loop
    ↓
AuditWriter      → Excel limpio + audit trail
    ↓
Output: archivo corregido + reporte / API response
```

### Por qué llama la atención

- Cubre **Data Engineering for AI** — top 9 skill en demanda, especialización emergente
- Es **RAG-adjacent**: comparar contra una DB de categorías válidas es retrieval sobre datos estructurados
- Tiene **evaluation layer** integrada: se puede medir precision/recall con un dataset de errores conocidos — exactamente lo que diferencia portfolios
- **Deployable**: FastAPI + Docker + Render/Railway → el recruiter abre una URL
- Caso de uso enterprise directo, explicable en 30 segundos
