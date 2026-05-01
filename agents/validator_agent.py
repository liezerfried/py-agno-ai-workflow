from rapidfuzz import fuzz, process
from pydantic import BaseModel

from agno.workflow import OnError, Step, StepInput, StepOutput

from agents.ingest_agent import IngestResult
from infrastructure.pipeline.contracts import CategoryValidation
from infrastructure.pipeline.session import PipelineSession
from infrastructure.pipeline.step_io import deserialize, fail, ok


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
        session = PipelineSession.from_dict(session_state)
        ingest_result = deserialize(step_input.previous_step_content, IngestResult)

        validations = [_validate_category(raw, session.valid_categories) for raw in ingest_result.raw_categories]
        anomalies = [v for v in validations if not v.is_valid]

        result = ValidatorResult(
            validations=validations,
            valid_count=len(validations) - len(anomalies),
            anomaly_count=len(anomalies),
            anomalies=anomalies,
        )
        return ok(result)
    except Exception as e:
        return fail(e)


validator_step = Step(name="validate", executor=validator_executor, on_error=OnError.fail)