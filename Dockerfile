FROM python:3.12-slim

WORKDIR /app

# Install uv — the project's package manager
RUN pip install uv --quiet

# Install dependencies first (separate layer so rebuilds are fast when only code changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code and static data
COPY . .

# Ensure tmp/ exists for SQLite DBs and output Excel files (also mounted as a volume)
RUN mkdir -p tmp

# Make the virtual environment's binaries available without prefixing uv run
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# Production entrypoint: Chainlit UI served on all interfaces
# Set LLM_PROVIDER=groq and GROQ_API_KEY via environment (docker-compose or HF Spaces secrets)
CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"]
