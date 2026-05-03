"""
Single source of truth for the pipeline step sequence.
Both agent_os.py (REST API) and app.py (Chainlit UI) import from here so that
adding, removing, or reordering a step requires one change in one place.
"""
from agno.workflow import Step

from agents.audit_writer_agent import audit_step
from agents.ingest_agent import ingest_step
from agents.mapper_agent import mapper_step
from agents.validator_agent import validator_step

PIPELINE_STEPS: list[Step] = [ingest_step, validator_step, mapper_step, audit_step]

# Maps each Step.name to the display label shown in Chainlit's cl.Step panels
# and used by _step_summary() to dispatch to the right deserializer.
STEP_DISPLAY_NAMES: dict[str, str] = {
    "ingest":   "IngestAgent",
    "validate": "ValidatorAgent",
    "map":      "MapperAgent",
    "audit":    "AuditWriter",
}