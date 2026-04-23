import os
from agno.models.lmstudio import LMStudio
from agno.models.groq import Groq


def get_model():
    provider = os.getenv("LLM_PROVIDER", "lmstudio").lower()

    if provider == "groq":
        return Groq(id=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))

    return LMStudio(id=os.getenv("LMSTUDIO_MODEL", "qwen2.5-7b-instruct"))
