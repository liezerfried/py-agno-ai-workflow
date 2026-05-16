"""
Tests for the TranslatorAgent translation cache.

Mirrors the decision cache pattern in mapper_agent: a module-level dict keyed
by the raw input, so the same string never costs two LLM calls in one process.
Most of the deduplication value already comes from the decision cache (the
translator runs inside _decide), but caching at the translator layer keeps
the optimisation composable for any future caller of translate().
"""
from __future__ import annotations

from unittest.mock import MagicMock

from agents.translator_agent import (
    TranslationResult,
    clear_translation_cache,
    set_agent as set_translator_agent,
    translate,
)


def _make_translator_stub(english: str, was_translated: bool, ntype: str = "unknown"):
    """Return a stub agent whose .run() returns the given TranslationResult and
    records its calls for assertion."""
    stub = MagicMock()
    result = MagicMock()
    result.content = TranslationResult(
        english_title=english, was_translated=was_translated, normalization_type=ntype
    )
    stub.run.return_value = result
    return stub


def test_repeated_raw_calls_translator_only_once() -> None:
    clear_translation_cache()
    stub = _make_translator_stub("Backend Developer", True, "abbreviation")
    set_translator_agent(stub)
    try:
        translate("Back-End Dev")
        translate("Back-End Dev")
        translate("Back-End Dev")
        assert stub.run.call_count == 1, (
            f"translator should be called once for repeated input; got {stub.run.call_count}"
        )
    finally:
        set_translator_agent(None)
        clear_translation_cache()


def test_distinct_raws_each_call_translator() -> None:
    clear_translation_cache()
    stub = _make_translator_stub("X", True)
    set_translator_agent(stub)
    try:
        translate("raw_alpha")
        translate("raw_beta")
        translate("raw_gamma")
        assert stub.run.call_count == 3
    finally:
        set_translator_agent(None)
        clear_translation_cache()


def test_clear_translation_cache_forces_recompute() -> None:
    clear_translation_cache()
    stub = _make_translator_stub("X", True)
    set_translator_agent(stub)
    try:
        translate("same_raw")
        assert stub.run.call_count == 1
        clear_translation_cache()
        translate("same_raw")
        assert stub.run.call_count == 2, (
            f"clear_translation_cache should force a new translator call; got {stub.run.call_count}"
        )
    finally:
        set_translator_agent(None)
        clear_translation_cache()


def test_failed_translation_is_cached_to_avoid_retry_storms() -> None:
    """If translation raises, the fallback (raw passthrough) is cached so a
    transient failure on a repeated input does not keep hammering the LLM."""
    clear_translation_cache()
    stub = MagicMock()
    stub.run.side_effect = RuntimeError("upstream is sad")
    set_translator_agent(stub)
    try:
        r1 = translate("transient_failure_raw")
        r2 = translate("transient_failure_raw")
        assert stub.run.call_count == 1
        assert r1.english_title == "transient_failure_raw"
        assert r1.was_translated is False
        assert r2 == r1
    finally:
        set_translator_agent(None)
        clear_translation_cache()
