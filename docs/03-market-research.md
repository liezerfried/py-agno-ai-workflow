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

Según Gartner: el **40% de las aplicaciones enterprise** integrarán agentes de IA
para fin de 2026. En 2025 era menos del 5%.

En producción: el **51% de las enterprises ya tiene agentes corriendo**, y un 23%
adicional los está escalando activamente. El **78% de los deployments LLM en
producción usan RAG** — ya no es una ventaja diferencial, es el baseline.

---

## Casos de uso más demandados en empresas

| Caso de uso | Demanda | Por qué |
|------------|---------|---------|
| Automatización de workflows internos (HR, finanzas, onboarding) | Muy alta | Reduce tareas repetitivas entre sistemas |
| Soporte al cliente autónomo | Muy alta | ROI inmediato y medible |
| RAG sobre documentación interna | Alta | Empresas tienen docs internas sin explotar |
| Análisis financiero + detección de anomalías | Alta | Finanzas opera 24/7, agentes también |
| Multi-agent para investigación de mercado | Alta | Research que antes tomaba días → minutos |
| Data quality / normalización de datos (ETL con LLM) | Alta | Sistemas legacy tienen datos sucios; LLM reemplaza reglas manuales de limpieza |
| Automatización de ventas / CRM | Media | En la práctica lo cubren herramientas no-code (n8n, Zapier+AI) — no diferencia a un ingeniero |

---

## Qué buscan los recruiters en un portfolio 2026

**Principio clave:** calidad > cantidad.
2-3 proyectos profundos y bien documentados > 10 proyectos superficiales.

### Lo que diferencia un portfolio mediocre de uno que consigue entrevistas:
- Error handling real (no happy path solamente)
- Evaluación de los agentes (¿cómo medís que funciona bien?)
- Deployment (no solo "corre en mi máquina")
- README claro con demo video o link en vivo — recruiters gastan <10 segundos en
  el CV pero tienen 80% más engagement con repos que tienen demo accesible
- Documentación honesta de limitaciones

### Stack que impresiona en 2026:
- Multi-agent systems con roles definidos
- RAG (Retrieval Augmented Generation)
- API expuesta (FastAPI)
- Docker + deploy en cloud (Render/Railway para free tier; AWS para señal enterprise)
- MLOps nombrado explícitamente: LangSmith, MLflow, o Agno built-in traces
- Prompt Engineering como skill técnica — demand surge de 135.8%, CAGR proyectado
  de 32.8% hasta 2030; no es "usar LLMs", es saber diseñar system prompts robustos

---

## Proyecto recomendado: Smart Data Normalization Agent

### Qué hace:
Un agente que recibe un archivo Excel con categorías potencialmente erróneas,
las compara contra una base de datos de categorías válidas, detecta typos y
errores de mapeo usando fuzzy matching + LLM, y devuelve el Excel corregido
junto con un audit trail completo de cada cambio.

### Agentes involucrados:
- `IngestAgent` — lee el Excel, extrae las categorías únicas de la columna target
- `ValidatorAgent` — compara contra la DB de categorías válidas, identifica anomalías
- `MapperAgent` — usa el LLM con `output_schema` Pydantic para matching semántico; devuelve `confidence` y `needs_review` por cada corrección
- `AuditWriter` — genera Excel corregido + reporte de cambios (columna, valor original,
  valor corregido, confianza, método usado)

### Arquitectura:
```
Input: Excel del usuario
    ↓
IngestAgent      → extrae categorías únicas
    ↓
ValidatorAgent   → detecta anomalías contra DB
    ↓
MapperAgent      → LLM matchea semánticamente (output_schema Pydantic):
                    confidence ≥ 0.90  → corrección automática
                    confidence 0.70–0.89 → needs_review = True
                    confidence < 0.70  → human-in-the-loop
    ↓
AuditWriter      → Excel limpio + audit trail
    ↓
Output: archivo corregido + reporte de cambios / API response
```

### Por qué llama la atención:
- Cubre **Data Engineering for AI** — top 9 skill en demanda, especialización emergente
- Es **RAG-adjacent**: comparar contra una DB de categorías válidas es retrieval
  sobre datos estructurados
- Tiene **evaluation layer** integrada: se puede medir precision/recall con un
  dataset de prueba con errores conocidos — exactamente lo que diferencia portfolios
- **Deployable**: FastAPI + Docker + Render/Railway → el recruiter puede abrir una URL
- Caso de uso enterprise directo y explicable en 30 segundos
