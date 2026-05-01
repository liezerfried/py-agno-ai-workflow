import csv
from pathlib import Path

from agno.workflow import Step, Steps, Workflow

from agents.audit_writer_agent import audit_step
from agents.ingest_agent import ingest_step
from agents.mapper_agent import mapper_step
from agents.validator_agent import validator_step
from infrastructure.pipeline.session import PipelineSession

_VALID_CATEGORIES_PATH = Path(__file__).parent.parent / "data" / "valid_categories.csv"


def _load_valid_categories() -> list[str]:
    with open(_VALID_CATEGORIES_PATH, newline="", encoding="utf-8") as f:
        return [row["category"] for row in csv.DictReader(f)]


def create_workflow(file_path: str, target_column: str) -> Workflow:
    valid_categories = _load_valid_categories()

    normalization_sequence = Steps(
        name="normalization",
        steps=[ingest_step, validator_step, mapper_step, audit_step],
    )

    return Workflow(
        name="Job Category Normalization",
        steps=[normalization_sequence],
        session_state=PipelineSession(
            file_path=file_path,
            target_column=target_column,
            valid_categories=valid_categories,
        ).to_dict(),
    )