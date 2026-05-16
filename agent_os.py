"""
Assembles the Agno Workflow and exposes it as a REST API via AgentOS.
Entry point for the HTTP API surface — run with `uvicorn agent_os:app`.
AgentOS wraps FastAPI internally; never instantiate FastAPI() directly in this project.
"""
import asyncio
import uuid as uuid_module
from datetime import datetime
from functools import partial
from pathlib import Path

from fastapi import File, Form, HTTPException, UploadFile

from agno.db.sqlite import SqliteDb
from agno.tracing import setup_tracing

# AgentOS is Agno's application server. It wraps FastAPI and exposes your Workflows
# as REST endpoints automatically — no manual route definitions needed.
# Call agent_os.get_app() to get the ASGI app object that uvicorn (or any ASGI server) can serve.
from agno.os.app import AgentOS

# Agno Workflow primitives:
#   Steps    — a named group of Steps executed in sequence within a Workflow.
#   Workflow — the top-level container; holds one or more Steps groups and shared session state.
from agno.workflow import Steps, Workflow

from agents.audit_writer_agent import AuditResult
from agents.ingest_agent import detect_job_column, scan_headers
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

# Single SQLite DB shared by AgentOS (sessions + run history) and the OTEL tracer
# (per-agent spans). Unifying both means runs triggered via REST appear in
# os.agno.com with full step-level detail. The same path is used by app.py and
# scripts/inspect_last_run.py so every entry point reads/writes the same store.
_db = SqliteDb(db_file="tmp/agentos.db")

# batch_processing=True flushes spans asynchronously so REST request handling is
# never blocked by a SQLite write between agent steps.
setup_tracing(db=_db, batch_processing=True)

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


# Custom upload endpoint layered on top of the AgentOS FastAPI app. Why a
# bespoke route instead of the built-in /workflows/{id}/runs: that endpoint
# only accepts a string `message`, with no native way to attach an .xlsx
# upload or override per-request session_state. This route gives REST clients
# (curl, Postman, a custom frontend) the same capability the Chainlit UI has.
@app.post("/normalize/upload", tags=["normalize"])
async def normalize_upload(
    file: UploadFile = File(..., description="Excel workbook (.xlsx) with a job-categories column"),
    target_column: str | None = Form(
        None,
        description="Name of the target column. Auto-detected when omitted (score threshold 0.85).",
    ),
):
    """
    Accept an Excel file upload and run the normalization workflow end-to-end.

    REST counterpart of the Chainlit UI in app.py: the same four agents in
    the same order, but invoked through Agno's `Workflow.run()` lifecycle so
    the run appears in `os.agno.com` with full step-level traces and
    structured spans.

    Returns AuditResult JSON: output_path, total_rows, corrected_count,
    review_queue_count, hallucination_count, precision.
    """
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="only .xlsx files are accepted")

    # Persist the upload to a known location so the executors (which read
    # file_path off session_state) can open it from disk. Each upload gets a
    # UUID prefix so concurrent requests never clobber each other.
    uploads_dir = Path("tmp/uploads")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    saved_path = uploads_dir / f"{uuid_module.uuid4()}_{file.filename}"
    saved_path.write_bytes(await file.read())

    # Auto-detect the job-categories column when the caller didn't specify
    # one. Mirrors app.py's behavior so REST and Chainlit accept the same
    # files without extra ceremony from the caller.
    resolved_column = target_column
    if not resolved_column:
        scan = scan_headers(str(saved_path))
        col, conf = detect_job_column(scan.column_names)
        if conf < 0.85:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Could not auto-detect job column "
                    f"(best={col!r}, confidence={conf:.2f}). "
                    f"Set target_column explicitly. "
                    f"Available columns: {scan.column_names}"
                ),
            )
        resolved_column = col

    # Workflow.run is synchronous and CPU/IO-bound (LLM calls). Run it on a
    # worker thread so the FastAPI event loop stays free for other requests.
    # The per-request session_state is merged with the workflow defaults,
    # which already include valid_categories — we only override the two
    # request-specific keys here.
    #
    # Explicit session_id ties this workflow run to a named session in the
    # AgentOS UI. The same id is also injected into session_state under
    # `workflow_session_id` so the inner mapper/translator executors can
    # forward it to each agent.run() and every inner trace attaches to the
    # same session — otherwise each agent creates its own orphan session.
    request_session_id = str(uuid_module.uuid4())
    loop = asyncio.get_event_loop()
    workflow_result = await loop.run_in_executor(
        None,
        partial(
            _workflow.run,
            input="",
            session_id=request_session_id,
            session_state={
                "file_path": str(saved_path),
                "target_column": resolved_column,
                "workflow_session_id": request_session_id,
            },
        ),
    )

    # Give the session a human-readable name so the UI's Sessions tab does
    # not just list "Untitled Session". The original filename (before the
    # UUID prefix we added on disk) is the most useful identifier for the
    # person reviewing past runs.
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    session_label = f"{file.filename} @ {timestamp}"
    try:
        _workflow.set_session_name(session_id=request_session_id, session_name=session_label)
    except Exception as exc:  # noqa: BLE001
        # Name is cosmetic UI metadata — failure here must not poison the
        # response. Log and continue with whatever default name Agno set.
        import logging
        logging.getLogger(__name__).warning(
            "Failed to set session name for %s: %s", request_session_id, exc
        )

    # The last step's content is the AuditWriter's JSON output, by contract
    # of the pipeline ordering in workflows/orchestrator.PIPELINE_STEPS.
    audit = AuditResult.model_validate_json(workflow_result.content)
    return audit.model_dump()


if __name__ == "__main__":
    # Convenience shortcut for local development: `python agent_os.py` starts the server
    # with hot-reload so code changes take effect without a manual restart.
    # In production, invoke uvicorn directly instead — it gives finer control over
    # workers, timeouts, and TLS without going through this __main__ block.
    agent_os.serve("agent_os:app", host="localhost", port=8000, reload=True)