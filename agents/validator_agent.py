from pydantic import BaseModel
from rapidfuzz import fuzz, process

from agno.workflow import OnError, Step, StepInput, StepOutput

from agents.ingest_agent import IngestResult


class CategoryValidation(BaseModel):
    raw: str
    is_valid: bool
    closest_match: str | None
    similarity_score: float   # 0.0–1.0


class ValidatorResult(BaseModel):
    validations: list[CategoryValidation]
    valid_count: int
    anomaly_count: int
    anomalies: list[CategoryValidation]   # subset where is_valid=False


def _validate_category(raw: str, valid_categories: list[str]) -> CategoryValidation:
    if raw in valid_categories:
        return CategoryValidation(raw=raw, is_valid=True, closest_match=None, similarity_score=1.0)

    match = process.extractOne(raw, valid_categories, scorer=fuzz.WRatio)
    if match is None:
        return CategoryValidation(raw=raw, is_valid=False, closest_match=None, similarity_score=0.0)

    closest, score, _ = match
    return CategoryValidation(
        raw=raw,
        is_valid=False,
        closest_match=closest,
        similarity_score=round(score / 100.0, 4),
    )


def validator_executor(step_input: StepInput, session_state: dict) -> StepOutput:
    try:
        ingest_result = IngestResult.model_validate_json(step_input.previous_step_content)
        valid_categories: list[str] = session_state["valid_categories"]

        validations = [_validate_category(raw, valid_categories) for raw in ingest_result.raw_categories]
        anomalies = [v for v in validations if not v.is_valid]

        result = ValidatorResult(
            validations=validations,
            valid_count=len(validations) - len(anomalies),
            anomaly_count=len(anomalies),
            anomalies=anomalies,
        )
        return StepOutput(content=result.model_dump_json())
    except Exception as e:
        return StepOutput(content=str(e), success=False, stop=True)


validator_step = Step(name="validate", executor=validator_executor, on_error=OnError.fail)