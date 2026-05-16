"""
Checks each raw job category against the O*NET canonical title list to flag anomalies.
Called by the Workflow after IngestAgent; its output drives MapperAgent's workload.
"Validation" here means: is this raw string already an exact O*NET title, or does it need correction?
"""
import logging

# rapidfuzz measures how similar two strings are on a 0-100 scale.
# Used here to find the closest O*NET title even when the raw value does not match exactly.
from rapidfuzz import fuzz, process

# Pydantic is a data-validation library.
# Classes that extend BaseModel have their fields type-checked automatically at construction time.
from pydantic import BaseModel

# Agno Workflow primitives:
#   Step      — a named unit of work in the pipeline.
#   StepInput — carries the serialized output of the previous Step.
#   StepOutput — the serialized result this Step passes to the next one.
#   OnError   — controls what the Workflow does when a Step fails.
from agno.workflow import OnError, Step, StepInput, StepOutput

from agents.ingest_agent import IngestResult
from infrastructure.pipeline.contracts import CategoryValidation
from infrastructure.pipeline.session import PipelineSession
from infrastructure.pipeline.step_io import deserialize, fail, ok

logger = logging.getLogger(__name__)


class ValidatorResult(BaseModel):
    """
    The full output of the validation step: one CategoryValidation per unique raw category.

    MapperAgent receives this and uses 'anomalies' to decide which categories need correction.
    Categories in 'validations' but not in 'anomalies' are already valid O*NET titles
    and will be passed through unchanged by AuditWriter.

    O*NET (Occupational Information Network) is the US Department of Labor database
    that provides 923 canonical job titles used as ground truth in this pipeline.
    """
    validations: list[CategoryValidation]   # One entry per unique raw category found in the file.
    valid_count: int                        # How many raw categories were already exact O*NET titles.
    anomaly_count: int                      # How many raw categories need correction.
    anomalies: list[CategoryValidation]     # Subset of validations where is_valid=False.


def _validate_category(raw: str, valid_categories: list[str]) -> CategoryValidation:
    """
    Classify a single raw job title as valid or anomalous.

    "Valid" means the raw string is already an exact O*NET canonical title — no correction needed.
    "Anomalous" means it differs in some way (typo, language, abbreviation, etc.) and MapperAgent
    will attempt to find the correct canonical title.

    This function does NOT correct the title — it only reports whether a correction is needed
    and provides the closest match as a hint for the confidence-band routing in MapperAgent.
    """
    if raw in valid_categories:
        # Exact match — this raw value IS already a canonical O*NET title.
        return CategoryValidation(raw=raw, is_valid=True, closest_match=None, similarity_score=1.0)

    # Not an exact match — find the most similar O*NET title to use as a hint for MapperAgent.
    # fuzz.WRatio handles token reordering and partial matches better than simple ratio.
    match = process.extractOne(raw, valid_categories, scorer=fuzz.WRatio)
    if match is None:
        # No similarity at all — completely unrecognizable input.
        return CategoryValidation(raw=raw, is_valid=False, closest_match=None, similarity_score=0.0)

    closest, score, _ = match
    # Normalize score from 0-100 (rapidfuzz) to 0.0-1.0 for consistency with pipeline thresholds.
    return CategoryValidation(
        raw=raw,
        is_valid=False,
        closest_match=closest,
        similarity_score=round(score / 100.0, 4),
    )


def validator_executor(step_input: StepInput, session_state: dict) -> StepOutput:
    """
    Agno Step executor: validates every unique raw category extracted by IngestAgent.

    Pipeline order: IngestAgent -> ValidatorAgent (this step) -> MapperAgent -> AuditWriter
    """
    try:
        session = PipelineSession.from_dict(session_state)
        ingest_result = deserialize(step_input.previous_step_content, IngestResult)

        # Validate every unique raw category extracted from the uploaded file.
        validations = [_validate_category(raw, session.valid_categories) for raw in ingest_result.raw_categories]
        # Collect anomalies separately so MapperAgent only processes what needs correction.
        anomalies = [v for v in validations if not v.is_valid]

        result = ValidatorResult(
            validations=validations,
            valid_count=len(validations) - len(anomalies),
            anomaly_count=len(anomalies),
            anomalies=anomalies,
        )
        logger.info(
            "validate: total=%d valid=%d anomalies=%d anomaly_rate=%.2f",
            len(validations),
            result.valid_count,
            result.anomaly_count,
            result.anomaly_count / len(validations) if validations else 0.0,
        )
        return ok(result)
    except Exception as e:
        return fail(e)


# Register the executor as a named Agno Step.
# on_error=OnError.fail stops the entire Workflow if validation fails —
# running MapperAgent on unvalidated input would produce unreliable results.
validator_step = Step(
    name="validate",
    description="Classify each raw category as valid (exact O*NET match) or anomalous, attaching the closest match and similarity score for downstream routing.",
    executor=validator_executor,
    on_error=OnError.fail,
)