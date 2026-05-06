# ADR 0001 — Deploy: Hugging Face Spaces + Docker

**Status:** Accepted  
**Date:** 2026-05-05

## Context

The project needs a deploy story to signal production-readiness to recruiters.
Two concerns: local reproducibility (anyone who clones the repo can run it) and a
live demo URL (a recruiter can see it running without cloning anything).

The LLM already has two providers in the stack: LM Studio for dev, Groq for prod.
No code changes are needed to the pipeline — only the entrypoint and secrets change.

## Decision

**Dockerfile + docker-compose.yml** for local reproducibility.  
**Hugging Face Spaces** as the free public deploy target for the Chainlit UI (`app.py`).

Rejected alternatives:
- **Railway** — free tier is $5 credit/month, not truly unlimited
- **Render** — free tier spins down after 15 min of inactivity; bad UX for demos
- **Fly.io** — requires credit card even for free tier

## Consequences

- The Chainlit UI (`app.py`) is the deployed entrypoint — it uses Groq in production
- The REST API (`agent_os.py`) is not deployed publicly; it runs locally via docker-compose
- A `.env.example` file must be committed so cloners know what variables to set
- `GROQ_API_KEY` must be set as a HF Spaces secret (never in the repo)
- LM Studio config stays in `.env` (local dev only, not needed in the Docker image)