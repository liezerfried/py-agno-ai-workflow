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

from agents.audit_writer_agent import AuditResult, audit_executor
from agents.ingest_agent import IngestResult, detect_job_column, ingest_executor, scan_headers
from agents.mapper_agent import MappingResult, mapper_executor
from agents.validator_agent import ValidatorResult, validator_executor
from infrastructure.pipeline.session import PipelineSession
from infrastructure.pipeline.step_io import deserialize
from workflows.normalization_workflow import load_valid_categories
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
        # Show how many distinct category values were extracted from the target column
        # and the total row count so the user can sanity-check the file was read correctly.
        r = deserialize(content, IngestResult)
        return f"Found {len(r.raw_categories)} unique categories ({r.total_rows} total rows)"

    if name == "ValidatorAgent":
        # Show the split between rows that are already valid O*NET titles (no work needed)
        # and rows flagged as anomalies that the MapperAgent will attempt to correct.
        r = deserialize(content, ValidatorResult)
        return f"{r.anomaly_count} anomalies flagged — {r.valid_count} already valid"

    if name == "MapperAgent":
        # Break down corrections by resolution method so the user can see how many
        # were cheap (exact/fuzzy match) vs. expensive (LLM call) vs. escalated.
        r = deserialize(content, MappingResult)
        auto = sum(1 for d in r.decisions if d.method in ("exact", "fuzzy"))
        llm  = sum(1 for d in r.decisions if d.method == "llm")
        rev  = sum(1 for d in r.decisions if d.needs_review)
        return f"{auto} auto-corrected — {llm} via LLM — {rev} to review queue"

    if name == "AuditWriter":
        # Surface the precision metric here so the user sees it before the final
        # summary message — useful when the pipeline is slow on large files.
        r = deserialize(content, AuditResult)
        p = f"{r.precision:.2%}" if r.precision is not None else "N/A"
        return f"Corrected: {r.corrected_count} — Review queue: {r.review_queue_count} — Precision: {p}"

    # Fallback: unknown agent name — return raw content rather than crashing.
    return content


async def _run_pipeline_with_steps(file_path: str, target_column: str) -> AuditResult:
    """
    Run the four-step normalization pipeline, displaying each agent as its own cl.Step.

    Each executor is dispatched to a background thread via run_in_executor so the async
    event loop stays free between steps (allowing Chainlit to render UI updates).
    The cl.Step context manager must live entirely in this async function — never inside
    the thread — so the UI updates correctly after each step completes.
    """
    # Build the shared session dictionary that every agent reads from.
    # PipelineSession holds the file path, target column, and the full set of valid
    # O*NET categories so agents don't need to reload the CSV themselves.
    session_state = PipelineSession(
        file_path=file_path,
        target_column=target_column,
        valid_categories=load_valid_categories(),
    ).to_dict()

    # Ordered list of (display name, executor function) pairs.
    # The order here is the execution order — do not rearrange.
    executors = [
        ("IngestAgent",    ingest_executor),
        ("ValidatorAgent", validator_executor),
        ("MapperAgent",    mapper_executor),
        ("AuditWriter",    audit_executor),
    ]

    loop = asyncio.get_event_loop()

    # Each agent's serialized JSON output becomes the next agent's StepInput.
    # None on the first step signals IngestAgent to bootstrap from session_state
    # rather than trying to parse a previous step's output.
    previous_content: str | None = None

    for name, executor_fn in executors:
        # cl.Step opens a collapsible panel in the Chainlit UI for this agent.
        # Setting step.output before awaiting the executor shows "Running…" immediately,
        # giving visual feedback while the thread is working.
        async with cl.Step(name=name) as step:
            step.output = "Running…"
            step_input = StepInput(previous_step_content=previous_content)

            # partial builds a zero-arg callable — run_in_executor cannot pass
            # arguments to the callable itself, so we bind them here.
            output = await loop.run_in_executor(
                None, partial(executor_fn, step_input, session_state)
            )

            if not output.success:
                # Update the step panel with the failure reason before raising,
                # so the user sees which agent failed and why.
                step.output = f"Failed: {output.content}"
                raise PipelineError(name, output.content or "unknown error")

            previous_content = output.content
            # Replace "Running…" with a human-readable summary of what this step produced.
            step.output = _step_summary(name, previous_content)

    # At this point previous_content holds the AuditWriter's JSON output.
    # Deserialize it once here so the caller gets a typed result, not a raw string.
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
    # AskFileMessage blocks until the user uploads a file or the timeout expires.
    # timeout=600 gives users 10 minutes, which is generous for large files.
    files = await cl.AskFileMessage(
        content="Upload an Excel file (.xlsx) with job categories to normalize.",
        accept={"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"]},
        max_size_mb=20,
        timeout=600,
    ).send()

    # A None response means the 10-minute timeout elapsed with no upload.
    if files is None:
        await cl.Message("Session expired after 10 minutes. Start a new chat to try again.").send()
        return

    uploaded = files[0]

    # scan_headers reads only the header row — it does not load the full file into memory.
    scan = scan_headers(uploaded.path)

    if not scan.column_names:
        await cl.Message("No columns found. Please upload a valid Excel file.").send()
        return

    # --- Column selection: three paths depending on what the file looks like ---

    if len(scan.column_names) == 1:
        # Single-column file: no ambiguity — skip the detection step entirely.
        target_column = scan.column_names[0]
        await cl.Message(f"Single column detected: **`{target_column}`** — starting pipeline…").send()

    else:
        # Multi-column file: score every column header against known job-title patterns.
        best_col, score = detect_job_column(scan.column_names)

        # 0.85 matches the pipeline's precision threshold — same bar for auto-detection
        # as for auto-correction, so the UI never silently picks the wrong column.
        if score >= 0.85:
            target_column = best_col
            await cl.Message(
                f"Auto-detected job category column: **`{target_column}`** — starting pipeline…"
            ).send()

        else:
            # Score too low to be confident — present each column as a clickable button
            # and let the user decide. AskActionMessage blocks until a button is clicked.
            res = await cl.AskActionMessage(
                content="Select the column that contains job categories:",
                actions=[
                    cl.Action(name="col", payload={"value": col}, label=col)
                    for col in scan.column_names
                ],
            ).send()

            # None means the user dismissed the prompt without clicking a button.
            if res is None:
                await cl.Message("No column selected. Please restart.").send()
                return

            # The button payload carries the original column name as a string.
            target_column = res.get("payload", {}).get("value")

    # --- Run the pipeline ---

    try:
        result: AuditResult = await _run_pipeline_with_steps(uploaded.path, target_column)
    except PipelineError as exc:
        # PipelineError is raised by any agent that returns success=False.
        # The step panel already shows the per-agent failure detail; this message
        # provides a top-level signal that the pipeline did not complete.
        await cl.Message(f"Pipeline stopped:\n```\n{exc}\n```").send()
        return

    # --- Display results ---

    # precision can be None when there are no ground-truth labels to evaluate against
    # (e.g. the user uploaded a file with no manually verified corrections).
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
        # cl.File attaches the corrected Excel as an inline download link in the chat.
        elements=[
            cl.File(
                name="corrected.xlsx",
                path=result.output_path,
                display="inline",
            )
        ],
    ).send()


@cl.on_message
# Chainlit keeps the chat session alive after on_chat_start completes, so any
# follow-up message the user sends lands here. The pipeline is one-shot per
# session — redirect rather than re-running or failing silently.
async def main(_message: cl.Message) -> None:
    await cl.Message("The pipeline has already completed. Start a new chat to process another file.").send()