import openpyxl
from pydantic import BaseModel

from agno.workflow import OnError, Step, StepInput, StepOutput


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
        file_path: str = session_state["file_path"]
        target_column: str = session_state["target_column"]
        result = extract_categories(file_path, target_column)
        return StepOutput(content=result.model_dump_json())
    except Exception as e:
        return StepOutput(content=str(e), success=False, stop=True)


ingest_step = Step(name="ingest", executor=ingest_executor, on_error=OnError.fail)