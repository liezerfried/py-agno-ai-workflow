import asyncio
from functools import partial

import chainlit as cl

from agno.workflow import StepInput

from agents.audit_writer_agent import AuditResult, audit_executor
from agents.ingest_agent import IngestResult, ingest_executor, scan_headers
from agents.mapper_agent import MappingResult, mapper_executor
from agents.validator_agent import ValidatorResult, validator_executor
from workflows.normalization_workflow import _load_valid_categories


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

    valid_categories, valid_categories_set = _load_valid_categories()
    session_state: dict = {
        "file_path": file_path,
        "target_column": target_column,
        "valid_categories": valid_categories,
        "valid_categories_set": valid_categories_set,
    }

    # ── Step 1: Ingest ────────────────────────────────────────────────────────
    async with cl.Step(name="IngestAgent") as step:
        step_input = StepInput()
        ingest_out = await asyncio.get_event_loop().run_in_executor(
            None, partial(ingest_executor, step_input, session_state)
        )
        if not ingest_out.success:
            step.output = f"Failed: {ingest_out.content}"
            await cl.Message(f"Pipeline stopped at IngestAgent:\n```\n{ingest_out.content}\n```").send()
            return

        ingest_result = IngestResult.model_validate_json(ingest_out.content)
        step.output = (
            f"Read **{ingest_result.total_rows}** rows — "
            f"found **{len(ingest_result.raw_categories)}** unique categories."
        )

    # ── Step 2: Validate ──────────────────────────────────────────────────────
    async with cl.Step(name="ValidatorAgent") as step:
        step_input = StepInput(previous_step_content=ingest_out.content)
        validator_out = await asyncio.get_event_loop().run_in_executor(
            None, partial(validator_executor, step_input, session_state)
        )
        if not validator_out.success:
            step.output = f"Failed: {validator_out.content}"
            await cl.Message(f"Pipeline stopped at ValidatorAgent:\n```\n{validator_out.content}\n```").send()
            return

        validator_result = ValidatorResult.model_validate_json(validator_out.content)
        step.output = (
            f"**{validator_result.valid_count}** already valid — "
            f"**{validator_result.anomaly_count}** anomalies to map."
        )

    # ── Step 3: Map ───────────────────────────────────────────────────────────
    async with cl.Step(name="MapperAgent") as step:
        step.output = f"Processing {validator_result.anomaly_count} anomalies (rapidfuzz + LLM)..."
        step_input = StepInput(previous_step_content=validator_out.content)
        mapper_out = await asyncio.get_event_loop().run_in_executor(
            None, partial(mapper_executor, step_input, session_state)
        )
        if not mapper_out.success:
            step.output = f"Failed: {mapper_out.content}"
            await cl.Message(f"Pipeline stopped at MapperAgent:\n```\n{mapper_out.content}\n```").send()
            return

        mapper_result = MappingResult.model_validate_json(mapper_out.content)
        step.output = (
            f"Auto-corrected: **{mapper_result.auto_corrected_count}** — "
            f"LLM-evaluated: **{mapper_result.llm_evaluated_count}** — "
            f"Needs review: **{mapper_result.needs_review_count}**"
        )

    # ── Step 4: Audit & write Excel ───────────────────────────────────────────
    async with cl.Step(name="AuditWriter") as step:
        step.output = "Writing corrected Excel + audit log..."
        step_input = StepInput(previous_step_content=mapper_out.content)
        audit_out = await asyncio.get_event_loop().run_in_executor(
            None, partial(audit_executor, step_input, session_state)
        )
        if not audit_out.success:
            step.output = f"Failed: {audit_out.content}"
            await cl.Message(f"Pipeline stopped at AuditWriter:\n```\n{audit_out.content}\n```").send()
            return

        audit_result = AuditResult.model_validate_json(audit_out.content)
        precision_str = f"{audit_result.precision:.2%}" if audit_result.precision is not None else "N/A"
        step.output = (
            f"Corrected: **{audit_result.corrected_count}** — "
            f"Review queue: **{audit_result.review_queue_count}** — "
            f"Precision: **{precision_str}**"
        )

    await cl.Message(
        content=(
            f"Pipeline complete.\n\n"
            f"| Metric | Value |\n"
            f"|--------|-------|\n"
            f"| Corrected | {audit_result.corrected_count} |\n"
            f"| Needs review | {audit_result.review_queue_count} |\n"
            f"| Precision | {precision_str} |\n\n"
            "Download your corrected file:"
        ),
        elements=[
            cl.File(
                name="corrected.xlsx",
                path=audit_result.output_path,
                display="inline",
            )
        ],
    ).send()
