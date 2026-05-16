from unittest.mock import MagicMock, patch

import pytest

from agents.mapper_agent import SemanticMatch, _decide
from agents.translator_agent import TranslationResult, set_agent as set_translator_agent
from infrastructure.pipeline.contracts import CategoryValidation

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
    with patch("agents.mapping_pipeline.process.extract", return_value=[("Frontend Developers", 100, 3)]):
        decision = _decide(_anomaly("Frontend Developers"), VALID, VALID_SET)
    assert decision.method == "exact"
    assert decision.normalization_type == "format"
    assert decision.needs_review is False
    assert decision.corrected == "Frontend Developers"
    assert decision.review_reason is None


def test_fuzzy_high_confidence_no_llm() -> None:
    with patch("agents.mapping_pipeline.process.extract", return_value=[("Frontend Developers", 95, 3)]):
        decision = _decide(_anomaly("Fronted Developers"), VALID, VALID_SET)
    assert decision.method == "fuzzy"
    assert decision.normalization_type == "typo"
    assert decision.needs_review is False
    assert decision.corrected == "Frontend Developers"
    assert decision.review_reason is None


def test_low_confidence_escalates_without_llm() -> None:
    with patch("agents.mapping_pipeline.process.extract", return_value=[("Software Engineers", 40, 0)]):
        decision = _decide(_anomaly("xyzzy123"), VALID, VALID_SET)
    assert decision.method == "needs_review"
    assert decision.normalization_type == "unknown"
    assert decision.needs_review is True
    assert decision.corrected is None
    assert decision.review_reason == "low_confidence"


def test_llm_band_equivalent_accepted() -> None:
    semantic = SemanticMatch(
        is_equivalent=True,
        canonical_title="Human Resources Managers",
        normalization_type="abbreviation",
    )
    mock_run = MagicMock()
    mock_run.content = semantic

    with patch("agents.mapping_pipeline.process.extract", return_value=[("Human Resources Managers", 78, 2)]):
        with patch("agents.mapper_agent._mapper_agent") as mock_agent:
            mock_agent.run.return_value = mock_run
            decision = _decide(_anomaly("RRHH"), VALID, VALID_SET)

    assert decision.method == "llm"
    assert decision.normalization_type == "abbreviation"
    assert decision.needs_review is False
    assert decision.corrected == "Human Resources Managers"
    assert decision.review_reason is None


def test_llm_band_not_equivalent_escalates() -> None:
    semantic = SemanticMatch(
        is_equivalent=False,
        canonical_title=None,
        normalization_type="unknown",
    )
    mock_run = MagicMock()
    mock_run.content = semantic

    with patch("agents.mapping_pipeline.process.extract", return_value=[("Accountants and Auditors", 75, 5)]):
        with patch("agents.mapper_agent._mapper_agent") as mock_agent:
            mock_agent.run.return_value = mock_run
            decision = _decide(_anomaly("comercial"), VALID, VALID_SET)

    assert decision.method == "needs_review"
    assert decision.normalization_type == "unknown"
    assert decision.needs_review is True
    assert decision.corrected is None
    assert decision.review_reason == "llm_no_match"


def test_hallucination_guard_rejects_invented_title() -> None:
    semantic = SemanticMatch(
        is_equivalent=True,
        canonical_title="Chief People Officer",   # not in VALID_SET
        normalization_type="unknown",
    )
    mock_run = MagicMock()
    mock_run.content = semantic

    with patch("agents.mapping_pipeline.process.extract", return_value=[("Human Resources Managers", 78, 2)]):
        with patch("agents.mapper_agent._mapper_agent") as mock_agent:
            mock_agent.run.return_value = mock_run
            decision = _decide(_anomaly("RRHH"), VALID, VALID_SET)

    assert decision.needs_review is True
    assert decision.normalization_type == "unknown"
    assert decision.corrected is None
    assert decision.review_reason == "llm_hallucination"


def test_llm_unexpected_content_type_falls_back_to_needs_review() -> None:
    mock_run = MagicMock()
    mock_run.content = "raw string instead of SemanticMatch"  # malformed LLM output

    with patch("agents.mapping_pipeline.process.extract", return_value=[("Human Resources Managers", 78, 2)]):
        with patch("agents.mapper_agent._mapper_agent") as mock_agent:
            mock_agent.run.return_value = mock_run
            decision = _decide(_anomaly("RRHH"), VALID, VALID_SET)

    assert decision.method == "needs_review"
    assert decision.needs_review is True
    assert decision.review_reason == "llm_error"


def test_llm_timeout_falls_back_to_needs_review() -> None:
    with patch("agents.mapping_pipeline.process.extract", return_value=[("Human Resources Managers", 78, 2)]):
        with patch("agents.mapper_agent._mapper_agent") as mock_agent:
            mock_agent.run.side_effect = TimeoutError("LLM timeout")
            decision = _decide(_anomaly("RRHH"), VALID, VALID_SET)

    assert decision.method == "needs_review"
    assert decision.normalization_type == "unknown"
    assert decision.needs_review is True
    assert decision.corrected is None
    assert decision.review_reason == "llm_error"


# ── Translation path (types 5, 6, 7) ──────────────────────────────────────────

def _make_translator_stub(english_title: str, was_translated: bool, normalization_type: str = "unknown"):
    mock_agent = MagicMock()
    mock_result = MagicMock()
    mock_result.content = TranslationResult(
        english_title=english_title,
        was_translated=was_translated,
        normalization_type=normalization_type,
    )
    mock_agent.run.return_value = mock_result
    return mock_agent


@pytest.fixture(autouse=True)
def reset_translator():
    # Stub out the translator for all mapper tests to avoid real LLM calls.
    # Tests that exercise the translation path override this via set_translator_agent().
    set_translator_agent(_make_translator_stub("noop", False))
    yield
    set_translator_agent(None)


def test_spanish_title_reaches_llm_after_translation() -> None:
    semantic = SemanticMatch(
        is_equivalent=True,
        canonical_title="Software Engineers",
        normalization_type="language",
    )
    mock_mapper_run = MagicMock()
    mock_mapper_run.content = semantic

    set_translator_agent(_make_translator_stub("software engineer", True, "language"))

    # First extract call (original "Desarrollador de Software") returns low score (review band).
    # Second extract call (translated "software engineer") returns LLM-band score.
    extract_side_effects = [
        [("Software Engineers", 40, 0)],   # original raw → review
        [("Software Engineers", 78, 0)],   # translated → llm band
    ]
    with patch("agents.mapping_pipeline.process.extract", side_effect=extract_side_effects):
        with patch("agents.mapper_agent._mapper_agent") as mock_mapper_agent:
            mock_mapper_agent.run.return_value = mock_mapper_run
            decision = _decide(_anomaly("Desarrollador de Software"), VALID, VALID_SET)

    assert decision.method == "llm"
    assert decision.corrected == "Software Engineers"
    assert decision.needs_review is False


def test_abbreviation_reaches_llm_after_translation() -> None:
    semantic = SemanticMatch(
        is_equivalent=True,
        canonical_title="Human Resources Managers",
        normalization_type="abbreviation",
    )
    mock_mapper_run = MagicMock()
    mock_mapper_run.content = semantic

    set_translator_agent(_make_translator_stub("human resources", True, "abbreviation"))

    extract_side_effects = [
        [("Human Resources Managers", 40, 0)],   # original → review
        [("Human Resources Managers", 78, 0)],   # translated → llm band
    ]
    with patch("agents.mapping_pipeline.process.extract", side_effect=extract_side_effects):
        with patch("agents.mapper_agent._mapper_agent") as mock_mapper_agent:
            mock_mapper_agent.run.return_value = mock_mapper_run
            decision = _decide(_anomaly("RRHH"), VALID, VALID_SET)

    assert decision.method == "llm"
    assert decision.corrected == "Human Resources Managers"
    assert decision.needs_review is False


def test_translation_failure_goes_to_review() -> None:
    set_translator_agent(_make_translator_stub("RRHH", False))

    with patch("agents.mapping_pipeline.process.extract", return_value=[("Human Resources Managers", 40, 0)]):
        decision = _decide(_anomaly("RRHH"), VALID, VALID_SET)

    assert decision.needs_review is True
    assert decision.review_reason == "low_confidence"


def test_translator_expands_abbreviation_even_when_not_flagged_translated() -> None:
    """
    Audit (2026-05-09) found 9 needs_review cases where the translator
    returned a useful expanded title (e.g. 'Backend Developer' for 'Back-End
    Dev') but set was_translated=False because the input was already English.
    The pipeline was discarding that expansion. The fix: re-fuzzy whenever the
    title actually changed, regardless of the was_translated flag.
    """
    semantic = SemanticMatch(
        is_equivalent=True,
        canonical_title="Backend Developers",
        normalization_type="abbreviation",
    )
    mock_mapper_run = MagicMock()
    mock_mapper_run.content = semantic

    # Translator returns the expanded form but with was_translated=False
    # because the input was already English. The pipeline should still
    # exploit the expansion.
    set_translator_agent(_make_translator_stub("Backend Developer", False, "abbreviation"))

    extract_side_effects = [
        [("Backend Developers", 50, 0)],   # original 'Back-End Dev' → review band
        [("Backend Developers", 78, 0)],   # translated 'Backend Developer' → llm band
    ]
    with patch("agents.mapping_pipeline.process.extract", side_effect=extract_side_effects):
        with patch("agents.mapper_agent._mapper_agent") as mock_mapper_agent:
            mock_mapper_agent.run.return_value = mock_mapper_run
            decision = _decide(_anomaly("Back-End Dev"), VALID + ["Backend Developers"], VALID_SET | {"Backend Developers"})

    assert decision.method == "llm"
    assert decision.corrected == "Backend Developers"
    assert decision.needs_review is False


def test_translator_unchanged_title_still_goes_to_review() -> None:
    """
    Guard the inverse: when the translator returns the *same* string and
    was_translated=False (no useful change), we must NOT loop or pretend
    progress. The case must still escalate to needs_review.
    """
    set_translator_agent(_make_translator_stub("xyz unknown", False))

    with patch("agents.mapping_pipeline.process.extract", return_value=[("Software Engineers", 40, 0)]):
        decision = _decide(_anomaly("xyz unknown"), VALID, VALID_SET)

    assert decision.needs_review is True
    assert decision.review_reason == "low_confidence"


def test_translated_but_still_low_score_goes_to_review() -> None:
    set_translator_agent(_make_translator_stub("certified public accountant", True, "abbreviation"))

    # Both original and translated score below review threshold
    extract_side_effects = [
        [("Accountants and Auditors", 40, 5)],   # original → review
        [("Accountants and Auditors", 45, 5)],   # translated → still review
    ]
    with patch("agents.mapping_pipeline.process.extract", side_effect=extract_side_effects):
        decision = _decide(_anomaly("CPA"), VALID, VALID_SET)

    assert decision.needs_review is True
    assert decision.review_reason == "low_confidence"


def test_translated_fuzzy_uses_translation_normalization_type() -> None:
    set_translator_agent(_make_translator_stub("data scientist", True, "language"))

    extract_side_effects = [
        [("Data Scientists", 40, 1)],   # original → review
        [("Data Scientists", 95, 1)],   # translated → fuzzy band
    ]
    with patch("agents.mapping_pipeline.process.extract", side_effect=extract_side_effects):
        decision = _decide(_anomaly("Cientifico de Datos"), VALID, VALID_SET)

    assert decision.method == "fuzzy"
    assert decision.normalization_type == "language"
    assert decision.corrected == "Data Scientists"
    assert decision.needs_review is False