"""
Maps each anomalous job category to the closest canonical O*NET title.
Routing: rapidfuzz score determines whether the match is accepted automatically
(exact >= 0.90), sent to the LLM for semantic evaluation (0.70-0.89), or escalated
to the human review queue (< 0.70). The LLM is never called when rapidfuzz alone
is sufficient — this keeps token cost proportional to actual ambiguity.
"""
import logging
from typing import Literal

from pydantic import BaseModel, model_validator

from agno.agent import Agent
from agno.workflow import OnError, Step, StepInput, StepOutput

from agents.mapping_pipeline import FuzzyResult, PipelineConfig, score, routing_band
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

    # Pydantic model_validator enforces the invariant at construction time so no
    # caller can accidentally build an inconsistent MappingDecision at runtime.
    @model_validator(mode="after")
    def _review_fields_consistent(self) -> "MappingDecision":
        if self.needs_review and self.review_reason is None:
            raise ValueError("review_reason must be set when needs_review=True")
        if not self.needs_review and self.review_reason is not None:
            raise ValueError("review_reason must be None when needs_review=False")
        return self


class MappingResult(BaseModel):
    decisions: list[MappingDecision]


# Separate from MappingDecision intentionally: this is the LLM's raw output schema.
# Keeping it narrow limits what the model can say — it cannot return a confidence score
# or a review reason, which are computed by the pipeline, not the LLM.
class SemanticMatch(BaseModel):
    is_equivalent: bool
    canonical_title: str | None    # must be one of the top-3 candidates passed in prompt
    normalization_type: Literal["language", "synonym", "abbreviation", "unknown"]


# Lazy singleton — the Agent instantiation triggers model loading, which is
# expensive. Deferring it means import-time is fast and tests that inject a stub
# via set_agent() never pay the cost of creating a real agent.
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
                "  language   -> raw title is in a foreign language. Example: 'Desarrollador Backend' -> 'Backend Web Developers'",
                "  abbreviation -> raw title uses an acronym or shorthand. Example: 'RRHH' -> 'Human Resources Managers', 'QA' -> 'Software Quality Assurance Analysts and Testers'",
                "  synonym    -> gender inflection, alternate wording, or job-title variant for the same role. Example: 'Desarrolladora Frontend' -> 'Frontend Web Developers'",
                "  unknown    -> you cannot determine the reason with confidence.",
                # Hard guardrails
                "NEVER hallucinate: if is_equivalent=true, canonical_title must be exactly one of the candidate strings provided in the prompt.",
                "When in doubt, set is_equivalent=false. A false negative (missed correction) is always safer than a hallucination.",
            ],
        )
    return _mapper_agent


def set_agent(agent: Agent | None) -> None:
    """Override the agent instance. Used by tests to inject a stub without LM Studio."""
    # Passing None resets the singleton so the real agent is rebuilt on the next LLM-band call.
    # Tests that stay in the exact/fuzzy band never call this — only tests covering the LLM
    # path need to inject a stub.
    global _mapper_agent
    _mapper_agent = agent


# Module-level config so thresholds and top-N candidates are shared across all
# _decide() calls without being re-instantiated per row.
_CONFIG = PipelineConfig()


# Centralised helper so every escalation path logs at the same level with the same
# fields — makes grepping the audit log for review cases reliable.
def _needs_review(anomaly: CategoryValidation, fuzzy: FuzzyResult, reason: str) -> MappingDecision:
    logger.info("needs_review: raw=%r reason=%s score=%.4f", anomaly.raw, reason, fuzzy.top_score)
    return MappingDecision(
        raw=anomaly.raw,
        preprocessed=fuzzy.preprocessed,
        corrected=None,
        confidence=fuzzy.top_score,
        method="needs_review",
        normalization_type="unknown",
        needs_review=True,
        review_reason=reason,
    )


def _handle_exact(anomaly: CategoryValidation, fuzzy: FuzzyResult) -> MappingDecision:
    logger.info("exact: raw=%r -> %r score=%.4f", anomaly.raw, fuzzy.top_match, fuzzy.top_score)
    return MappingDecision(
        raw=anomaly.raw,
        preprocessed=fuzzy.preprocessed,
        corrected=fuzzy.top_match,
        confidence=fuzzy.top_score,
        method="exact",
        normalization_type="format",
        needs_review=False,
    )


def _handle_fuzzy(anomaly: CategoryValidation, fuzzy: FuzzyResult, translation: TranslationResult) -> MappingDecision:
    # If a translation was attempted upstream and it lifted the score into the fuzzy band,
    # the normalization type comes from the translator. If no translation was needed,
    # the mismatch is a typo/format issue resolved by rapidfuzz alone.
    norm_type = translation.normalization_type if translation.was_translated else "typo"
    logger.info("fuzzy: raw=%r -> %r score=%.4f norm_type=%s", anomaly.raw, fuzzy.top_match, fuzzy.top_score, norm_type)
    return MappingDecision(
        raw=anomaly.raw,
        preprocessed=fuzzy.preprocessed,
        corrected=fuzzy.top_match,
        confidence=fuzzy.top_score,
        method="fuzzy",
        normalization_type=norm_type,
        needs_review=False,
    )


def _handle_llm(anomaly: CategoryValidation, fuzzy: FuzzyResult, valid_categories_set: set[str]) -> MappingDecision:
    logger.info("llm: raw=%r score=%.4f candidates=%s", anomaly.raw, fuzzy.top_score, [t for t, _ in fuzzy.candidates])
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

        # Build a set of the exact strings the LLM was shown so we can verify its answer
        # is one of them — not a rephrasing or an invented title.
        candidate_titles = {title for title, _ in fuzzy.candidates}

        if semantic.is_equivalent:
            # Double guard: check both the global O*NET set and the candidates we sent.
            # The LLM may return a valid O*NET title that was NOT in the prompt candidates
            # (a hallucination that happens to exist in the DB); both checks are required.
            if not is_valid_onet_title(semantic.canonical_title, valid_categories_set) or semantic.canonical_title not in candidate_titles:
                logger.warning("LLM hallucination for %r: returned %r", anomaly.raw, semantic.canonical_title)
                return _needs_review(anomaly, fuzzy, "llm_hallucination")
            logger.info("llm accepted: raw=%r -> %r norm_type=%s", anomaly.raw, semantic.canonical_title, semantic.normalization_type)
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
        return _needs_review(anomaly, fuzzy, "llm_no_match")

    except Exception as exc:
        logger.warning("LLM call failed for %r: %s", anomaly.raw, exc)
        return _needs_review(anomaly, fuzzy, "llm_error")


def _decide(anomaly: CategoryValidation, valid_categories: list[str], valid_categories_set: set[str]) -> MappingDecision:
    """
    Produce a MappingDecision for a single anomalous category.

    Routing logic:
      1. Run rapidfuzz to get a top score and candidate list.
      2. If score >= 0.90 (exact band)  -> accept automatically, no LLM call.
      3. If score 0.70-0.89 (fuzzy band) -> accept automatically (high-confidence fuzzy).
      4. If score < 0.70 (review band)  -> try translation first; if that lifts the
         score into a higher band, re-route. Otherwise escalate to human review.
      5. If still in review band after translation -> needs_review=True, no correction written.
      6. If routed to LLM -> call the agent; validate its output; accept or reject.
    """
    fuzzy = score(anomaly.raw, valid_categories, _CONFIG)
    band = routing_band(fuzzy.top_score, _CONFIG)
    translation = TranslationResult(english_title=anomaly.raw, was_translated=False, normalization_type="unknown")

    if fuzzy.top_match is None:
        return _needs_review(anomaly, fuzzy, "no_candidates")

    if band == "review":
        # Before giving up, try translating the raw title to English — a Spanish title
        # that scores < 0.70 against O*NET (all English) may score much higher after
        # translation (e.g. "Desarrollador Backend" -> "Backend Developer" -> 0.91).
        translation = translate(anomaly.raw)
        if translation.was_translated:
            fuzzy_t = score(translation.english_title, valid_categories, _CONFIG)
            band_t = routing_band(fuzzy_t.top_score, _CONFIG)
            if band_t != "review":
                # Translation lifted the score into a workable band — use the new results.
                fuzzy = fuzzy_t
                band = band_t
        if band == "review":
            return _needs_review(anomaly, fuzzy, "low_confidence")

    if band == "exact":
        return _handle_exact(anomaly, fuzzy)
    if band == "fuzzy":
        return _handle_fuzzy(anomaly, fuzzy, translation)
    return _handle_llm(anomaly, fuzzy, valid_categories_set)


def mapper_executor(step_input: StepInput, session_state: dict) -> StepOutput:
    """
    Agno Step executor: runs _decide() for every anomaly produced by ValidatorAgent.

    Pipeline order: IngestAgent -> ValidatorAgent -> MapperAgent (this step) -> AuditWriter

    Only the anomalies list is processed here — categories already validated as exact
    O*NET titles are passed through unchanged by AuditWriter without touching this step.
    """
    try:
        # session_state is the shared dict Agno passes between Steps; from_dict reconstructs
        # the typed PipelineSession so we get the pre-loaded valid_categories list/set.
        session = PipelineSession.from_dict(session_state)
        # previous_step_content is raw JSON from ValidatorAgent's StepOutput; deserialize
        # parses it back into a typed ValidatorResult so _decide() receives structured data.
        validator_result = deserialize(step_input.previous_step_content, ValidatorResult)

        decisions = [
            _decide(anomaly, session.valid_categories, session.valid_categories_set)
            for anomaly in validator_result.anomalies
        ]

        result = MappingResult(decisions=decisions)
        # ok() serialises result to JSON and wraps it in a successful StepOutput so
        # AuditWriter can deserialize it from step_input.previous_step_content.
        return ok(result)
    except Exception as e:
        # fail() marks the StepOutput as failed; on_error=OnError.fail on the Step
        # stops the workflow and surfaces the error to the caller.
        return fail(e)


mapper_step = Step(name="map", executor=mapper_executor, on_error=OnError.fail)