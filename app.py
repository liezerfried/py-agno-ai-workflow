"""
Chainlit UI entry point: file upload, column selection, pipeline run, and results display.
This is the interactive web UI — run with `chainlit run app.py`.
Each agent runs in a background thread (run_in_executor) to keep the async event loop free,
and each has its own cl.Step so the user sees per-agent progress in real time.
"""
import asyncio
import contextvars
import time
from functools import partial
from pathlib import Path

import chainlit as cl

from agno.db.sqlite import SqliteDb
from agno.tracing import setup_tracing
from agno.workflow import StepInput

from agents.audit_writer_agent import AuditResult
from agents.ingest_agent import IngestResult, detect_job_column, scan_headers
from agents.mapper_agent import MappingResult, set_progress_callback
from agents.validator_agent import ValidatorResult
from infrastructure.pipeline.metrics_store import get_recent_runs
from infrastructure.pipeline.session import PipelineSession
from infrastructure.pipeline.step_io import deserialize
from workflows.normalization_workflow import load_valid_categories
from workflows.orchestrator import PIPELINE_STEPS, STEP_DISPLAY_NAMES
from workflows.pipeline import PipelineError

# Create the tmp/ directory at import time so traces and output files always have
# a place to land regardless of the working directory the user starts Chainlit from.
Path("tmp").mkdir(exist_ok=True)

# batch_processing=True flushes traces asynchronously so the event loop is never
# blocked waiting for a SQLite write between agent steps. The DB path is shared
# with agent_os.py and scripts/inspect_last_run.py so every entry point
# (Chainlit UI, REST API, inspection CLI) reads from the same SQLite file.
setup_tracing(db=SqliteDb(db_file="tmp/agentos.db"), batch_processing=True)


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
    Run the four-step normalization pipeline.

    Two UI surfaces are kept in sync:
      - A live `cl.Message` rendered just above the mapper step that updates
        in place as anomalies are processed (e.g. "MapperAgent — 12/98 mapped").
        Chainlit's cl.Step header does not refresh mid-flight, so the live
        counter has to live in a Message we explicitly call .update() on.
      - cl.Step: per-stage panel with a structured summary the user can expand
        after the pipeline finishes (e.g. "5 auto-corrected — 75 via LLM").

    The mapper executor is dispatched to a background thread via run_in_executor
    so the async event loop stays free for Chainlit to render UI updates while
    the LLM calls are in flight.

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

        # Mapper is the only stage that emits per-anomaly progress; for the
        # other (sub-second) stages we don't bother creating a progress message.
        progress_msg: cl.Message | None = None
        if step.name == "map":
            progress_msg = cl.Message(content=f"**{display_name}** — starting…")
            await progress_msg.send()
            set_progress_callback(
                _make_message_progress_callback(progress_msg, display_name, loop)
            )

        async with cl.Step(name=display_name) as cl_step:
            cl_step.output = "Running…"
            step_input = StepInput(previous_step_content=previous_content)

            try:
                output = await loop.run_in_executor(
                    None, partial(step.executor, step_input, session_state)
                )
            finally:
                if progress_msg is not None:
                    set_progress_callback(None)

            if not output.success:
                cl_step.output = f"Failed: {output.content}"
                if progress_msg is not None:
                    # Keep the failure visible — replacing this with a remove()
                    # would erase the only on-screen evidence of the stage that
                    # broke the pipeline.
                    progress_msg.content = f"**{display_name}** — failed"
                    await progress_msg.update()
                raise PipelineError(display_name, output.content or "unknown error")

            previous_content = output.content
            cl_step.output = _step_summary(display_name, previous_content)

        # Once the cl.Step has closed it carries the canonical "Used X" header
        # plus the expandable summary, so the live progress message is now
        # redundant — remove it to keep the chat history clean.
        if progress_msg is not None:
            await progress_msg.remove()

    return AuditResult.model_validate_json(previous_content)


def _make_message_progress_callback(
    progress_msg: cl.Message,
    display_name: str,
    loop: asyncio.AbstractEventLoop,
):
    """
    Build a thread-safe progress callback that updates a cl.Message in place
    as MapperAgent processes anomalies.

    Why a cl.Message and not cl.Step.update() or cl.TaskList: cl.Step does
    not refresh its visible header while the `async with` is open (docs only
    show step.update() being called *after* the step closes). cl.TaskList
    renders next to the chat as a side panel and is easy to miss visually.
    cl.Message updates inline in the same chat flow the user is already
    looking at, and cl.Message.update() is the same mechanism Chainlit uses
    for token streaming — a battle-tested live-update path.

    Why we capture contextvars: Chainlit identifies the active session via a
    ContextVar set when @cl.on_chat_start is invoked. asyncio.run_coroutine_threadsafe
    does NOT propagate that ContextVar to the spawned Task, so progress_msg.update()
    from a naked coroutine cannot find the session and the UI never refreshes
    even though the coroutine itself runs without error. Capturing the current
    context here and using ctx.run() to spawn the Task restores the binding.

    Throttling: the callback fires once per anomaly (≈ 50–100 times in a real
    run). We only push to the UI every 5th anomaly plus the final one — the
    user gets fluid feedback without the websocket being flooded.

    ETA: computed from the elapsed time since the first non-zero callback and
    the average completion rate. The estimate stabilises within a few updates
    once the parallel workers reach steady state.
    """
    ctx = contextvars.copy_context()
    # Mutable single-element list so the closure can record the start time
    # the first time real progress is reported, without using `nonlocal`.
    started_at: list[float | None] = [None]

    def _cb(processed: int, total: int) -> None:
        # Only emit on the first call, every 5th anomaly, and the final one.
        # Anything more granular floods the websocket without measurable UX gain.
        is_terminal = total == 0 or processed == total
        if not is_terminal and processed != 0 and processed % 5 != 0:
            return

        # Anchor the timer the moment work actually begins (processed == 1+),
        # not at processed == 0 — otherwise the first ETA estimate counts the
        # idle time before any anomaly completed and reads artificially high.
        if started_at[0] is None and processed > 0:
            started_at[0] = time.perf_counter()

        if total == 0:
            content = f"**{display_name}** — no anomalies to map"
        elif processed == 0 or started_at[0] is None:
            content = f"**{display_name}** — starting…"
        elif processed >= total:
            content = f"**{display_name}** — {processed}/{total} mapped"
        else:
            elapsed = time.perf_counter() - started_at[0]
            avg = elapsed / processed
            eta_seconds = int(avg * (total - processed))
            mins, secs = divmod(eta_seconds, 60)
            eta_str = f"{mins}:{secs:02d}" if mins else f"{secs}s"
            pct = round(processed / total * 100)
            content = (
                f"**{display_name}** — {processed}/{total} mapped "
                f"({pct}%) • ~{eta_str} remaining"
            )

        async def _push() -> None:
            progress_msg.content = content
            await progress_msg.update()

        def _schedule_in_ctx() -> None:
            # ensure_future creates the Task within whatever context is active
            # at call time. By calling it through ctx.run(), the Task inherits
            # the chainlit session ContextVar from the original coroutine.
            ctx.run(lambda: asyncio.ensure_future(_push()))

        # call_soon_threadsafe hops onto the chainlit event loop; the wrapper
        # then schedules the coroutine within the captured context.
        loop.call_soon_threadsafe(_schedule_in_ctx)

    return _cb


def _render_history() -> str:
    """Build a markdown table of recent pipeline runs for the history view."""
    runs = get_recent_runs(limit=20)
    if not runs:
        return "No previous runs — process your first file to see the history."

    lines = [
        "| Date | File | Rows | Corrected | Review | Precision |",
        "|------|------|------|-----------|--------|-----------|",
    ]
    for r in runs:
        timestamp = r["timestamp"][:16].replace("T", " ")  # "2026-05-05 14:32"
        precision = f"{r['precision']:.1%}" if r["precision"] is not None else "N/A"
        lines.append(
            f"| {timestamp} | {r['filename']} | {r['total_rows']} "
            f"| {r['corrected']} | {r['review_queue']} | {precision} |"
        )
    return "\n".join(lines)


@cl.on_chat_start
async def start() -> None:
    """
    Entry point for every new Chainlit chat session.

    Flow:
      1. Ask the user whether to process a new file or view run history.
      2. History path: render the pipeline_runs table and end the session.
      3. Process path: prompt for file upload, detect column, run pipeline, show results.
    """
    action = await cl.AskActionMessage(
        content="What would you like to do?",
        actions=[
            cl.Action(name="process", payload={"value": "process"}, label="Process a new file"),
            cl.Action(name="history", payload={"value": "history"}, label="View run history"),
        ],
    ).send()

    if action is None or action.get("payload", {}).get("value") == "history":
        await cl.Message(content=_render_history()).send()
        return

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