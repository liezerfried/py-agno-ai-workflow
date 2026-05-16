import logging
from typing import Literal

from pydantic import BaseModel

from agno.agent import Agent
from agno.db.sqlite import SqliteDb

from infrastructure.llm.provider import get_model

logger = logging.getLogger(__name__)


# Structured output enforced by Agno via output_schema — prevents free-text responses
# and guarantees the pipeline always receives a typed object, never a raw string.
class TranslationResult(BaseModel):
    english_title: str
    was_translated: bool
    # Defaults to "unknown" so callers can distinguish "agent didn't know" from an explicit classification.
    normalization_type: Literal["language", "abbreviation", "unknown"] = "unknown"


# Module-level singleton: Agent construction is expensive (model init, instruction parsing),
# so the instance is reused across calls within the same process lifetime.
_translator_agent: Agent | None = None


# Shared SqliteDb pointing at the same file the tracer and AgentOS use, so the
# AgentSession this Agent creates lands in the same store as the workflow
# session and the os.agno.com UI can stitch them together.
_AGENT_DB = SqliteDb(db_file="tmp/agentos.db")


def _get_agent() -> Agent:
    global _translator_agent
    if _translator_agent is None:
        _translator_agent = Agent(
            name="TranslatorAgent",
            # Model is resolved at runtime from infrastructure/llm/provider.py so the
            # same agent code works in dev (LM Studio) and prod (Groq) without changes.
            model=get_model(),
            db=_AGENT_DB,
            # output_schema forces the LLM to return a JSON object matching TranslationResult.
            # Agno validates the response against the schema before returning it.
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


# Module-level translation cache. Same rationale as the decision cache in
# mapper_agent: short-circuits repeated inputs within a single process so the
# pipeline never re-pays the LLM for an answer it already has. Combined with
# temperature=0 in the model layer, cache hits return the same English title
# the LLM would produce on a fresh call. Failures are cached too (the raw
# passthrough fallback) so a transient upstream failure does not turn into a
# retry storm when the same raw shows up again.
_translation_cache: dict[str, TranslationResult] = {}


def clear_translation_cache() -> None:
    """Drop every cached translation. Used by tests and by callers that want
    to force a fresh LLM call after, e.g., changing prompts or model config."""
    _translation_cache.clear()


def translate(raw: str, session_id: str | None = None) -> TranslationResult:
    """
    Translate a raw job title to an English canonical form.

    session_id (optional): when forwarded by mapper_executor, ties this
    TranslatorAgent.run() to the parent workflow session in the AgentOS UI
    so all inner agent calls appear under one cohesive session instead of
    spawning their own. Omitted callers keep the legacy single-session-per-
    agent behavior (used by direct CLI / test invocations).
    """
    cached = _translation_cache.get(raw)
    if cached is not None:
        return cached
    try:
        # Only pass session_id when explicitly provided so that the agent.run
        # call site does not change for callers that never had it (legacy tests,
        # the Chainlit path with manual orchestration).
        run_kwargs = {"session_id": session_id} if session_id is not None else {}
        result = _get_agent().run(f'Job title: "{raw}"', **run_kwargs)
        # Agno wraps the validated Pydantic object in RunResponse.content.
        # The isinstance check guards against unexpected model output that bypassed schema validation.
        if isinstance(result.content, TranslationResult):
            tr = result.content
        else:
            raise TypeError(f"Unexpected content type: {type(result.content).__name__}")
    except Exception as exc:
        # On any failure (network, schema mismatch, timeout) the raw title is returned unchanged
        # so the pipeline never drops a row — it escalates to human review instead of crashing.
        logger.warning("Translation failed for %r: %s", raw, exc)
        tr = TranslationResult(english_title=raw, was_translated=False, normalization_type="unknown")
    _translation_cache[raw] = tr
    return tr


def set_agent(agent: Agent | None) -> None:
    """Override the agent instance. Used by tests to inject a stub."""
    # Passing None resets the singleton so the real agent is rebuilt on the next translate() call.
    # This keeps tests hermetic: each test can inject a controlled stub without leaking state
    # into subsequent tests that expect the real agent.
    global _translator_agent
    _translator_agent = agent
