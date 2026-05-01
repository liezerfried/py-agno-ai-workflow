"""
Shared fixtures for unit and integration tests.

Design goals:
- All filesystem artefacts live in tmp_path (pytest-managed, cleaned up automatically).

- The stub LLM is opt-in via the `stub_llm` fixture; real-LLM tests just skip the fixture.
- valid_categories_fixture is a small, deterministic slice of the real O*NET list, covering
  every normalization type the pipeline exercises.
"""

from __future__ import annotations


def pytest_addoption(parser):
    parser.addoption(
        "--real-llm",
        action="store_true",
        default=False,
        help="Run tests that make real LLM calls (requires LLM_PROVIDER env var).",
    )

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock, patch

import openpyxl
import pytest

from agno.workflow import StepInput

from agents.audit_writer_agent import AuditResult
from agents.ingest_agent import IngestResult
from agents.mapper_agent import MappingResult, SemanticMatch
from agents.validator_agent import ValidatorResult


@dataclass
class PipelineResult:
    ingest: IngestResult
    validator: ValidatorResult
    mapper: MappingResult
    audit: AuditResult
    output_path: str

# ---------------------------------------------------------------------------
# Canonical test vocabulary — deterministic, covers all 7 normalization types
# ---------------------------------------------------------------------------

VALID_CATEGORIES: list[str] = [
    "Software Developers",
    "Software Quality Assurance Analysts and Testers",
    "Human Resources Managers",
    "Frontend Web Developers",
    "Backend Web Developers",
    "Data Scientists",
    "Accountants and Auditors",
    "Sales Managers",
    "Marketing Managers",
    "Registered Nurses",
]
VALID_CATEGORIES_SET: set[str] = set(VALID_CATEGORIES)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def valid_cats() -> tuple[list[str], set[str]]:
    """Return the test vocabulary as (list, set) matching session_state layout."""
    return VALID_CATEGORIES, VALID_CATEGORIES_SET


@pytest.fixture()
def valid_categories_csv(tmp_path: Path) -> Path:
    """Write the test vocabulary to a CSV file that _load_valid_categories() can read."""
    csv_path = tmp_path / "valid_categories.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["category"])
        writer.writeheader()
        writer.writerows({"category": c} for c in VALID_CATEGORIES)
    return csv_path


def make_excel(path: Path, column: str, rows: list[str]) -> Path:
    """
    Write a minimal one-column Excel file.

    Args:
        path: Destination .xlsx path (parent dir must exist).
        column: Header name for the job-category column.
        rows: One value per data row (may contain duplicates, None-like strings, etc.).
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([column])
    for r in rows:
        ws.append([r])
    wb.save(path)
    return path


@pytest.fixture()
def excel_factory(tmp_path: Path):
    """
    Factory fixture.  Call it with (column_name, rows) → returns Path to .xlsx.

    Example::

        def test_something(excel_factory):
            xl = excel_factory("job_title", ["Software Developers", "RRHH"])
    """

    def _make(column: str, rows: list[str]) -> Path:
        p = tmp_path / "input.xlsx"
        return make_excel(p, column, rows)

    return _make


def make_step_input(content: str) -> StepInput:
    """Construct a StepInput whose previous_step_content is *content*."""
    return StepInput(previous_step_content=content)


@pytest.fixture()
def step_input_factory():
    """Return the make_step_input helper as a fixture for tests that prefer fixture injection."""
    return make_step_input


# ---------------------------------------------------------------------------
# Stub LLM
# ---------------------------------------------------------------------------


class StubLLM:
    """
    Drop-in replacement for mapper_agent.mapper_agent.run().

    Default behaviour: always returns a SemanticMatch that says 'not equivalent'
    so no LLM-band decision is auto-accepted.  Override `responses` to drive
    specific answers.

    responses: list of SemanticMatch values, consumed in order (last one repeated).
    """

    def __init__(self, responses: list[SemanticMatch] | None = None) -> None:
        self.responses = responses or [
            SemanticMatch(
                is_equivalent=False,
                canonical_title=None,
                normalization_type="unknown",
            )
        ]
        self._call_count = 0

    def __call__(self, *args, **kwargs) -> MagicMock:
        idx = min(self._call_count, len(self.responses) - 1)
        self._call_count += 1
        mock = MagicMock()
        mock.content = self.responses[idx]
        return mock

    @property
    def call_count(self) -> int:
        return self._call_count


@pytest.fixture()
def stub_mapper() -> Iterator[StubLLM]:
    """
    Inject a StubLLM via set_agent() — the canonical test seam for the mapper.

    Defaults to 'not equivalent' so every LLM-band input escalates to
    needs_review.  Tests that need specific responses should patch
    agents.mapper_agent._mapper_agent directly and set mock_agent.run.side_effect.
    """
    from agents.mapper_agent import set_agent

    stub = StubLLM()

    class _StubAgent:
        def run(self, *args, **kwargs):
            return stub(*args, **kwargs)

    set_agent(_StubAgent())
    try:
        yield stub
    finally:
        set_agent(None)


@pytest.fixture()
def stub_llm() -> Iterator[StubLLM]:
    """Backward-compat alias for stub_mapper."""
    from agents.mapper_agent import set_agent

    stub = StubLLM()

    class _StubAgent:
        def run(self, *args, **kwargs):
            return stub(*args, **kwargs)

    set_agent(_StubAgent())
    try:
        yield stub
    finally:
        set_agent(None)