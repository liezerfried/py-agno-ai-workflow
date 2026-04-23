Check the current codebase against the hard invariants defined in CLAUDE.md.
For each invariant, report PASS, FAIL, or N/A (not yet implemented):

**Hard invariants:**
- [ ] Agent never invents a category — `corrected` is always an exact value from `valid_categories.csv`
- [ ] All agent output uses `output_schema` + Pydantic v2 — no free-text strings
- [ ] AuditWriter verifies every correction against the DB before writing Excel
- [ ] `rapidfuzz` runs before every LLM call — mandatory pre-filter, not optional
- [ ] `needs_review=True` cases go to the review queue — never silently applied
- [ ] All agents import model from `infrastructure/llm/provider.py` — never instantiated directly in agent files

**Confidence score thresholds (check MapperAgent):**
- [ ] score ≥ 0.90 → auto-correct, no LLM call
- [ ] score 0.70–0.89 → LLM evaluates, correction applied with needs_review=True
- [ ] score < 0.70 → needs_review=True, no correction applied, goes to review queue

**Output schema (check MapperOutput):**
- [ ] `original: str` — category as received in input
- [ ] `corrected: str` — exact match from valid_categories.csv
- [ ] `confidence: float` — value between 0 and 1
- [ ] `needs_review: bool`
- [ ] `method: str` — one of: rapidfuzz | llm | human
- [ ] `normalization_type: str` — one of: typo | synonym | language | format | abbreviation | case | unknown

For every FAIL: report the exact file and line number.
For every N/A: confirm whether it is expected given the current implementation stage.
