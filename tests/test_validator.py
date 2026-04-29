import pytest

from agents.validator_agent import _validate_category

VALID = [
    "Software Engineer",
    "Data Scientist",
    "Human Resources Managers",
    "Frontend Developer",
    "Backend Developer",
]


def test_exact_match_is_valid() -> None:
    result = _validate_category("Software Engineer", VALID)
    assert result.is_valid is True
    assert result.similarity_score == 1.0
    assert result.closest_match is None


def test_exact_match_case_sensitive() -> None:
    # Exact check is case-sensitive; "software engineer" != "Software Engineer"
    result = _validate_category("software engineer", VALID)
    assert result.is_valid is False
    assert result.similarity_score < 1.0
    assert result.closest_match == "Software Engineer"


def test_near_miss_returns_closest_match() -> None:
    # "Softwaree Engineer" is a typo — should score high but not 1.0
    result = _validate_category("Softwaree Engineer", VALID)
    assert result.is_valid is False
    assert result.closest_match == "Software Engineer"
    assert 0.70 <= result.similarity_score < 1.0


def test_complete_miss_scores_low() -> None:
    result = _validate_category("xyz123", VALID)
    assert result.is_valid is False
    assert result.similarity_score < 0.70


def test_anomalies_prefiltered() -> None:
    from agno.workflow import StepInput, StepOutput
    from agents.ingest_agent import IngestResult
    from agents.validator_agent import validator_executor

    ingest_result = IngestResult(
        file_path="dummy.xlsx",
        target_column="job",
        raw_categories=["Software Engineer", "Softwaree Engineer", "xyz123"],
        total_rows=3,
    )

    class FakeStepInput:
        previous_step_content = ingest_result.model_dump_json()

    session_state = {"valid_categories": VALID, "valid_categories_set": set(VALID)}
    output: StepOutput = validator_executor(FakeStepInput(), session_state)  # type: ignore[arg-type]

    from agents.validator_agent import ValidatorResult
    result = ValidatorResult.model_validate_json(output.content)

    assert result.valid_count == 1
    assert result.anomaly_count == 2
    assert len(result.anomalies) == 2
    assert all(not a.is_valid for a in result.anomalies)