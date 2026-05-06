# Domain Context — py-agno-ai-workflow

## Purpose

AI pipeline that maps free-text job category strings to canonical O*NET occupation titles.
Input: Excel file with a job category column. Output: corrected Excel + audit trail.

## Primary goal

Portfolio project targeting recruiters and hiring managers in AI/ML engineering roles.
The project must demonstrate production-shaped code quality, not just working prompts.

## Deploy target

Hugging Face Spaces (free tier) for the Chainlit UI (`app.py`).
Dockerfile + docker-compose.yml for local reproducibility.
LLM in production: Groq (`llama-3.3-70b-versatile`) — already in the stack.
LLM in dev: LM Studio (local) — not included in the Docker image.

## Core terms

### Canonical title
An exact string from `data/valid_categories.csv`, derived from O*NET (US Dept. of Labor, 923 titles).
The system never invents a canonical title — it only selects from this fixed set.

### Correction
A mapping from a raw job category string to a canonical title.
A correction is only written to the output Excel if it passes the hallucination guard in AuditWriter.

### Review queue
The set of raw categories that could not be auto-corrected with sufficient confidence (score < 0.70).
These are written to the "Review Queue" sheet of the output Excel and must be resolved by a human.
Intentionally file-scoped: the review queue exists only within a single pipeline run output file.
Multi-tenant persistent review is out of scope for this project's portfolio goal.

### Pipeline run metrics
Aggregated statistics for a single pipeline run, persisted to `pipeline_runs` table in SQLite.
Fields: run_id, timestamp, filename, total_rows, corrected, review_queue, hallucinations, precision.
Accessible from the Chainlit UI via "Ver historial de runs" action at session start.

### Pipeline run
A single execution of the four-step workflow (Ingest → Validate → Map → Audit) for one uploaded file.
Produces one output Excel file and one set of AuditResult metrics.

### Confidence band
The decision rule that routes a category to one of three outcomes:
- ≥ 0.90 → auto-correct (rapidfuzz, no LLM call)
- 0.70–0.89 → LLM evaluates semantic equivalence
- < 0.70 → human review (system never guesses)

### Hallucination
A correction proposed by the LLM that names a string not present in `valid_categories.csv`.
Caught at AuditWriter (final guard) and routed to the review queue.