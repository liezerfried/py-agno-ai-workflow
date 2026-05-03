"""
Chainlit UI entry point: file upload, column selection, pipeline run, and results display.
This is the interactive web UI — run with `chainlit run app.py`.
Each agent runs in a background thread (run_in_executor) to keep the async event loop free,
and each has its own cl.Step so the user sees per-agent progress in real time.
"""
import asyncio
from functools import partial
from pathlib import Path

import chainlit as cl

from agno.db.sqlite import SqliteDb
from agno.tracing import setup_tracing
from agno.workflow import StepInput

from agents.audit_writer_agent import AuditResult
from agents.ingest_agent import IngestResult, detect_job_column, scan_headers
from agents.mapper_agent import MappingResult
from agents.validator_agent import ValidatorResult
from infrastructure.pipeline.session import PipelineSession
from infrastructure.pipeline.step_io import deserialize
from workflows.normalization_workflow import load_valid_categories
from workflows.orchestrator import PIPELINE_STEPS, STEP_DISPLAY_NAMES
from workflows.pipeline import PipelineError

# Create the tmp/ directory at import time so traces and output files always have
# a place to land regardless of the working directory the user starts Chainlit from.
Path("tmp").mkdir(exist_ok=True)

# batch_processing=True flushes traces asynchronously so the event loop is never
# blocked waiting for a SQLite write between agent steps.
setup_tracing(db=SqliteDb(db_file="tmp/traces.db"), batch_processing=True)


def _step_summary(name: str, content: str) -> str:
    """
    Convert a raw agent JSON payload into a short human-readable status line
    that Chainlit displays inside each cl.Step panel after the step completes.

    Each branch deserializes the agent-specific Pydantic model from the JSON string
    and extracts the metrics most relevant to that step. The function is only called
    after a successful output, so `content` is always valid JSON at this point.
    """
    if name == "IngestAgent":
        r = deserialize(content, IngestResult)
        return f"Found {len(r.raw_categories)} unique categories ({r.total_rows} total rows)"

    if name == "ValidatorAgent":
        r = deserialize(content, ValidatorResult)
        return f"{r.anomaly_count} anomalies flagged — {r.valid_count} already valid"

    if name == "MapperAgent":
        r = deserialize(content, MappingResult)
        auto = sum(1 for d in r.decisions if d.method in ("exact", "fuzzy"))
        llm  = sum(1 for d in r.decisions if d.method == "llm")
        rev  = sum(1 for d in r.decisions if d.needs_review)
        return f"{auto} auto-corrected — {llm} via LLM — {rev} to review queue"

    if name == "AuditWriter":
        r = deserialize(content, AuditResult)
        p = f"{r.precision:.2%}" if r.precision is not None else "N/A"
        return f"Corrected: {r.corrected_count} — Review queue: {r.review_queue_count} — Precision: {p}"

    return content


async def _run_pipeline_with_steps(file_path: str, target_column: str) -> AuditResult:
    """
    Run the four-step normalization pipeline, displaying each agent as its own cl.Step.

    Each executor is dispatched to a background thread via run_in_executor so the async
    event loop stays free between steps (allowing Chainlit to render UI updates).
    The cl.Step context manager must live entirely in this async function — never inside
    the thread — so the UI updates correctly after each step completes.

    Step order and executor bindings are defined in workflows/orchestrator.py.
    """
    session_state = PipelineSession(
        file_path=file_path,
        target_column=target_column,
        valid_categories=load_valid_categories(),
    ).to_dict()

    loop = asyncio.get_event_loop()
    previous_content: str | None = None

    for step in PIPELINE_STEPS:
        display_name = STEP_DISPLAY_NAMES[step.name]
        async with cl.Step(name=display_name) as cl_step:
            cl_step.output = "Running…"
            step_input = StepInput(previous_step_content=previous_content)

            output = await loop.run_in_executor(
                None, partial(step.executor, step_input, session_state)
            )

            if not output.success:
                cl_step.output = f"Failed: {output.content}"
                raise PipelineError(display_name, output.content or "unknown error")

            previous_content = output.content
            cl_step.output = _step_summary(display_name, previous_content)

    return AuditResult.model_validate_json(previous_content)


@cl.on_chat_start
async def start() -> None:
    """
    Entry point for every new Chainlit chat session.

    Flow:
      1. Prompt the user to upload an Excel file.
      2. Scan its column headers.
      3. Determine the target column automatically or ask the user to pick one.
      4. Run the four-agent pipeline.
      5. Display a summary table and a download link for the corrected file.
    """
    files = await cl.AskFileMessage(
        content="Upload an Excel file (.xlsx) with job categories to normalize.",
        accept={"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"]},
        max_size_mb=20,
        timeout=600,
    ).send()

    if files is None:
        await cl.Message("Session expired after 10 minutes. Start a new chat to try again.").send()
        return

    uploaded = files[0]

    scan = scan_headers(uploaded.path)

    if not scan.column_names:
        await cl.Message("No columns found. Please upload a valid Excel file.").send()
        return

    # --- Column selection: three paths depending on what the file looks like ---

    if len(scan.column_names) == 1:
        target_column = scan.column_names[0]
        await cl.Message(f"Single column detected: **`{target_column}`** — starting pipeline…").send()

    else:
        best_col, score = detect_job_column(scan.column_names)

        # 0.85 matches the pipeline's precision threshold — same bar for auto-detection
        # as for auto-correction, so the UI never silently picks the wrong column.
        if score >= 0.85:
            target_column = best_col
            await cl.Message(
                f"Auto-detected job category column: **`{target_column}`** — starting pipeline…"
            ).send()

        else:
            res = await cl.AskActionMessage(
                content="Select the column that contains job categories:",
                actions=[
                    cl.Action(name="col", payload={"value": col}, label=col)
                    for col in scan.column_names
                ],
            ).send()

            if res is None:
                await cl.Message("No column selected. Please restart.").send()
                return

            target_column = res.get("payload", {}).get("value")

    # --- Run the pipeline ---

    try:
        result: AuditResult = await _run_pipeline_with_steps(uploaded.path, target_column)
    except PipelineError as exc:
        await cl.Message(f"Pipeline stopped:\n```\n{exc}\n```").send()
        return

    # --- Display results ---

    precision_str = f"{result.precision:.2%}" if result.precision is not None else "N/A"

    await cl.Message(
        content=(
            f"Pipeline complete.\n\n"
            f"| Metric | Value |\n"
            f"|--------|-------|\n"
            f"| Corrected | {result.corrected_count} |\n"
            f"| Needs review | {result.review_queue_count} |\n"
            f"| Precision | {precision_str} |\n\n"
            "Download your corrected file:"
        ),
        elements=[
            cl.File(
                name="corrected.xlsx",
                path=result.output_path,
                display="inline",
            )
        ],
    ).send()


@cl.on_message
async def main(_message: cl.Message) -> None:
    await cl.Message("The pipeline has already completed. Start a new chat to process another file.").send()