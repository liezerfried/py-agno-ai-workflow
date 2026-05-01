from __future__ import annotations

from pydantic import BaseModel


class CategoryValidation(BaseModel):
    raw: str
    is_valid: bool
    closest_match: str | None
    similarity_score: float   # 0.0–1.0
