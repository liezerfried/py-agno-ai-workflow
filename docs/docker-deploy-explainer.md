# Docker y Deploy — Conceptos desde cero

## ¿Qué problema resuelve Docker?

Tu proyecto funciona en tu máquina porque tenés Python 3.12, uv, las dependencias instaladas, el archivo `.env` con las API keys, y el path correcto. En otra máquina, nada de eso está garantizado.

Docker resuelve esto empaquetando **todo lo necesario para correr la app** en una unidad portátil llamada **imagen** (image). Quien tenga Docker instalado puede correr tu app con un solo comando, sin importar su sistema operativo.

---

## Los tres conceptos clave

### 1. Dockerfile

Un archivo de texto con instrucciones paso a paso para construir la imagen de tu app. Es como una receta:

```dockerfile
FROM python:3.12-slim          # Empezá desde Python 3.12 limpio
WORKDIR /app                   # Carpeta de trabajo dentro del contenedor
COPY pyproject.toml .          # Copiá el archivo de dependencias
RUN pip install uv && uv sync  # Instalá las dependencias
COPY . .                       # Copiá el resto del código
CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0"]  # Comando para arrancar
```

Cuando corrés `docker build`, Docker lee este archivo y produce una **imagen** — un snapshot inmutable del estado de tu app.

### 2. Imagen (Image)

El resultado de `docker build`. Es como un "archivo ejecutable" que contiene Python, tus dependencias, y tu código. Se puede compartir (subirla a Docker Hub o GitHub Container Registry) o usar localmente.

### 3. Contenedor (Container)

Una instancia corriendo de una imagen. Es lo que arranca cuando hacés `docker run`. Podés tener múltiples contenedores del mismo image corriendo al mismo tiempo.

```
Dockerfile  →  docker build  →  Image  →  docker run  →  Container (proceso vivo)
```

---

## docker-compose.yml

Cuando tu app necesita más de un proceso — por ejemplo, la app + una base de datos — `docker-compose` los orquesta juntos con un solo archivo:

```yaml
services:
  app:
    build: .                      # Usar el Dockerfile de esta carpeta
    ports:
      - "8000:8000"               # Exponer el puerto
    env_file:
      - .env                      # Inyectar variables de entorno
    volumes:
      - ./tmp:/app/tmp            # Persistir archivos generados (output Excel, SQLite DB)

  # Ejemplo: si en el futuro agregaras Postgres
  # db:
  #   image: postgres:16
  #   environment:
  #     POSTGRES_PASSWORD: secret
```

Para este proyecto, en la etapa actual, `docker-compose` tiene un solo servicio (la app). Su valor principal es documentar cómo se corre: qué puertos, qué variables, qué volúmenes.

---

## ¿Por qué importa para el portfolio?

Un recruiter técnico o tech lead que ve el repo sabe leer un Dockerfile. Si está bien escrito, comunica:

- "Esta persona entiende cómo se opera el código, no solo cómo se escribe"
- "El proyecto puede correrse en cualquier entorno en minutos"
- "Hay una historia clara de deploy, no solo scripts locales"

---

## Hugging Face Spaces — Deploy gratuito

Para este proyecto, **Hugging Face Spaces** es la mejor opción gratuita por estas razones:

1. **Soporte nativo de Chainlit** — HF Spaces tiene un preset específico para Chainlit apps
2. **Completamente gratuito** — sin límite de horas ni spin-down (a diferencia de Render)
3. **Conocido en el mundo AI/ML** — los recruiters de AI lo conocen; un link a `huggingface.co/spaces/tu-usuario/tu-app` tiene peso
4. **Sin tarjeta de crédito**

### Cómo funciona

En lugar de un `Dockerfile` genérico, HF Spaces usa un archivo `README.md` con metadata especial al principio:

```yaml
---
title: Job Category Normalizer
emoji: 🗂️
colorFrom: blue
colorTo: green
sdk: docker          # o "chainlit" si tienen preset directo
app_port: 8000
---
```

El `Dockerfile` sigue siendo necesario — HF lo usa para construir y correr la imagen.

---

## El plan concreto para este proyecto

```
1. Dockerfile          — construye la imagen de la app Chainlit
2. docker-compose.yml  — documenta cómo correrla localmente con un solo comando
3. .env.example        — muestra qué variables se necesitan sin exponer los valores reales
4. README.md           — instrucciones de 5 pasos para correrlo local + link al Space en HF
5. HF Space            — deploy del Chainlit UI (entrypoint: app.py + Groq como LLM)
```

---

## Comandos que vas a usar

```bash
# Construir la imagen localmente
docker build -t job-normalizer .

# Correrla localmente (equivalente a chainlit run app.py)
docker-compose up

# Ver los contenedores activos
docker ps

# Ver los logs
docker-compose logs -f
```