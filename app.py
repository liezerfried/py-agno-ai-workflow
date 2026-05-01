import asyncio
from functools import partial
from pathlib import Path

import chainlit as cl

from agno.db.sqlite import SqliteDb
from agno.tracing import setup_tracing

from agents.audit_writer_agent import AuditResult
from agents.ingest_agent import scan_headers
from workflows.normalization_workflow import create_workflow
from workflows.pipeline import PipelineError

# Tracing — all agent and workflow runs are captured to tmp/traces.db.
# View at https://app.agno.com after connecting with AGNO_API_KEY,
# or query the SQLite file directly.
Path("tmp").mkdir(exist_ok=True)
setup_tracing(db=SqliteDb(db_file="tmp/traces.db"), batch_processing=True)


def _run_workflow(file_path: str, target_column: str) -> AuditResult:
    workflow = create_workflow(file_path, target_column)
    run_output = workflow.run()
    step_results = run_output.step_results
    if not step_results:
        raise PipelineError("unknown", "Workflow produced no step results")
    last = step_results[-1]
    if not last.success:
        raise PipelineError("pipeline", last.content)
    return AuditResult.model_validate_json(last.content)


@cl.on_chat_start
async def start() -> None:
    files = None
    while files is None:
        files = await cl.AskFileMessage(
            content="Upload an Excel file (.xlsx) with job categories to normalize.",
            accept={"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"]},
            max_size_mb=20,
        ).send()

    uploaded = files[0]
    scan = scan_headers(uploaded.path)

    if not scan.column_names:
        await cl.Message("No columns found in the file. Please upload a valid Excel file.").send()
        return

    columns_list = "\n".join(f"  {i + 1}. {col}" for i, col in enumerate(scan.column_names))
    res = await cl.AskUserMessage(
        content=f"Columns detected:\n```\n{columns_list}\n```\nType the **column name** that contains the job categories.",
        timeout=120,
    ).send()

    if res is None:
        await cl.Message("No column selected. Please restart the chat.").send()
        return

    target_column = res["output"].strip()
    if target_column not in scan.column_names:
        await cl.Message(
            f'Column `{target_column}` not found. Available: {", ".join(scan.column_names)}\nPlease restart and try again.'
        ).send()
        return

    cl.user_session.set("file_path", uploaded.path)
    cl.user_session.set("target_column", target_column)

    await cl.Message(
        f'Ready. Column **`{target_column}`** selected.\nType **run** to start the normalization pipeline.'
    ).send()


@cl.on_message
async def main(message: cl.Message) -> None:
    if message.content.strip().lower() != "run":
        await cl.Message('Type **run** to start the pipeline.').send()
        return

    file_path: str | None = cl.user_session.get("file_path")
    target_column: str | None = cl.user_session.get("target_column")

    if not file_path or not target_column:
        await cl.Message("No file loaded. Please restart the chat and upload a file.").send()
        return

    async with cl.Step(name="Normalization Pipeline") as step:
        step.output = "Running pipeline…"
        try:
            result: AuditResult = await asyncio.get_event_loop().run_in_executor(
                None,
                partial(_run_workflow, file_path, target_column),
            )
        except PipelineError as exc:
            step.output = f"Failed at {exc.stage}: {exc.message}"
            await cl.Message(f"Pipeline stopped:\n```\n{exc}\n```").send()
            return

        precision_str = (
            f"{result.precision:.2%}" if result.precision is not None else "N/A"
        )
        step.output = (
            f"Corrected: **{result.corrected_count}** — "
            f"Review queue: **{result.review_queue_count}** — "
            f"Precision: **{precision_str}**"
        )

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