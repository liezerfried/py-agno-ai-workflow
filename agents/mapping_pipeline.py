from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from rapidfuzz import fuzz, process

from agents.pre_processor import normalize_title


class LLMFailureReason(str, Enum):
    no_match = "no_match"           # LLM ran but said not equivalent or returned null canonical_title
    hallucination = "hallucination" # LLM returned a title outside valid_categories_set or candidates
    error = "error"                 # exception raised during LLM call


@dataclass(frozen=True)
class PipelineConfig:
    top_n: int = 3
    high_threshold: float = 0.90
    low_threshold: float = 0.70


@dataclass
class FuzzyResult:
    preprocessed: str
    top_match: str | None
    top_score: float                      # 0.0–1.0
    candidates: list[tuple[str, float]]   # (title, normalized_score), up to top_n entries


def score(raw: str, valid_categories: list[str], config: PipelineConfig) -> FuzzyResult:
    preprocessed = normalize_title(raw)
    matches = process.extract(preprocessed, valid_categories, scorer=fuzz.WRatio, limit=config.top_n)

    if not matches:
        return FuzzyResult(preprocessed=preprocessed, top_match=None, top_score=0.0, candidates=[])

    top_match_str, top_score_raw, _ = matches[0]
    candidates = [(m[0], round(m[1] / 100.0, 4)) for m in matches]

    return FuzzyResult(
        preprocessed=preprocessed,
        top_match=top_match_str,
        top_score=round(top_score_raw / 100.0, 4),
        candidates=candidates,
    )


def routing_band(top_score: float, config: PipelineConfig) -> Literal["exact", "fuzzy", "llm", "review"]:
    if top_score == 1.0:
        return "exact"
    if top_score >= config.high_threshold:
        return "fuzzy"
    if top_score >= config.low_threshold:
        return "llm"
    return "review"