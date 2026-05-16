# Diagnóstico: "loop infinito" al procesar 100 filas

**Fecha:** 2026-05-08
**Branch:** `feature/observability`
**Reportado por:** usuario, vía Chainlit + LM Studio local

## Síntoma

Al subir `data/test_100_autodetect.xlsx` (100 filas) por la UI de Chainlit
contra LM Studio local, el proceso parecía no terminar nunca. La consola
mostraba HTTP 200 sueltos, sin progreso visible. El usuario lo describió
como "loop infinito".

## Diagnóstico

No era un loop. Era **procesamiento secuencial bloqueante de ~6 minutos
sin ningún feedback al usuario**.

Datos del harness `scripts/repro_pipeline.py` con instrumentación per-anomaly:

```
98 unique anomalies (de 100 filas; 0 valid contra O*NET)
Mapper total:  340.9s  (5min 41s)
Per-anomaly:   p50=2.85s   p95=6.51s   max=7.87s
Distribución:  fuzzy=5%   llm=63%   needs_review=32%
LLM calls:     281 LMStudio.invoke spans (avg 2.1s, max 12.4s)
Trafico:       191 MapperAgent.run + 89 TranslatorAgent.run
```

### Hipótesis evaluadas

| Hipótesis | Resultado |
|-----------|-----------|
| H1 — Latencia secuencial acumulada | ✅ Confirmada |
| H2 — Sin timeout (hang real posible) | ⚠️ Riesgo latente, max LLM 12.4s no es hang pero sin tope |
| H3 — Retries silenciosos por schema | ❌ Descartada (281 calls = 191 mapper + 89 translator, sin overshoot) |

### Hallazgos secundarios

- **Pares masc/fem duplicados** (`Administrador/a`, `Analista Financiero/a`,
  `Cientifico/a`, `Desarrollador/a`, `Gerente/a` ×2). Cada par paga el LLM
  dos veces para el mismo trabajo subyacente. Costo evitable ~60s.
- **Indeterminismo del LLM en casos borderline:** `Desarrollador Web` →
  needs_review pero `Desarrolladora Web` → llm aceptado, mismo score.
- **`RRHH` → needs_review** pese a estar como ejemplo explícito en el
  prompt del MapperAgent. Sugiere problema en cómo llegan los candidates
  top-3 después de la traducción.

## Causa raíz

`agents/mapper_agent.mapper_executor` itera anomalies en list-comprehension
serial. Cada anomalía en banda *review* o *llm* dispara 1–2 calls a un LLM
local (qwen3.5-9b en LM Studio). 98 anomalías × ~3s promedio = ~6 minutos.
Durante esos 6 minutos el `cl.Step` en Chainlit muestra "Running…" sin
cambios. El usuario no puede distinguir "procesando" de "colgado".

## Fix aplicado (P0)

Dos cambios mínimos, sin alterar la lógica de routing:

### 1. Progress callback en `mapper_agent.py`

Variable de módulo + setter (mismo patrón que `set_agent`):

- `set_progress_callback(fn: Callable[[int, int], None] | None)`
- `mapper_executor` invoca `_emit_progress(0, total)` antes de empezar y
  `_emit_progress(i, total)` tras cada anomaly.
- Excepciones del callback se atrapan y loggean: un observer roto no aborta
  un run.

### 2. Cableado en `app.py` (tres iteraciones)

La integración con la UI de Chainlit requirió tres intentos. El callback
funcionaba (validado por tests + harness CLI), pero ningún update llegaba al
browser. Los intentos:

1. **`cl_step.output = label; await cl_step.update()`** desde un coroutine
   programado vía `asyncio.run_coroutine_threadsafe`. **Falla**: Chainlit
   identifica la sesión activa por un `ContextVar` que no se propaga al Task
   creado por `run_coroutine_threadsafe`. Fix parcial: capturar el contexto
   con `contextvars.copy_context()` y usar `ctx.run(lambda: asyncio.ensure_future(...))`.
2. **Mismo patrón pero mutando `cl_step.name`**. **Falla**: los docs de
   Chainlit muestran `step.update()` siempre llamado *después* del `async
   with`. La primitiva no soporta refresh mid-flight; los cambios se
   aplican al cerrar el step.
3. **`cl.TaskList`**. Funciona técnicamente, pero los docs aclaran que se
   renderiza "next to the chatbot UI" (panel lateral), no inline en el
   chat. El usuario no lo veía y asumía que no había cambios.
4. **`cl.Message` que se actualiza con `update()`** (final). Aparece inline
   en el flujo del chat y es exactamente el mecanismo que usa Chainlit para
   streamear tokens del LLM — battle-tested. **Funciona.**

`_make_message_progress_callback(progress_msg, display_name, loop)` construye
el callback thread-safe que actualiza `progress_msg.content` y llama
`progress_msg.update()`. Mantiene la captura de `contextvars` del intento 1.

UX final del mensaje en vivo:

```
MapperAgent — starting…
MapperAgent — 5/98 mapped (5%) • ~3:12 remaining
MapperAgent — 50/98 mapped (51%) • ~1:18 remaining
MapperAgent — 98/98 mapped
                                                   ← progress_msg.remove()
✓ Used MapperAgent (con summary expandible)
```

Throttle: la UI se actualiza cada 5 anomalías + el evento terminal. El
contador serial fire por cada anomaly (decoupled del throttling visual).

Al cerrar el step el mensaje se borra con `progress_msg.remove()` para
evitar duplicación con el `cl.Step` que ya muestra "Used MapperAgent".
En caso de fallo (`output.success == False`) el mensaje conserva el
estado `failed` para dejar evidencia visible del stage roto.

### 3. Timeout configurable en `provider.py`

`get_model()` lee `LLM_TIMEOUT_SECONDS` (default 60) y lo pasa a
`LMStudio(timeout=…)` y `Groq(timeout=…)`. Si LM Studio se cuelga real,
la call se cae a `TimeoutError` y `_handle_llm` la absorbe en
`needs_review` (path ya cubierto por `test_llm_timeout_falls_back_to_needs_review`).

## Tests añadidos

- `tests/test_mapper_progress.py` — 9 tests:
  - 4 de progress callback: emite `(0,total)` al inicio, `(total,total)` al
    final; runs sin callback no rompen; aislamiento entre runs; lista vacía
    emite `(0,0)`.
  - 5 de concurrencia: orden preservado bajo paralelismo; callback
    thread-safe llega a `(total,total)`; `MAPPER_CONCURRENCY=1` cae a serial;
    valores inválidos caen al default; **wall-clock test** (8 anomalías ×
    0.4s sleep deben terminar en <1.6s, no 3.2s — detecta regresión a serial).
- `tests/test_provider.py` — 4 tests: default 60s, override por env,
  Groq también, env mal formado cae al default.

Suite completa: **168 passed, 2 deselected (real_llm)**.

## Fix adicional aplicado (P1.2 — paralelización)

Tras P0, corrimos un benchmark sintético de 4 calls paralelas vs seriales
contra LM Studio: serial 15.4s, paralelo 4.8s → 3.2× speedup. LM Studio
soporta concurrencia. Procedimos con paralelización.

### Cambios

- `_resolve_concurrency()` en `mapper_agent.py` lee `MAPPER_CONCURRENCY`
  (default 4). Valores ≤1 fuerzan path serial; valores inválidos caen al
  default sin abortar.
- `mapper_executor` usa `ThreadPoolExecutor` cuando `concurrency > 1` y
  `total > 1`; preserva orden de salida re-indexando por posición original
  (`decisions[idx] = future.result()`); progress callback dispara desde el
  hilo principal (`as_completed` bloquea ahí), por lo que no hay race en
  el contador.
- Tests añadidos: orden preservado, callback alcanza `(total, total)`,
  fallback a serial con concurrency=1, valor inválido cae a default,
  **wall-clock test** que detecta paralelismo real (8 anomalías × 0.4s
  sleep deben terminar en <1.6s, no en 3.2s).

### Resultado E2E (mismo archivo, 100 filas)

| Métrica | Serial (P0) | Paralelo (P1.2) | Speedup |
|---------|-------------|------------------|---------|
| Wall-clock harness | 340.9s | **160.7s** | **2.12×** |
| Per-anomaly avg | 3.48s | 1.64s  | 2.12× |

### Validación E2E final desde Chainlit (2026-05-09)

| Métrica | Valor |
|---------|-------|
| Filas | 100 |
| Corregidas | 78 |
| Review queue | 22 |
| Hallucinations | 0 |
| Precision | 100% |

Los traces de Agno confirman 4 `MapperAgent.run` arrancando dentro de un
intervalo de 876 ms (paralelización en flujo real, no sólo en harness).
El usuario reportó que vio el contador subir desde "5/98 mapped" hasta
"98/98 mapped" con ETA decreciendo en vivo, y al terminar el mensaje de
progreso desapareció dejando solo el `cl.Step` "Used MapperAgent" expandible.

El speedup real (2.1×) es menor que el sintético (3.2×) porque ~32% de
las anomalías encadenan TranslatorAgent + MapperAgent en serie por fila;
LM Studio aún serializa esa cadena interna a un solo worker.

### Hallazgo bonus

Distribución de métodos cambió entre runs sin tocar prompts ni datos:

| Método | Run serial | Run paralelo |
|--------|-----------|--------------|
| llm | 62 | 74 (+12) |
| needs_review | 31 | 19 (−12) |

Es **varianza estocástica del LLM** en casos borderline, ya observada
con "Desarrollador Web" → needs_review vs "Desarrolladora Web" → llm
aceptado. Confirma la necesidad de cache de decisiones + `temperature=0`
para reproducibilidad. Pendiente como P2.

## Lo que NO se cambió (intencional)

- **Dedupe semántico post-translation** (cachear `translate(raw)` y reusar
  para variantes género/abreviatura): bajaría ~10–15% de calls. Diferido
  a P2 — el efecto sobre wall-clock es chico ahora que la paralelización
  ya bajó el total a 2:41.
- **Cache de decisiones del Mapper** + `temperature=0`: necesario para que
  un mismo input dé el mismo output entre runs. P2.
- **Threshold del 32% needs_review** (revisar candidates top-3 y
  `instructions` del MapperAgent): mejora calidad, no latencia. P2.
- **Migración de Chainlit a `_workflow.run()`**: necesaria para que los
  runs de Chainlit aparezcan en `os.agno.com`. Diferida a P3 — orthogonal
  al cuelgue.

## Referencias

- Harness de repro: `scripts/repro_pipeline.py`
- Inspector de traces: `scripts/inspect_last_run.py`
- DB unificada: `tmp/agentos.db` (Agno traces + sessions + pipeline_runs)
