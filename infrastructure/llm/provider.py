"""
Central factory for the LLM model object used by all agents in the pipeline.
Reads the LLM_PROVIDER environment variable to switch between local dev (LM Studio)
and production (Groq) without touching any agent code.
Invariant: all agents import their model via get_model() from this module — never
instantiate LMStudio or Groq directly in an agent file. Centralizing here means
switching providers in production requires changing only one environment variable.
"""
import os
from agno.models.lmstudio import LMStudio
from agno.models.groq import Groq

# Default upper bound for a single LLM completion. Tuned from the 2026-05-08
# diagnosis: LM Studio's qwen3.5-9b regularly takes 6–8s per call and was
# observed at 12.4s for an outlier. 60s gives ample margin while still ensuring
# a hung remote does not stall the pipeline indefinitely. _handle_llm() in
# mapper_agent.py already absorbs the resulting TimeoutError into needs_review.
_DEFAULT_TIMEOUT_SECONDS = 60


def _resolve_timeout() -> int:
    """Read LLM_TIMEOUT_SECONDS, falling back to the default on missing or invalid input."""
    raw = os.getenv("LLM_TIMEOUT_SECONDS")
    if raw is None:
        return _DEFAULT_TIMEOUT_SECONDS
    try:
        return int(raw)
    except ValueError:
        # Misconfigured env should not abort startup — log-and-default is safer
        # than crashing the whole AgentOS / Chainlit process at import time.
        return _DEFAULT_TIMEOUT_SECONDS


def get_model():
    """
    Return the configured LLM model object for the current environment.

    The model is selected via the LLM_PROVIDER environment variable:

      - "lmstudio" (default): connects to LM Studio, a local server that runs
        open-source models on your own machine. Free, no API key required, but
        LM Studio must be running before the pipeline starts. Best for development.

      - "groq": connects to Groq's hosted API using llama-3.3-70b-versatile.
        Requires a GROQ_API_KEY environment variable. Used in production for
        reliable speed and uptime.

    Both model names can be overridden via additional environment variables:
      - LMSTUDIO_MODEL: local model to load (default: "qwen/qwen3.5-9b").
      - GROQ_MODEL:     Groq model to call  (default: "llama-3.3-70b-versatile").

    Returns:
        An Agno model object (either LMStudio or Groq) ready to be passed as the
        'model' argument when constructing an Agno Agent.
    """
    # Default to LM Studio for local/dev unless LLM_PROVIDER overrides it.
    provider = os.getenv("LLM_PROVIDER", "lmstudio").lower()
    timeout = _resolve_timeout()

    if provider == "groq":
        # Use Groq for prod; model name can be overridden via GROQ_MODEL.
        return Groq(id=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"), timeout=timeout)

    # Fallback to LM Studio; model name can be overridden via LMSTUDIO_MODEL.
    return LMStudio(id=os.getenv("LMSTUDIO_MODEL", "qwen/qwen3.5-9b"), timeout=timeout)
