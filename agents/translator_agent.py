import logging
from typing import Literal

from pydantic import BaseModel

from agno.agent import Agent

from infrastructure.llm.provider import get_model

logger = logging.getLogger(__name__)


class TranslationResult(BaseModel):
    english_title: str
    was_translated: bool
    normalization_type: Literal["language", "abbreviation", "unknown"] = "unknown"


_translator_agent: Agent | None = None


def _get_agent() -> Agent:
    global _translator_agent
    if _translator_agent is None:
        _translator_agent = Agent(
            name="TranslatorAgent",
            model=get_model(),
            output_schema=TranslationResult,
            instructions=[
                "You receive a job title that may be in Spanish or use abbreviations/acronyms.",
                "Your task: normalize it to a short English job title.",
                "",
                "Rules:",
                "1. Translate Spanish to English.",
                "2. Expand abbreviations and acronyms to full English words.",
                "   Examples: RRHH -> Human Resources, DBA -> Database Administrator, RN -> Registered Nurse",
                "3. Remove gender inflection: use the neutral English form.",
                "   Examples: Desarrolladora -> Developer, Analista Financiera -> Financial Analyst",
                "4. Do NOT add or remove seniority words — keep the core role only.",
                "5. Return ONLY the short job title — no explanations, no punctuation.",
                "6. If the title is already in English and needs no changes: return it unchanged with was_translated=false.",
                "",
                "Set normalization_type:",
                "  language     -> input was in a foreign language",
                "  abbreviation -> input was an acronym or shorthand",
                "  unknown      -> cannot determine",
                "",
                "Examples:",
                "  'Desarrollador de Software'  -> english_title='Software Developer',  was_translated=true,  normalization_type='language'",
                "  'Analista Financiera'         -> english_title='Financial Analyst',   was_translated=true,  normalization_type='language'",
                "  'RRHH'                        -> english_title='Human Resources',     was_translated=true,  normalization_type='abbreviation'",
                "  'DBA'                         -> english_title='Database Administrator', was_translated=true, normalization_type='abbreviation'",
                "  'RN'                          -> english_title='Registered Nurse',    was_translated=true,  normalization_type='abbreviation'",
                "  'Software Developer'          -> english_title='Software Developer',  was_translated=false, normalization_type='unknown'",
            ],
        )
    return _translator_agent


def translate(raw: str) -> TranslationResult:
    try:
        result = _get_agent().run(f'Job title: "{raw}"')
        if isinstance(result.content, TranslationResult):
            return result.content
        raise TypeError(f"Unexpected content type: {type(result.content).__name__}")
    except Exception as exc:
        logger.warning("Translation failed for %r: %s", raw, exc)
        return TranslationResult(english_title=raw, was_translated=False, normalization_type="unknown")


def set_agent(agent: Agent | None) -> None:
    """Override the agent instance. Used by tests to inject a stub."""
    global _translator_agent
    _translator_agent = agent
