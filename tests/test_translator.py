from unittest.mock import MagicMock

import pytest

from agents.translator_agent import translate, set_agent, TranslationResult


def _make_stub(english_title: str, was_translated: bool, normalization_type: str = "unknown"):
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
def reset_agent():
    yield
    set_agent(None)


def test_translates_spanish():
    set_agent(_make_stub("software developer", True, "language"))
    result = translate("Desarrollador de Software")
    assert result.english_title == "software developer"
    assert result.was_translated is True
    assert result.normalization_type == "language"


def test_expands_abbreviation():
    set_agent(_make_stub("human resources", True, "abbreviation"))
    result = translate("RRHH")
    assert result.was_translated is True
    assert result.normalization_type == "abbreviation"


def test_expands_rn():
    set_agent(_make_stub("registered nurse", True, "abbreviation"))
    result = translate("RN")
    assert result.english_title == "registered nurse"
    assert result.was_translated is True


def test_english_unchanged():
    set_agent(_make_stub("Software Developer", False))
    result = translate("Software Developer")
    assert result.was_translated is False


def test_translation_failure_returns_raw():
    mock_agent = MagicMock()
    mock_agent.run.side_effect = RuntimeError("LLM unavailable")
    set_agent(mock_agent)
    result = translate("RRHH")
    assert result.english_title == "RRHH"
    assert result.was_translated is False
