"""
Tests for the LLM model factory in infrastructure/llm/provider.py.

The cuelgue investigation (2026-05-08) showed that LM Studio occasionally
takes 12+ seconds for a single completion, and the pipeline had no upper
bound on how long it would wait. A configurable timeout shifts that risk
from "process hangs forever" to "row falls back to needs_review", which is
exactly the failure mode _handle_llm() already absorbs gracefully.
"""
from __future__ import annotations

import pytest

from infrastructure.llm.provider import get_model


def test_default_timeout_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without LLM_TIMEOUT_SECONDS the model is built with the default ceiling."""
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "lmstudio")
    model = get_model()
    assert getattr(model, "timeout", None) == 60


def test_custom_timeout_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_TIMEOUT_SECONDS overrides the default."""
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("LLM_PROVIDER", "lmstudio")
    model = get_model()
    assert getattr(model, "timeout", None) == 15


def test_groq_provider_also_receives_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same timeout knob applies whether dev (LM Studio) or prod (Groq)."""
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    # Groq() reads GROQ_API_KEY at construction; provide a stub so it does not
    # hit real auth. The key never leaves the constructor for this assertion.
    monkeypatch.setenv("GROQ_API_KEY", "stub-key-for-test")
    model = get_model()
    assert getattr(model, "timeout", None) == 30


def test_invalid_timeout_value_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-integer LLM_TIMEOUT_SECONDS does not crash the factory; default wins."""
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "not-a-number")
    monkeypatch.setenv("LLM_PROVIDER", "lmstudio")
    model = get_model()
    assert getattr(model, "timeout", None) == 60


# ── Temperature (determinism) ─────────────────────────────────────────────────


def test_default_temperature_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    temperature=0 is the default so two runs against the same input produce
    the same mapping decision. Run-to-run variance was the largest residual
    annoyance after the cuelgue fix; this knob removes it at the model layer.
    """
    monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "lmstudio")
    model = get_model()
    assert getattr(model, "temperature", None) == 0


def test_custom_temperature_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_TEMPERATURE overrides the default for experimentation."""
    monkeypatch.setenv("LLM_TEMPERATURE", "0.7")
    monkeypatch.setenv("LLM_PROVIDER", "lmstudio")
    model = get_model()
    assert getattr(model, "temperature", None) == 0.7


def test_groq_provider_also_receives_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both dev (LM Studio) and prod (Groq) get the same determinism guarantee."""
    monkeypatch.setenv("LLM_TEMPERATURE", "0")
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "stub-key-for-test")
    model = get_model()
    assert getattr(model, "temperature", None) == 0


def test_invalid_temperature_falls_back_to_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-numeric LLM_TEMPERATURE does not abort the factory; default wins."""
    monkeypatch.setenv("LLM_TEMPERATURE", "not-a-number")
    monkeypatch.setenv("LLM_PROVIDER", "lmstudio")
    model = get_model()
    assert getattr(model, "temperature", None) == 0
