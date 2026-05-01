"""
Unit and integration tests for agents/mapping_pipeline.py.

Zero mocks — all tests use the real pre_processor and real rapidfuzz.
The key cases exercise the seniority-strip → confidence band interaction:
  "Lead Accountants and Auditors" → strip "lead" → 0.91 → fuzzy auto-correct
  "Senior Data Scientists"        → strip "senior" → 0.87 → llm band
"""

from __future__ import annotations

import pytest

from agents.mapping_pipeline import FuzzyResult, PipelineConfig, routing_band, score

# ---------------------------------------------------------------------------
# Test vocabulary — small enough to reason about, covers the 4 routing bands
# ---------------------------------------------------------------------------

VALID = [
    "accountants and auditors",   # lowercase so seniority-stripped form hits 1.0
    "Data Scientists",
    "Human Resources Managers",
    "Frontend Web Developers",
    "Software Developers",
]

CONFIG = PipelineConfig()


# ---------------------------------------------------------------------------
# routing_band — pure unit tests (no rapidfuzz, no pre_processor)
# ---------------------------------------------------------------------------


def test_routing_band_exact() -> None:
    assert routing_band(1.0, CONFIG) == "exact"


def test_routing_band_fuzzy_at_high_threshold() -> None:
    assert routing_band(CONFIG.high_threshold, CONFIG) == "fuzzy"


def test_routing_band_fuzzy_just_below_exact() -> None:
    assert routing_band(0.99, CONFIG) == "fuzzy"


def test_routing_band_llm_at_low_threshold() -> None:
    assert routing_band(CONFIG.low_threshold, CONFIG) == "llm"


def test_routing_band_llm_just_below_high() -> None:
    assert routing_band(0.89, CONFIG) == "llm"


def test_routing_band_review_just_below_low() -> None:
    assert routing_band(round(CONFIG.low_threshold - 0.01, 4), CONFIG) == "review"


def test_routing_band_review_on_zero() -> None:
    assert routing_band(0.0, CONFIG) == "review"


def test_routing_band_custom_thresholds() -> None:
    strict = PipelineConfig(high_threshold=0.95, low_threshold=0.80)
    assert routing_band(0.94, strict) == "llm"    # fuzzy with defaults, llm with strict
    assert routing_band(0.79, strict) == "review"  # llm with defaults, review with strict


# ---------------------------------------------------------------------------
# score() — seniority-strip → confidence band interaction (real rapidfuzz)
# ---------------------------------------------------------------------------


def test_seniority_lead_strips_to_fuzzy_band() -> None:
    """'Lead Accountants and Auditors' — strip 'lead' → match 'accountants and auditors' → fuzzy."""
    r = score("Lead Accountants and Auditors", VALID, CONFIG)
    assert r.preprocessed == "accountants and auditors"
    assert r.top_match == "accountants and auditors"
    assert r.top_score == 1.0
    assert routing_band(r.top_score, CONFIG) == "exact"


def test_seniority_senior_strips_to_llm_band() -> None:
    """'Senior Data Scientists' — strip 'senior' → 'data scientists' → 0.87 vs 'Data Scientists' → llm."""
    r = score("Senior Data Scientists", VALID, CONFIG)
    assert r.preprocessed == "data scientists"
    assert r.top_match == "Data Scientists"
    band = routing_band(r.top_score, CONFIG)
    assert band == "llm", f"Expected llm band, got {band!r} (score={r.top_score:.4f})"


def test_seniority_case_invariant() -> None:
    """Pre-processor lowercases before stripping — 'SENIOR' and 'Senior' produce same result."""
    r_lower = score("Senior Data Scientists", VALID, CONFIG)
    r_upper = score("SENIOR DATA SCIENTISTS", VALID, CONFIG)
    assert r_lower.preprocessed == r_upper.preprocessed
    assert r_lower.top_score == r_upper.top_score


def test_gibberish_falls_to_review_band() -> None:
    r = score("xyz999abc", VALID, CONFIG)
    assert routing_band(r.top_score, CONFIG) == "review"


def test_empty_categories_returns_zero_score() -> None:
    r = score("Software Developers", [], CONFIG)
    assert r.top_match is None
    assert r.top_score == 0.0
    assert r.candidates == []
    assert routing_band(r.top_score, CONFIG) == "review"


def test_candidates_bounded_by_top_n() -> None:
    r = score("Software Developers", VALID, CONFIG)
    assert len(r.candidates) <= CONFIG.top_n


def test_candidates_are_normalized_score_tuples() -> None:
    r = score("Data Scientists", VALID, CONFIG)
    for title, s in r.candidates:
        assert isinstance(title, str)
        assert 0.0 <= s <= 1.0