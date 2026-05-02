"""
Shared data contract passed from ValidatorAgent to MapperAgent.
Defines CategoryValidation — the per-category verdict of the validation step.
A consumer reads is_valid to decide whether correction is needed, and similarity_score
to decide which confidence band (auto-correct / LLM / human review) should apply.
"""
from __future__ import annotations

# Pydantic is a data-validation library. Classes that extend BaseModel have every
# field type-checked automatically — no manual validation code needed by callers.
from pydantic import BaseModel


class CategoryValidation(BaseModel):
    """
    The validation verdict for a single raw job title.

    Produced by ValidatorAgent and consumed by MapperAgent.

    If is_valid is True, the raw string is already an exact O*NET canonical title
    and no correction will be attempted. If False, MapperAgent will try to find
    the correct canonical title using rapidfuzz and/or the LLM.

    O*NET (Occupational Information Network) is the US Department of Labor database
    that provides 923 canonical job titles used as ground truth in this pipeline.
    A canonical title is an exact string from data/valid_categories.csv — the system
    never invents one; it only picks from that list.
    """

    # The original free-text job title exactly as read from the Excel file.
    raw: str

    # True  = raw is an exact O*NET title; no correction needed.
    # False = raw differs in some way and MapperAgent must attempt a correction.
    is_valid: bool

    # The most similar O*NET title found by rapidfuzz.
    # None when is_valid=True (no lookup was needed) or when no similarity was found at all.
    closest_match: str | None

    # Similarity between raw and closest_match, on a 0.0–1.0 scale.
    # 1.0 = perfect match; 0.0 = no similarity found.
    # MapperAgent uses this to choose the confidence band:
    #   ≥ 0.90 → auto-correct, 0.70–0.89 → ask LLM, < 0.70 → human review.
    similarity_score: float   # 0.0–1.0
