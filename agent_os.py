import csv
from pathlib import Path

from agno.db.sqlite import SqliteDb
from agno.os.app import AgentOS
from agno.workflow import Step, Steps, Workflow

from agents.audit_writer_agent import audit_step
from agents.ingest_agent import ingest_step
from agents.mapper_agent import mapper_step
from agents.validator_agent import validator_step

Path("tmp").mkdir(exist_ok=True)

_VALID_CATEGORIES_PATH = Path(__file__).parent / "data" / "valid_categories.csv"


def _load_valid_categories() -> list[str]:
    with open(_VALID_CATEGORIES_PATH, newline="", encoding="utf-8") as f:
        return [row["category"] for row in csv.DictReader(f)]


# AgentOS needs a Workflow instance at startup.
# file_path and target_column are injected at run time via session_state in the API request.
_workflow = Workflow(
    name="Job Category Normalization",
    description="Maps free-text job categories to canonical O*NET occupation titles.",
    steps=[
        Steps(
            name="normalization",
            steps=[ingest_step, validator_step, mapper_step, audit_step],
        )
    ],
    session_state={
        "file_path": "",
        "target_column": "",
        "valid_categories": _load_valid_categories(),
    },
)

_db = SqliteDb(db_file="tmp/agent_os.db")

agent_os = AgentOS(
    name="Job Category Normalizer",
    description="AI pipeline that maps free-text job categories to canonical O*NET occupation titles.",
    workflows=[_workflow],
    db=_db,
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve("agent_os:app", host="localhost", port=8000, reload=True)
