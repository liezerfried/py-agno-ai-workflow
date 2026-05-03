"""
Assembles the Agno Workflow and exposes it as a REST API via AgentOS.
Entry point for the HTTP API surface — run with `uvicorn agent_os:app`.
AgentOS wraps FastAPI internally; never instantiate FastAPI() directly in this project.
"""
import csv
from pathlib import Path

from agno.db.sqlite import SqliteDb

# AgentOS is Agno's application server. It wraps FastAPI and exposes your Workflows
# as REST endpoints automatically — no manual route definitions needed.
# Call agent_os.get_app() to get the ASGI app object that uvicorn (or any ASGI server) can serve.
from agno.os.app import AgentOS

# Agno Workflow primitives:
#   Step     — a single named executor function (e.g. ingest_step, validator_step).
#   Steps    — a named group of Steps executed in sequence within a Workflow.
#   Workflow — the top-level container; holds one or more Steps groups and shared session state.
# Pipeline order: IngestAgent → ValidatorAgent → MapperAgent → AuditWriter
from agno.workflow import Steps, Workflow

from agents.audit_writer_agent import audit_step
from agents.ingest_agent import ingest_step
from agents.mapper_agent import mapper_step
from agents.validator_agent import validator_step

# Create the tmp/ directory if it doesn't exist yet (used for the SQLite DB and output files).
Path("tmp").mkdir(exist_ok=True)

# Anchored to __file__ so the path is correct regardless of where uvicorn is launched from.
_VALID_CATEGORIES_PATH = Path(__file__).parent / "data" / "valid_categories.csv"


def _load_valid_categories() -> list[str]:
    """
    Read the O*NET canonical title list from disk and return it as a plain list of strings.

    O*NET (Occupational Information Network) is the US Department of Labor database
    that provides 923 canonical job titles used as ground truth in this pipeline.
    The CSV is generated from the source O*NET spreadsheet by scripts/build_valid_categories.py.

    Returns:
        A list of 923 canonical job title strings, one per row in valid_categories.csv.
    """
    with open(_VALID_CATEGORIES_PATH, newline="", encoding="utf-8") as f:
        return [row["category"] for row in csv.DictReader(f)]


# Build the Workflow once at startup — AgentOS needs it registered before serving requests.
# file_path and target_column start as empty strings because their real values are
# injected at run time via session_state in each API request (one per uploaded file).
_workflow = Workflow(
    name="Job Category Normalization",
    description="Maps free-text job categories to canonical O*NET occupation titles.",
    steps=[
        # Steps groups all four agents into a single named sequence.
        # The output of each Step is automatically passed to the next as StepInput.
        Steps(
            name="normalization",
            steps=[ingest_step, validator_step, mapper_step, audit_step],
        )
    ],
    session_state={
        "file_path": "",          # Overridden per request with the uploaded file's path.
        "target_column": "",      # Overridden per request with the user-selected column name.
        "valid_categories": _load_valid_categories(),  # Loaded once; shared across all requests.
    },
)

# SqliteDb persists workflow run history and session state between requests.
_db = SqliteDb(db_file="tmp/agent_os.db")

# AgentOS registers the workflow and wires up the REST API.
# It does NOT start a server here — that happens via agent_os.serve() or an external uvicorn call.
agent_os = AgentOS(
    name="Job Category Normalizer",
    description="AI pipeline that maps free-text job categories to canonical O*NET occupation titles.",
    workflows=[_workflow],
    db=_db,
)

# get_app() returns the underlying FastAPI ASGI application.
# Exposing it as `app` lets any ASGI server pick it up by name:
#   uvicorn agent_os:app --host localhost --port 8000
app = agent_os.get_app()

if __name__ == "__main__":
    # Convenience shortcut for local development: `python agent_os.py` starts the server
    # with hot-reload so code changes take effect without a manual restart.
    # In production, invoke uvicorn directly instead — it gives finer control over
    # workers, timeouts, and TLS without going through this __main__ block.
    agent_os.serve("agent_os:app", host="localhost", port=8000, reload=True)
