import os
from agno.models.lmstudio import LMStudio
from agno.models.groq import Groq


def get_model():
    # Default to LM Studio for local/dev unless LLM_PROVIDER overrides it.
    provider = os.getenv("LLM_PROVIDER", "lmstudio").lower()

    if provider == "groq":
        # Use Groq for prod; model name can be overridden via GROQ_MODEL.
        return Groq(id=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))

    # Fallback to LM Studio; model name can be overridden via LMSTUDIO_MODEL.
    return LMStudio(id=os.getenv("LMSTUDIO_MODEL", "qwen2.5-7b-instruct"))