"""
Assembles the Agno Workflow and exposes it as a REST API via AgentOS.
Entry point for the HTTP API surface — run with `uvicorn agent_os:app`.
AgentOS wraps FastAPI internally; never instantiate FastAPI() directly in this project.
"""
from pathlib import Path

from agno.db.sqlite import SqliteDb

# AgentOS is Agno's application server. It wraps FastAPI and exposes your Workflows
# as REST endpoints automatically — no manual route definitions needed.
# Call agent_os.get_app() to get the ASGI app object that uvicorn (or any ASGI server) can serve.
from agno.os.app import AgentOS

# Agno Workflow primitives:
#   Steps    — a named group of Steps executed in sequence within a Workflow.
#   Workflow — the top-level container; holds one or more Steps groups and shared session state.
from agno.workflow import Steps, Workflow

from workflows.normalization_workflow import load_valid_categories
from workflows.orchestrator import PIPELINE_STEPS

# Create the tmp/ directory if it doesn't exist yet (used for the SQLite DB and output files).
Path("tmp").mkdir(exist_ok=True)


# Build the Workflow once at startup — AgentOS needs it registered before serving requests.
# file_path and target_column start as empty strings because their real values are
# injected at run time via session_state in each API request (one per uploaded file).
_workflow = Workflow(
    name="Job Category Normalization",
    description="Maps free-text job categories to canonical O*NET occupation titles.",
    steps=[
        # Steps groups all four agents into a single named sequence.
        # The output of each Step is automatically passed to the next as StepInput.
        # Step order is defined in workflows/orchestrator.py — edit there, not here.
        Steps(name="normalization", steps=PIPELINE_STEPS)
    ],
    session_state={
        "file_path": "",          # Overridden per request with the uploaded file's path.
        "target_column": "",      # Overridden per request with the user-selected column name.
        "valid_categories": load_valid_categories(),  # Loaded once; shared across all requests.
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