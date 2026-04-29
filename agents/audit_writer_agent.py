import os
from datetime import datetime
from pathlib import Path

import openpyxl
from pydantic import BaseModel

from agno.workflow import OnError, Step, StepInput, StepOutput

from agents.mapper_agent import MappingDecision, MappingResult


class AuditResult(BaseModel):
    output_path: str
    corrected_count: int
    review_queue_count: int
    hallucination_count: int
    precision: float | None   # corrected / (corrected + hallucination); None if no corrections attempted


def _write_excel(
    source_path: str,
    decisions_by_raw: dict[str, MappingDecision],
    target_column: str,
    valid_categories_set: set[str],
) -> tuple[str, int, int, int]:
    wb_in = openpyxl.load_workbook(source_path)
    ws_in = wb_in.active

    headers = [cell.value for cell in next(ws_in.iter_rows(min_row=1, max_row=1))]
    col_idx = headers.index(target_column)

    wb_out = openpyxl.Workbook()

    # Sheet 1: Corrected data
    ws_corrected = wb_out.active
    ws_corrected.title = "Corrected"
    ws_corrected.append(headers + ["corrected_category", "correction_method", "confidence"])

    # Sheet 2: Review queue
    ws_review = wb_out.create_sheet("Review Queue")
    ws_review.append(["original_category", "reason"])

    corrected_count = 0
    review_queue_count = 0
    hallucination_count = 0

    for row in ws_in.iter_rows(min_row=2, values_only=True):
        raw_val = str(row[col_idx]).strip() if row[col_idx] is not None else None
        decision = decisions_by_raw.get(raw_val) if raw_val else None

        if decision is None:
            # Category was already valid — pass through unchanged
            ws_corrected.append(list(row) + [raw_val, "exact", 1.0])
            continue

        if decision.needs_review:
            ws_corrected.append(list(row) + [None, decision.method, decision.confidence])
            ws_review.append([decision.raw, decision.method])
            review_queue_count += 1
            continue

        corrected = decision.corrected
        # Hard invariant: verify correction is in valid_categories_set before writing
        if corrected not in valid_categories_set:
            ws_corrected.append(list(row) + [None, "needs_review", decision.confidence])
            ws_review.append([decision.raw, "hallucination_rejected"])
            hallucination_count += 1
            review_queue_count += 1
            continue

        ws_corrected.append(list(row) + [corrected, decision.method, decision.confidence])
        corrected_count += 1

    wb_in.close()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    source_stem = Path(source_path).stem
    output_dir = Path(source_path).parent
    output_path = str(output_dir / f"{source_stem}_corrected_{timestamp}.xlsx")
    wb_out.save(output_path)

    return output_path, corrected_count, review_queue_count, hallucination_count


def audit_executor(step_input: StepInput, session_state: dict) -> StepOutput:
    try:
        mapping_result = MappingResult.model_validate_json(step_input.previous_step_content)
        file_path: str = session_state["file_path"]
        target_column: str = session_state["target_column"]
        valid_categories_set: set[str] = session_state["valid_categories_set"]

        decisions_by_raw = {d.raw: d for d in mapping_result.decisions}

        output_path, corrected_count, review_queue_count, hallucination_count = _write_excel(
            source_path=file_path,
            decisions_by_raw=decisions_by_raw,
            target_column=target_column,
            valid_categories_set=valid_categories_set,
        )

        total_attempted = corrected_count + hallucination_count
        precision = corrected_count / total_attempted if total_attempted > 0 else None

        result = AuditResult(
            output_path=output_path,
            corrected_count=corrected_count,
            review_queue_count=review_queue_count,
            hallucination_count=hallucination_count,
            precision=precision,
        )
        return StepOutput(content=result.model_dump_json())
    except Exception as e:
        return StepOutput(content=str(e), success=False, stop=True)


audit_step = Step(name="audit", executor=audit_executor, on_error=OnError.fail)