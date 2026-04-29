from unittest.mock import MagicMock, patch

import pytest

from agents.mapper_agent import SemanticMatch, _decide
from agents.validator_agent import CategoryValidation

VALID = [
    "Software Engineers",
    "Data Scientists",
    "Human Resources Managers",
    "Frontend Developers",
    "Backend Developers",
    "Accountants and Auditors",
]
VALID_SET = set(VALID)


def _anomaly(raw: str) -> CategoryValidation:
    return CategoryValidation(raw=raw, is_valid=False, closest_match=None, similarity_score=0.0)


def test_exact_score_method() -> None:
    with patch("agents.mapper_agent.process.extract", return_value=[("Frontend Developers", 100, 3)]):
        decision = _decide(_anomaly("Frontend Developers"), VALID, VALID_SET)
    assert decision.method == "exact"
    assert decision.normalization_type == "format"
    assert decision.needs_review is False
    assert decision.corrected == "Frontend Developers"


def test_fuzzy_high_confidence_no_llm() -> None:
    with patch("agents.mapper_agent.process.extract", return_value=[("Frontend Developers", 95, 3)]):
        decision = _decide(_anomaly("Fronted Developers"), VALID, VALID_SET)
    assert decision.method == "fuzzy"
    assert decision.normalization_type == "typo"
    assert decision.needs_review is False
    assert decision.corrected == "Frontend Developers"


def test_low_confidence_escalates_without_llm() -> None:
    with patch("agents.mapper_agent.process.extract", return_value=[("Software Engineers", 40, 0)]):
        decision = _decide(_anomaly("xyzzy123"), VALID, VALID_SET)
    assert decision.method == "needs_review"
    assert decision.normalization_type == "unknown"
    assert decision.needs_review is True
    assert decision.corrected is None


def test_llm_band_equivalent_accepted() -> None:
    semantic = SemanticMatch(
        is_equivalent=True,
        canonical_title="Human Resources Managers",
        normalization_type="abbreviation",
        reasoning="RRHH is a Spanish abbreviation for Human Resources.",
    )
    mock_run = MagicMock()
    mock_run.content = semantic

    with patch("agents.mapper_agent.process.extract", return_value=[("Human Resources Managers", 78, 2)]):
        with patch("agents.mapper_agent.mapper_agent.run", return_value=mock_run):
            decision = _decide(_anomaly("RRHH"), VALID, VALID_SET)

    assert decision.method == "llm"
    assert decision.normalization_type == "abbreviation"
    assert decision.needs_review is False
    assert decision.corrected == "Human Resources Managers"


def test_llm_band_not_equivalent_escalates() -> None:
    semantic = SemanticMatch(
        is_equivalent=False,
        canonical_title=None,
        normalization_type="unknown",
        reasoning="comercial does not map to any candidate.",
    )
    mock_run = MagicMock()
    mock_run.content = semantic

    with patch("agents.mapper_agent.process.extract", return_value=[("Accountants and Auditors", 75, 5)]):
        with patch("agents.mapper_agent.mapper_agent.run", return_value=mock_run):
            decision = _decide(_anomaly("comercial"), VALID, VALID_SET)

    assert decision.method == "needs_review"
    assert decision.normalization_type == "unknown"
    assert decision.needs_review is True
    assert decision.corrected is None


def test_hallucination_guard_rejects_invented_title() -> None:
    semantic = SemanticMatch(
        is_equivalent=True,
        canonical_title="Chief People Officer",   # not in VALID_SET
        normalization_type="unknown",
        reasoning="Hallucinated title.",
    )
    mock_run = MagicMock()
    mock_run.content = semantic

    with patch("agents.mapper_agent.process.extract", return_value=[("Human Resources Managers", 78, 2)]):
        with patch("agents.mapper_agent.mapper_agent.run", return_value=mock_run):
            decision = _decide(_anomaly("RRHH"), VALID, VALID_SET)

    assert decision.needs_review is True
    assert decision.normalization_type == "unknown"
    assert decision.corrected is None


def test_llm_timeout_falls_back_to_needs_review() -> None:
    with patch("agents.mapper_agent.process.extract", return_value=[("Human Resources Managers", 78, 2)]):
        with patch("agents.mapper_agent.mapper_agent.run", side_effect=TimeoutError("LLM timeout")):
            decision = _decide(_anomaly("RRHH"), VALID, VALID_SET)

    assert decision.method == "needs_review"
    assert decision.normalization_type == "unknown"
    assert decision.needs_review is True
    assert decision.corrected is None