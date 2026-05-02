import logging
from typing import Literal

from pydantic import BaseModel, model_validator

from agno.agent import Agent
from agno.workflow import OnError, Step, StepInput, StepOutput

from agents.mapping_pipeline import PipelineConfig, score, routing_band
from agents.translator_agent import translate, TranslationResult
from agents.validator_agent import ValidatorResult
from infrastructure.pipeline.contracts import CategoryValidation
from domain.onet import is_valid_onet_title
from infrastructure.llm.provider import get_model
from infrastructure.pipeline.session import PipelineSession
from infrastructure.pipeline.step_io import deserialize, fail, ok

logger = logging.getLogger(__name__)


class MappingDecision(BaseModel):
    raw: str
    preprocessed: str
    corrected: str | None          # None when needs_review=True; must be exact CSV value
    confidence: float
    method: Literal["exact", "fuzzy", "llm", "needs_review"]
    normalization_type: Literal["typo", "synonym", "language", "format", "abbreviation", "case", "unknown"]
    needs_review: bool
    review_reason: str | None = None

    @model_validator(mode="after")
    def _review_fields_consistent(self) -> "MappingDecision":
        if self.needs_review and self.review_reason is None:
            raise ValueError("review_reason must be set when needs_review=True")
        if not self.needs_review and self.review_reason is not None:
            raise ValueError("review_reason must be None when needs_review=False")
        return self


class MappingResult(BaseModel):
    decisions: list[MappingDecision]


class SemanticMatch(BaseModel):
    is_equivalent: bool
    canonical_title: str | None    # must be one of the top-3 candidates passed in prompt
    normalization_type: Literal["language", "synonym", "abbreviation", "unknown"]


_mapper_agent: Agent | None = None


def _get_agent() -> Agent:
    global _mapper_agent
    if _mapper_agent is None:
        _mapper_agent = Agent(
            name="MapperAgent",
            model=get_model(),
            output_schema=SemanticMatch,
            instructions=[
                # Role and context
                "You are a job title normalization expert working with the O*NET occupational database (US Dept. of Labor).",
                "Your task: decide if a raw job title is semantically equivalent to one of the provided O*NET canonical titles.",
                # Core rule — is_equivalent
                "Set is_equivalent=true ONLY when the raw title and a candidate describe the SAME professional role.",
                "Set is_equivalent=false when: the role is different, too vague, or none of the candidates fit — even if the words look similar.",
                # Core rule — canonical_title
                "When is_equivalent=true: copy one candidate verbatim into canonical_title. Do NOT rephrase, shorten, or translate.",
                "When is_equivalent=false: canonical_title MUST be null. Never invent a title outside the candidates list.",
                # normalization_type guide with examples
                "Set normalization_type based on WHY the raw title differs from its canonical form:",
                "  language   → raw title is in a foreign language. Example: 'Desarrollador Backend' → 'Backend Web Developers'",
                "  abbreviation → raw title uses an acronym or shorthand. Example: 'RRHH' → 'Human Resources Managers', 'QA' → 'Software Quality Assurance Analysts and Testers'",
                "  synonym    → gender inflection, alternate wording, or job-title variant for the same role. Example: 'Desarrolladora Frontend' → 'Frontend Web Developers'",
                "  unknown    → you cannot determine the reason with confidence.",
                # Hard guardrails
                "NEVER hallucinate: if is_equivalent=true, canonical_title must be exactly one of the candidate strings provided in the prompt.",
                "When in doubt, set is_equivalent=false. A false negative (missed correction) is always safer than a hallucination.",
            ],
        )
    return _mapper_agent


def set_agent(agent: Agent | None) -> None:
    """Override the agent instance. Used by tests to inject a stub without LM Studio."""
    global _mapper_agent
    _mapper_agent = agent


_CONFIG = PipelineConfig()


def _decide(anomaly: CategoryValidation, valid_categories: list[str], valid_categories_set: set[str]) -> MappingDecision:
    fuzzy = score(anomaly.raw, valid_categories, _CONFIG)
    band = routing_band(fuzzy.top_score, _CONFIG)
    translation = TranslationResult(english_title=anomaly.raw, was_translated=False, normalization_type="unknown")

    def _review(review_reason: str) -> MappingDecision:
        return MappingDecision(
            raw=anomaly.raw,
            preprocessed=fuzzy.preprocessed,
            corrected=None,
            confidence=fuzzy.top_score,
            method="needs_review",
            normalization_type="unknown",
            needs_review=True,
            review_reason=review_reason,
        )

    if fuzzy.top_match is None:
        return _review("no_candidates")

    if band == "review":
        translation = translate(anomaly.raw)
        if translation.was_translated:
            fuzzy_t = score(translation.english_title, valid_categories, _CONFIG)
            band_t = routing_band(fuzzy_t.top_score, _CONFIG)
            if band_t != "review":
                fuzzy = fuzzy_t
                band = band_t
        if band == "review":
            return _review("low_confidence")

    if band == "exact":
        return MappingDecision(
            raw=anomaly.raw,
            preprocessed=fuzzy.preprocessed,
            corrected=fuzzy.top_match,
            confidence=fuzzy.top_score,
            method="exact",
            normalization_type="format",
            needs_review=False,
        )

    if band == "fuzzy":
        return MappingDecision(
            raw=anomaly.raw,
            preprocessed=fuzzy.preprocessed,
            corrected=fuzzy.top_match,
            confidence=fuzzy.top_score,
            method="fuzzy",
            normalization_type=translation.normalization_type if translation.was_translated else "typo",
            needs_review=False,
        )

    # band == "llm": call LLM with top candidates
    candidates_text = "\n".join(
        f"  {i+1}. {title} (score: {s:.2f})"
        for i, (title, s) in enumerate(fuzzy.candidates)
    )
    prompt = (
        f'Job title to normalize: "{anomaly.raw}"\n'
        f'Preprocessed form: "{fuzzy.preprocessed}"\n'
        f"Candidate canonical titles (ranked by similarity):\n{candidates_text}\n\n"
        "Select the best match if semantically equivalent, or return null if none fit."
    )

    try:
        run_result = _get_agent().run(prompt)
        if not isinstance(run_result.content, SemanticMatch):
            raise TypeError(f"LLM returned unexpected content type: {type(run_result.content).__name__}")
        semantic: SemanticMatch = run_result.content

        candidate_titles = {title for title, _ in fuzzy.candidates}

        if semantic.is_equivalent:
            # LLM claims a match — canonical_title must be a valid O*NET title in our candidates
            if not is_valid_onet_title(semantic.canonical_title, valid_categories_set) or semantic.canonical_title not in candidate_titles:
                logger.warning("LLM hallucination for %r: returned %r", anomaly.raw, semantic.canonical_title)
                return _review("llm_hallucination")
            return MappingDecision(
                raw=anomaly.raw,
                preprocessed=fuzzy.preprocessed,
                corrected=semantic.canonical_title,
                confidence=fuzzy.top_score,
                method="llm",
                normalization_type=semantic.normalization_type,
                needs_review=False,
            )

        # LLM said not equivalent — legitimate no-match, not a hallucination
        return _review("llm_no_match")

    except Exception as exc:
        logger.warning("LLM call failed for %r: %s", anomaly.raw, exc)
        return _review("llm_error")


def mapper_executor(step_input: StepInput, session_state: dict) -> StepOutput:
    try:
        session = PipelineSession.from_dict(session_state)
        validator_result = deserialize(step_input.previous_step_content, ValidatorResult)

        decisions = [
            _decide(anomaly, session.valid_categories, session.valid_categories_set)
            for anomaly in validator_result.anomalies
        ]

        result = MappingResult(decisions=decisions)
        return ok(result)
    except Exception as e:
        return fail(e)


mapper_step = Step(name="map", executor=mapper_executor, on_error=OnError.fail)