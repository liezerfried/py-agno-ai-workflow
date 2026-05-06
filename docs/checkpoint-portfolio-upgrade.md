# Checkpoint — Portfolio Upgrade

Sesión de trabajo basada en el feedback de GPT sobre el proyecto.
Objetivo: elevar el MVP de "portfolio-shaped" a "product-shaped" para recruiters.

---

## Issues completados

### #10 — Config hygiene: `.env.example`
**Qué se hizo:** Se actualizó `.env.example` con todas las variables actuales, comentarios inline y el link para obtener la Groq API key. Se verificó que `.gitignore` excluye `.env` pero no `.env.example`.

### #11 — Dockerfile + docker-compose
**Qué se hizo:** Se creó `Dockerfile` (Python 3.12 slim + uv) y `docker-compose.yml` con volumen `tmp/` y override `LLM_PROVIDER=groq` para producción. También se creó `.dockerignore`.

**Pendiente de verificación:** El build local no se pudo corroborar porque la virtualización no está habilitada en el BIOS (ver sección más abajo). La estructura del Dockerfile es correcta — HF Spaces lo va a construir en sus propios servidores sin necesitar Docker local.

### #12 — `metrics_store`: tabla `pipeline_runs` en SQLite
**Qué se hizo:** Se creó `infrastructure/pipeline/metrics_store.py` con `record_run()` y `get_recent_runs()`. Se agregó `total_rows` a `AuditResult` y a `_write_excel()`. El `audit_executor` llama `record_run()` automáticamente al final de cada pipeline run. Se agregaron 7 tests nuevos. Suite completa: 155 passed.

### #13 — Chainlit history view
**Qué se hizo:** Se modificó `@cl.on_chat_start` en `app.py` para mostrar una `AskActionMessage` al inicio con dos opciones:
- **Procesar nuevo archivo** → flujo de upload existente sin cambios
- **Ver historial de runs** → tabla markdown con los últimos 20 runs (timestamp, archivo, filas, corregidas, review queue, precisión)

Empty state manejado: si no hay runs previos, muestra un mensaje explicativo en lugar de una tabla vacía.

---

## Issues pendientes

### #14 — Deploy a Hugging Face Spaces *(HITL)*
**Qué hay que hacer:**
1. Ir a [huggingface.co/spaces](https://huggingface.co/spaces) → "Create new Space"
2. Elegir SDK: **Docker**
3. Subir el repo (o conectar con GitHub para auto-deploy)
4. Configurar los secrets en el panel de HF Spaces:
   - `GROQ_API_KEY` — tu key de Groq (nunca en el repo)
   - `AGNO_API_KEY` — tu key de Agno (opcional, para trazabilidad en la nube)
   - `LLM_PROVIDER=groq` — override del provider para producción
5. Verificar que la app arranca y completa un pipeline run desde la URL pública

**Nota:** HF Spaces construye la imagen Docker en sus propios servidores — no necesitás Docker corriendo localmente para esto.

### #15 — README: instrucciones de deploy local + link al Space *(bloqueado por #14)*
**Qué hay que hacer:**
1. Agregar sección "Quick start" en el README con los pasos para correr localmente con Docker
2. Agregar el link al HF Space vivo (una vez que #14 esté completo)
3. Referenciar `.env.example` como punto de partida para la configuración

---

## Pendiente técnico: virtualización Docker

**Diagnóstico:** La CPU soporta virtualización (VT-x presente), pero está **desactivada en el firmware (BIOS)**. Docker Desktop no puede arrancar sin ella.

**Cómo resolverlo:**
1. Reiniciar el equipo y entrar al BIOS (tecla `F2`, `F10`, `Del` o `Esc` al encender — depende del fabricante)
2. Buscar `Intel Virtualization Technology`, `VT-x`, `AMD-V`, o `SVM Mode`
3. Cambiarlo a `Enabled`
4. Guardar y reiniciar (`F10`)
5. Abrir Docker Desktop — debería arrancar sin errores
6. Verificar el build: `docker build -t job-normalizer .` desde la raíz del proyecto
7. Verificar que corre: `docker-compose up` → abrir `http://localhost:8000`

**Si la opción aparece gris en el BIOS**, está bloqueada por configuración de empresa/IT y necesitás pedir que la habiliten.

---

## Estado general del branch

Branch activo: `feature/observability`

```
#10 ✅  #11 ✅  #12 ✅  #13 ✅  #14 ⏳ (HITL)  #15 ⏳ (bloqueado por #14)
```

Cuando retomes: empezá por #14 (crear el HF Space y configurar secrets), luego #15 (actualizar el README con el link vivo).
