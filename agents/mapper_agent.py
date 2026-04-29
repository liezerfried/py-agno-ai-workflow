from typing import Literal

from pydantic import BaseModel
from rapidfuzz import fuzz, process

from agno.agent import Agent
from agno.workflow import OnError, Step, StepInput, StepOutput

from agents.pre_processor import normalize_title
from agents.validator_agent import CategoryValidation, ValidatorResult
from infrastructure.llm.provider import get_model


class MappingDecision(BaseModel):
    raw: str
    preprocessed: str
    corrected: str | None          # None when needs_review=True; must be exact CSV value
    confidence: float
    method: Literal["exact", "fuzzy", "llm", "needs_review"]
    normalization_type: Literal["typo", "synonym", "language", "format", "abbreviation", "case", "unknown"]
    needs_review: bool


class MappingResult(BaseModel):
    decisions: list[MappingDecision]
    auto_corrected_count: int
    llm_evaluated_count: int
    needs_review_count: int


class SemanticMatch(BaseModel):
    is_equivalent: bool
    canonical_title: str | None    # must be one of the top-3 candidates passed in prompt
    normalization_type: Literal["language", "synonym", "abbreviation", "unknown"]
    reasoning: str


mapper_agent = Agent(
    name="MapperAgent",
    model=get_model(),
    output_schema=SemanticMatch,
    instructions=[
        "You receive a job title and up to 3 candidate canonical O*NET occupation titles ranked by similarity.",
        "Decide if the job title is semantically equivalent to any candidate (same role, different words).",
        "Set canonical_title to the exact candidate string if equivalent, null if none fit.",
        "Never invent or modify a title — canonical_title must be copied verbatim from the candidates list.",
        "Set normalization_type to one of: language (title is in a foreign language), abbreviation (title uses an acronym or abbreviation), synonym (gender inflection or alternate wording for the same role), unknown (if unclear).",
        "Provide one sentence of reasoning for the audit trail.",
    ],
)

_TOP_N = 3
_HIGH_THRESHOLD = 0.90
_LOW_THRESHOLD = 0.70


def _decide(anomaly: CategoryValidation, valid_categories: list[str], valid_categories_set: set[str]) -> MappingDecision:
    preprocessed = normalize_title(anomaly.raw)

    top_matches = process.extract(preprocessed, valid_categories, scorer=fuzz.WRatio, limit=_TOP_N)

    if not top_matches:
        return MappingDecision(
            raw=anomaly.raw,
            preprocessed=preprocessed,
            corrected=None,
            confidence=0.0,
            method="needs_review",
            normalization_type="unknown",
            needs_review=True,
        )

    top_match, top_score_raw, _ = top_matches[0]
    top_score = round(top_score_raw / 100.0, 4)

    if top_score == 1.0:
        return MappingDecision(
            raw=anomaly.raw,
            preprocessed=preprocessed,
            corrected=top_match,
            confidence=top_score,
            method="exact",
            normalization_type="format",
            needs_review=False,
        )

    if top_score >= _HIGH_THRESHOLD:
        return MappingDecision(
            raw=anomaly.raw,
            preprocessed=preprocessed,
            corrected=top_match,
            confidence=top_score,
            method="fuzzy",
            normalization_type="typo",
            needs_review=False,
        )

    if top_score < _LOW_THRESHOLD:
        return MappingDecision(
            raw=anomaly.raw,
            preprocessed=preprocessed,
            corrected=None,
            confidence=top_score,
            method="needs_review",
            normalization_type="unknown",
            needs_review=True,
        )

    # 0.70–0.89 band: call LLM with top-3 candidates
    candidates = [m[0] for m in top_matches]
    candidates_text = "\n".join(f"  {i+1}. {c} (score: {round(m[1]/100.0, 2)})" for i, (c, m) in enumerate(zip(candidates, top_matches)))
    prompt = (
        f'Job title to normalize: "{anomaly.raw}"\n'
        f'Preprocessed form: "{preprocessed}"\n'
        f"Candidate canonical titles (ranked by similarity):\n{candidates_text}\n\n"
        "Select the best match if semantically equivalent, or return null if none fit."
    )

    try:
        run_result = mapper_agent.run(prompt)
        semantic: SemanticMatch = run_result.content

        # Guard: canonical_title must be one of the candidates we provided
        if semantic.canonical_title is not None and semantic.canonical_title not in valid_categories_set:
            return MappingDecision(
                raw=anomaly.raw,
                preprocessed=preprocessed,
                corrected=None,
                confidence=top_score,
                method="needs_review",
                normalization_type="unknown",
                needs_review=True,
            )

        if semantic.is_equivalent and semantic.canonical_title in {c for c in candidates}:
            return MappingDecision(
                raw=anomaly.raw,
                preprocessed=preprocessed,
                corrected=semantic.canonical_title,
                confidence=top_score,
                method="llm",
                normalization_type=semantic.normalization_type,
                needs_review=False,
            )

        return MappingDecision(
            raw=anomaly.raw,
            preprocessed=preprocessed,
            corrected=None,
            confidence=top_score,
            method="needs_review",
            normalization_type="unknown",
            needs_review=True,
        )

    except Exception:
        return MappingDecision(
            raw=anomaly.raw,
            preprocessed=preprocessed,
            corrected=None,
            confidence=top_score,
            method="needs_review",
            normalization_type="unknown",
            needs_review=True,
        )


def mapper_executor(step_input: StepInput, session_state: dict) -> StepOutput:
    try:
        validator_result = ValidatorResult.model_validate_json(step_input.previous_step_content)
        valid_categories: list[str] = session_state["valid_categories"]
        valid_categories_set: set[str] = session_state["valid_categories_set"]

        decisions = [_decide(anomaly, valid_categories, valid_categories_set) for anomaly in validator_result.anomalies]

        result = MappingResult(
            decisions=decisions,
            auto_corrected_count=sum(1 for d in decisions if d.method in {"exact", "fuzzy"}),
            llm_evaluated_count=sum(1 for d in decisions if d.method == "llm"),
            needs_review_count=sum(1 for d in decisions if d.needs_review),
        )
        return StepOutput(content=result.model_dump_json())
    except Exception as e:
        return StepOutput(content=str(e), success=False, stop=True)


mapper_step = Step(name="map", executor=mapper_executor, on_error=OnError.fail)