import re

import openpyxl
from pydantic import BaseModel
from rapidfuzz import fuzz, process

from agno.workflow import OnError, Step, StepInput, StepOutput

from infrastructure.pipeline.session import PipelineSession
from infrastructure.pipeline.step_io import fail, ok

_JOB_COLUMN_SYNONYMS: list[str] = [
    # English — generic
    "job category", "job title", "job function", "job role", "job type",
    "position", "role", "occupation", "title", "function", "designation",
    "category", "profession", "trade", "job", "work category",
    # English — compound
    "job description", "job name", "job classification", "job code",
    "employment category", "staff category", "staff role", "work role",
    # Spanish — generic
    "cargo", "puesto", "categoria", "categoría", "ocupacion", "ocupación",
    "rol", "funcion", "función", "denominacion", "denominación", "empleo",
    # Spanish — compound
    "tipo cargo", "categoria empleo", "categoria laboral", "nombre cargo",
    "descripcion cargo", "descripcion puesto", "puesto trabajo",
    "tipo empleo", "perfil", "perfil laboral", "area funcional",
    "puesto de trabajo", "categoria de empleo", "categoria de trabajo",
]


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


def detect_job_column(column_names: list[str]) -> tuple[str | None, float]:
    """Returns (best_column_name, score 0.0–1.0). (None, 0.0) when list is empty."""
    if not column_names:
        return None, 0.0

    best_col: str | None = None
    best_score: float = 0.0

    for col in column_names:
        normalized = re.sub(r"[\s_\-\.]+", " ", col.lower()).strip()
        match = process.extractOne(normalized, _JOB_COLUMN_SYNONYMS, scorer=fuzz.WRatio)
        if match:
            score = round(match[1] / 100.0, 4)
            if score > best_score:
                best_col = col
                best_score = score

    return best_col, best_score


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