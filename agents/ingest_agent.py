import openpyxl
from pydantic import BaseModel

from agno.workflow import OnError, Step, StepInput, StepOutput

from infrastructure.pipeline.session import PipelineSession
from infrastructure.pipeline.step_io import fail, ok


class HeaderScanResult(BaseModel):
    file_path: str
    column_names: list[str]


class IngestResult(BaseModel):
    file_path: str
    target_column: str
    raw_categories: list[str]   # unique, sorted, stripped
    total_rows: int


def scan_headers(file_path: str) -> HeaderScanResult:
    wb = openpyxl.load_workbook(file_path, read_only=True)
    ws = wb.active
    headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1)) if cell.value is not None]
    wb.close()
    return HeaderScanResult(file_path=file_path, column_names=headers)


def extract_categories(file_path: str, target_column: str) -> IngestResult:
    wb = openpyxl.load_workbook(file_path, read_only=True)
    ws = wb.active

    header_row = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
    if target_column not in header_row:
        raise ValueError(f"Column '{target_column}' not found. Available: {header_row}")

    col_idx = header_row.index(target_column)

    raw_values: list[str] = []
    total_rows = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        total_rows += 1
        val = row[col_idx]
        if val is not None:
            raw_values.append(str(val).strip())

    wb.close()

    unique_categories = sorted(set(raw_values))
    return IngestResult(
        file_path=file_path,
        target_column=target_column,
        raw_categories=unique_categories,
        total_rows=total_rows,
    )


def ingest_executor(_step_input: StepInput, session_state: dict) -> StepOutput:
    try:
        session = PipelineSession.from_dict(session_state)
        result = extract_categories(session.file_path, session.target_column)
        return ok(result)
    except Exception as e:
        return fail(e)


ingest_step = Step(name="ingest", executor=ingest_executor, on_error=OnError.fail)