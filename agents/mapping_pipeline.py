"""
Confidence-band routing: decides whether each raw category is auto-corrected, sent to the LLM, or flagged for human review.
Called by MapperAgent after ingest and validation; produces a FuzzyResult and routing label for every category.
This module never calls the LLM directly — it only measures string similarity and returns a routing decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

# rapidfuzz measures how similar two strings are on a 0–100 scale.
# A score of 90 means the two strings are roughly 90% similar.
# Used here to match user-typed job titles to the official O*NET list
# without calling the LLM — zero token cost, near-zero latency.
from rapidfuzz import fuzz, process

from agents.pre_processor import normalize_title


class LLMFailureReason(str, Enum):
    """
    Explains why an LLM call did not produce a usable correction.

    Each value corresponds to a distinct failure mode so callers can
    handle them differently (e.g. log hallucinations separately from errors).
    """
    no_match = "no_match"           # LLM ran but said not equivalent or returned null canonical_title
    hallucination = "hallucination" # LLM returned a title outside valid_categories_set or candidates
    error = "error"                 # exception raised during LLM call


# A frozen dataclass cannot be modified after creation — like a tuple with named fields.
# Frozen is used here so that no step can accidentally change the thresholds mid-pipeline.
@dataclass(frozen=True)
class PipelineConfig:
    """
    Thresholds that control the confidence-band routing logic.

    Raising high_threshold reduces auto-corrections but lowers false positives.
    Lowering low_threshold sends more cases to the LLM, increasing token cost.
    """
    top_n: int = 3                # How many candidate O*NET titles rapidfuzz returns per query.
    high_threshold: float = 0.90  # Minimum score for an auto-correction (no LLM call needed).
    low_threshold: float = 0.70   # Minimum score to route to the LLM; below this → human review.


@dataclass
class FuzzyResult:
    """
    The output of a single rapidfuzz lookup against the O*NET title list.

    Consumers use top_score to decide which confidence band applies, and
    candidates to give the LLM a small shortlist rather than all 923 titles.
    """
    preprocessed: str                         # The raw title after normalize_title() has run.
    top_match: str | None                     # The O*NET title with the highest similarity score, or None.
    top_score: float                          # Similarity score of top_match, on a 0.0–1.0 scale.
    candidates: list[tuple[str, float]]       # Up to top_n (title, score) pairs, sorted best-first.


def score(raw: str, valid_categories: list[str], config: PipelineConfig) -> FuzzyResult:
    """
    Pre-process a raw job title and measure its similarity to every O*NET canonical title.

    This is the mandatory rapidfuzz pre-filter that always runs before any LLM call,
    reducing token cost by catching clear matches without spending API credits.

    Normalization types handled before this function returns a result:
      - Type 1 (typo): rapidfuzz similarity absorbs minor character differences.
      - Types 2–4 (casing, seniority, noise): normalize_title strips these first.

    O*NET (Occupational Information Network) is the US Department of Labor database
    that provides 923 canonical job titles used as ground truth in this pipeline.

    Args:
        raw: The original free-text job title as typed by the user (e.g. "Dev Front").
        valid_categories: The full list of 923 O*NET canonical titles to match against.
        config: Routing thresholds and top_n candidate count.

    Returns:
        A FuzzyResult containing the best match and its similarity score on a 0.0–1.0 scale.
    """
    # normalize_title handles Types 2–4 (casing/punctuation, seniority, noise)
    # so rapidfuzz sees a cleaner string and scores more accurately.
    preprocessed = normalize_title(raw)

    # fuzz.WRatio is a weighted combination of several ratio strategies.
    # It handles partial matches and token reordering better than simple ratio.
    matches = process.extract(preprocessed, valid_categories, scorer=fuzz.WRatio, limit=config.top_n)

    if not matches:
        return FuzzyResult(preprocessed=preprocessed, top_match=None, top_score=0.0, candidates=[])

    top_match_str, top_score_raw, _ = matches[0]
    # rapidfuzz returns scores in 0–100; normalize to 0.0–1.0 to match the threshold constants.
    candidates = [(m[0], round(m[1] / 100.0, 4)) for m in matches]

    return FuzzyResult(
        preprocessed=preprocessed,
        top_match=top_match_str,
        top_score=round(top_score_raw / 100.0, 4),
        candidates=candidates,
    )


def routing_band(top_score: float, config: PipelineConfig) -> Literal["exact", "fuzzy", "llm", "review"]:
    """
    Map a similarity score to one of four routing decisions (confidence bands).

    The confidence band determines what happens next for a given raw category:
      - "exact"  (score == 1.0): perfect match — the raw title IS already a canonical
        O*NET title. No action needed.
      - "fuzzy"  (score >= 0.90): high confidence — auto-correct without asking the LLM.
        Zero token cost; handles Types 1–4 (typos, casing, seniority, noise).
      - "llm"    (0.70 <= score < 0.90): medium confidence — ask the LLM to verify
        semantic equivalence. Handles Types 5–7 (language, abbreviation, gender
        inflection) where strings look different but mean the same thing
        (e.g. "RRHH" → "Human Resources Managers").
      - "review" (score < 0.70): low confidence — the system never guesses.
        Row is flagged for human review; no correction is applied automatically.

    Args:
        top_score: The normalized similarity score (0.0–1.0) from FuzzyResult.top_score.
        config: PipelineConfig holding the high and low threshold values.

    Returns:
        One of the four routing labels as a plain string literal.
    """
    if top_score == 1.0:
        # Perfect score — the raw value is already an exact O*NET title; nothing to do.
        return "exact"
    if top_score >= config.high_threshold:
        # ≥ 0.90: high enough to auto-correct — no LLM call, no token cost.
        return "fuzzy"
    if top_score >= config.low_threshold:
        # 0.70–0.89: ask the LLM to verify semantic equivalence.
        return "llm"
    # < 0.70: too uncertain — escalate to human review queue, never auto-apply.
    return "review"
