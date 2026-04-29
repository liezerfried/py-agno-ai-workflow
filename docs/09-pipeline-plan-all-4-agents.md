# Pipeline Plan — All 4 Agents + Workflow

## Preamble: confirmed API signatures

From the live Agno docs:

```python
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.steps import Steps
from agno.workflow.workflow import Workflow
from agno.agent import Agent

# Step accepts agent=, team=, or executor= (fn: StepInput → StepOutput)
Step(name="...", agent=my_agent, description="...")
Step(name="...", executor=my_fn, description="...")  # pure-Python step

# Steps groups a named sequence; Workflow holds Steps
Steps(name="...", steps=[step1, step2, ...])
Workflow(name="...", steps=[steps_seq], db=..., session_state={...})

# output_schema on Agent — LLM must return JSON conforming to the model
Agent(name="...", model=get_model(), output_schema=MyPydanticModel, instructions="...")

# Access typed output after agent.run():
result = agent.run(prompt)
typed: MyPydanticModel = result.content

# Inter-step data: StepInput.previous_step_content is a plain string
# Convention: each step serializes its Pydantic output with .model_dump_json()
# and the next step parses it with MyModel.model_validate_json(step_input.previous_step_content)
```

**Critical finding:** `previous_step_content` is a `str`, not a typed object. All typed handoffs between steps require explicit `model_dump_json()` / `model_validate_json()` calls.

---

## Agent 1 — IngestAgent

### 1. Single responsibility

Reads the Excel file, extracts the unique non-null values from the target column, and returns them as a typed `IngestResult`. Nothing else.

### 2. Position in the pipeline

Receives: `(file_path: str, target_column: str)` from the Workflow caller.  
Hands off: `IngestResult` serialized to JSON → `ValidatorAgent` via `previous_step_content`.

### 3. Input and output models

```python
# Already exists in agents/ingest_agent.py — no changes needed
class IngestResult(BaseModel):
    file_path: str
    target_column: str
    raw_categories: list[str]   # unique, sorted, stripped
    total_rows: int
```

No Agno `output_schema` here — the output is produced by deterministic Python code, not an LLM. The invariant "never free-text strings" is satisfied because the executor returns `StepOutput(content=result.model_dump_json())`.

The Step is an executor function, not an `Agent`:

```python
def ingest_executor(step_input: StepInput) -> StepOutput:
    # parse file_path + target_column from step_input.input (JSON string)
    params = IngestParams.model_validate_json(step_input.input)
    result = extract_categories(params.file_path, params.target_column)
    return StepOutput(content=result.model_dump_json())

ingest_step = Step(name="ingest", executor=ingest_executor)
```

`IngestParams` (internal, not an output schema):

```python
class IngestParams(BaseModel):
    file_path: str
    target_column: str
```

### 4. Normalization types handled

None. IngestAgent reads raw values verbatim — intentionally. Normalization starts in ValidatorAgent (rapidfuzz) and MapperAgent (pre_processor + LLM). Touching the data here would make the audit trail lie.

### 5. Confidence scoring

N/A.

### 6. Hard invariants

| Invariant | How respected |
|-----------|---------------|
| Output is Pydantic v2, never free-text | `StepOutput.content = IngestResult.model_dump_json()` |
| Never instantiate LLM in agent file | No model used — pure openpyxl |
| rapidfuzz before LLM | N/A — no fuzzy or LLM work here |

### 7. What could go wrong

- **Column not found in file.** Current code raises `ValueError`. The executor should catch this and return `StepOutput(content=..., success=False)` so the Workflow stops cleanly rather than crashing with an unhandled exception.
- **Excel has merged cells or multiple header rows.** `openpyxl` reads the literal cell value at row 1. A misaligned header silently picks the wrong column. Design prevention: `scan_headers()` already exists — the Workflow caller should invoke it and surface column names to the user before starting the pipeline (Chainlit step).

---

## Agent 2 — ValidatorAgent

### 1. Single responsibility

Compares each raw category against `valid_categories.csv` using rapidfuzz and flags every one that is not an exact match, returning a per-category validation result.

### 2. Position in the pipeline

Receives: `IngestResult` (deserialized from `previous_step_content`).  
Hands off: `ValidatorResult` → `MapperAgent`.

### 3. Input and output models

```python
class CategoryValidation(BaseModel):
    raw: str
    is_valid: bool                  # True = exact match in valid_categories.csv
    closest_match: str | None       # best rapidfuzz candidate, None if is_valid=True
    similarity_score: float         # 0.0–1.0; 1.0 if exact match

class ValidatorResult(BaseModel):
    validations: list[CategoryValidation]
    valid_count: int
    anomaly_count: int
    anomalies: list[CategoryValidation]  # subset where is_valid=False, pre-filtered
```

`anomalies` is a pre-computed convenience field — `MapperAgent` only processes anomalies, so filtering here keeps the mapper simple and auditable.

Again, no LLM → executor function, not an Agno Agent with a model.

### 4. Normalization types handled

ValidatorAgent itself handles **none of the 7 types** — it only classifies. It runs rapidfuzz to compute similarity but does not modify the raw value. The score is a diagnostic, not a correction. Classification result (`is_valid`, `similarity_score`) informs MapperAgent which normalization path to take.

### 5. Confidence scoring

N/A. Thresholds are applied by MapperAgent, not here. ValidatorAgent stores the raw score and lets the mapper decide.

### 6. Hard invariants

| Invariant | How respected |
|-----------|---------------|
| Agent never invents a category | ValidatorAgent does not write `corrected` — it only reads the CSV and computes scores |
| Output is Pydantic v2 | `StepOutput.content = ValidatorResult.model_dump_json()` |
| rapidfuzz before LLM | rapidfuzz runs here, before MapperAgent ever sees the data |
| No model instantiation in agent file | Pure Python; no `get_model()` call |

### 7. What could go wrong

- **`valid_categories.csv` not found at runtime.** The executor should fail fast with a clear error rather than returning empty anomalies (which would make everything look valid). Load and validate the file at module import time, not inside the executor.
- **Encoding mismatch between Excel values and CSV.** Accented characters (`é`, `ñ`) that were read with one encoding might not match CSV entries. Prevention: normalize both sides to NFKD + lowercase before comparison (same transform used in `pre_processor.normalize_title()`). Document this normalization step explicitly.

---

## Agent 3 — MapperAgent

### 1. Single responsibility

For each anomaly from ValidatorAgent: apply `pre_processor.normalize_title()`, run rapidfuzz, apply the three confidence thresholds, call the LLM only for the 0.70–0.89 band, and return a typed `MappingResult`.

### 2. Position in the pipeline

Receives: `ValidatorResult` (anomalies list) from `previous_step_content`.  
Hands off: `MappingResult` → `AuditWriter`.

### 3. Input and output models

```python
from typing import Literal

class MappingDecision(BaseModel):
    raw: str
    preprocessed: str               # output of normalize_title(raw) — logged for audit
    corrected: str | None           # None when needs_review=True; must be exact CSV value
    confidence: float
    method: Literal["exact", "fuzzy", "llm", "needs_review"]
    needs_review: bool

class MappingResult(BaseModel):
    decisions: list[MappingDecision]
    auto_corrected_count: int       # method in {"exact", "fuzzy"}
    llm_evaluated_count: int        # method == "llm"
    needs_review_count: int         # needs_review=True
```

The LLM output schema (used only inside the 0.70–0.89 call):

```python
class SemanticMatch(BaseModel):
    is_equivalent: bool
    canonical_title: str | None     # must be exact CSV value; None if not equivalent
    reasoning: str                  # one sentence — required for audit trail
```

`mapper_agent` is the only real Agno Agent with a model:

```python
mapper_agent = Agent(
    name="MapperAgent",
    model=get_model(),
    output_schema=SemanticMatch,
    instructions=[
        "You receive a job title and a candidate canonical O*NET occupation title.",
        "Decide if they are semantically equivalent (same role, different words).",
        "canonical_title must be the exact candidate string if equivalent, else null.",
        "Never invent a title not in the candidate list.",
    ],
)
```

The Step is an **executor function** that calls `mapper_agent.run()` internally only when needed:

```python
def mapper_executor(step_input: StepInput) -> StepOutput:
    validator_result = ValidatorResult.model_validate_json(step_input.previous_step_content)
    decisions = []
    for anomaly in validator_result.anomalies:
        decision = _decide(anomaly)   # contains all 3 threshold branches
        decisions.append(decision)
    result = MappingResult(decisions=decisions, ...)
    return StepOutput(content=result.model_dump_json())
```

### 4. Normalization types handled

| Type | Handled by | Stage |
|------|-----------|-------|
| 1 — Typo | rapidfuzz | Inside mapper_executor, score ≥ 0.90 |
| 2 — Casing/punctuation | `pre_processor.normalize_title()` | Before rapidfuzz |
| 3 — Seniority stripping | `pre_processor.normalize_title()` | Before rapidfuzz |
| 4 — Noise/context | `pre_processor.normalize_title()` | Before rapidfuzz |
| 5 — Language | LLM (`mapper_agent`) | 0.70–0.89 band |
| 6 — Abbreviation/synonym | LLM (`mapper_agent`) | 0.70–0.89 band |
| 7 — Gender inflection | LLM (`mapper_agent`) | 0.70–0.89 band |

### 5. Confidence scoring

| Score | Action | `method` | `needs_review` | LLM call? |
|-------|--------|----------|----------------|-----------|
| = 1.0 | Exact match to CSV entry | `"exact"` | `False` | No |
| ≥ 0.90 | Auto-correct to rapidfuzz top match | `"fuzzy"` | `False` | No |
| 0.70–0.89 | Call `mapper_agent.run()` with `SemanticMatch` schema. If `is_equivalent=True`, use `canonical_title`. If False, set `needs_review=True` | `"llm"` or `"needs_review"` | Depends on LLM answer | Yes |
| < 0.70 | Escalate immediately, no LLM | `"needs_review"` | `True` | No |

Note: if rapidfuzz finds an exact string match (score = 1.0), `method="exact"` — distinguished from fuzzy for the audit log.

### 6. Hard invariants

| Invariant | How respected |
|-----------|---------------|
| Agent never invents a category | `corrected` is only set to the rapidfuzz `top_match` (which came from the CSV) or to `SemanticMatch.canonical_title` (which the LLM prompt constrains to the candidate string). AuditWriter re-verifies this. |
| output_schema + Pydantic v2 | `MappingResult` for the step; `SemanticMatch` for each LLM call |
| rapidfuzz before every LLM call | Enforced by the executor's control flow — the LLM branch is unreachable if rapidfuzz score < 0.70 or ≥ 0.90 |
| needs_review=True → review queue | `corrected=None` when `needs_review=True`; AuditWriter reads this flag and routes accordingly |
| Model via get_model() | `mapper_agent = Agent(model=get_model(), ...)` |

### 7. What could go wrong

- **LLM hallucinates a canonical title not in the CSV.** AuditWriter's DB verification catches this, but MapperAgent can also guard: after receiving `SemanticMatch`, check that `canonical_title` is in the loaded valid categories set before accepting it. If it fails, treat as `needs_review`.
- **Pre-processor over-normalizes and loses signal.** E.g., stripping "Senior" from "Senior Data Scientist" leaves "Data Scientist" which correctly maps. But stripping from "Senior Partner" leaves "Partner" which is ambiguous. Prevention: log `preprocessed` alongside `raw` in `MappingDecision` — the audit trail exposes over-normalization.
- **LLM timeout or API error in the 0.70–0.89 band.** The executor must catch exceptions from `mapper_agent.run()` and fall back to `needs_review=True` rather than crashing the whole workflow.

---

## Agent 4 — AuditWriter

### 1. Single responsibility

Verifies every proposed correction against `valid_categories.csv` via DuckDB, writes the corrected Excel (with an audit sheet and a review-queue sheet), and returns a typed `AuditResult`.

### 2. Position in the pipeline

Receives: `MappingResult` from `previous_step_content` + original `file_path` (from Workflow `session_state`).  
Hands off: `AuditResult` to the Workflow caller (Chainlit).

### 3. Input and output models

```python
class AuditResult(BaseModel):
    output_path: str
    corrected_count: int
    review_queue_count: int
    hallucination_count: int        # corrections rejected because not in CSV
    precision: float | None         # corrected / (corrected + hallucination), None if no corrections
```

No LLM → executor function.

### 4. Normalization types handled

None. AuditWriter does not modify categories. It only applies corrections that MapperAgent already decided.

### 5. Confidence scoring

N/A.

### 6. Hard invariants

| Invariant | How respected |
|-----------|---------------|
| AuditWriter verifies every correction against DB before writing | DuckDB query: `SELECT COUNT(*) FROM read_csv('data/valid_categories.csv') WHERE title = ?` for each `MappingDecision.corrected` |
| needs_review=True → review queue | Any decision with `needs_review=True` goes to the review queue sheet, never to the corrected column |
| Output is Pydantic v2 | `StepOutput.content = AuditResult.model_dump_json()` |
| hallucination detected → never silently applied | If DuckDB returns 0 for a proposed correction, it is rejected: `corrected` is set to `None`, `hallucination_count` incremented, row goes to review queue |

### 7. What could go wrong

- **Output Excel path collision.** If the user runs the pipeline twice on the same file, the second run overwrites the first output. Prevention: generate the output filename with a timestamp suffix (`corrected_20260428_143000.xlsx`).
- **DuckDB reads a stale CSV.** If `valid_categories.csv` is updated between steps (unlikely but possible in dev), the validation DB may disagree with the one ValidatorAgent used. Prevention: load the CSV once at Workflow startup and store the valid set in `session_state` — all agents read from the same snapshot.

---

## Workflow wiring

**File:** `workflows/normalization_workflow.py`

```
Workflow(session_state={...})
└── Steps("normalization")
    ├── Step("ingest",    executor=ingest_executor)
    ├── Step("validate",  executor=validator_executor)
    ├── Step("map",       executor=mapper_executor)      # calls mapper_agent internally
    └── Step("audit",     executor=audit_executor)
```

### session_state usage

| Key | Written by | Read by |
|-----|-----------|---------|
| `file_path` | Workflow caller | AuditWriter executor |
| `valid_categories_set` | Workflow init | ValidatorAgent, MapperAgent, AuditWriter |

Loading `valid_categories.csv` once into `session_state["valid_categories_set"]` at startup satisfies the stale-data concern and avoids 4 separate file reads.

### Data flow (typed)

```
Workflow.run(input=IngestParams.model_dump_json())
  → ingest_executor   → StepOutput(IngestResult.model_dump_json())
  → validator_executor → StepOutput(ValidatorResult.model_dump_json())
  → mapper_executor   → StepOutput(MappingResult.model_dump_json())
  → audit_executor    → StepOutput(AuditResult.model_dump_json())
  → WorkflowRunOutput (final response to Chainlit)
```

---

## Open questions before coding

1. **Does MapperAgent need `agno.agent.Agent` or is it acceptable for it to be an executor function that instantiates Agent internally?** The current plan uses both (executor wraps Agent). This is intentional — should be confirmed.

2. **Where does `file_path` enter the Workflow?** Options: (a) as the initial `input` JSON, (b) as a Workflow `session_state` key. Plan assumes (a) parsed by `ingest_executor` + stored to `session_state` for `audit_executor`.

3. **Chainlit integration point**: does Chainlit call `workflow.arun()` or `workflow.print_response()`? Async is preferred for streaming step updates. Needs a separate design decision before the UI layer is built.

4. **Review queue format**: is it a separate Excel sheet, a separate file, or a DB table? The plan assumes a second sheet (`_review_queue`) in the same output workbook. Confirm before implementing `AuditWriter`.

---

## Summary table

| Agent | Type | LLM | Input source | Output | Hard constraint |
|-------|------|-----|--------------|--------|-----------------|
| IngestAgent | Executor function | No | file_path, target_column | IngestResult | Read verbatim, no normalization |
| ValidatorAgent | Executor function | No | IngestResult.raw_categories | ValidatorResult | rapidfuzz scoring only, no LLM |
| MapperAgent | Executor + Agent | Yes (0.70–0.89 only) | ValidatorResult.anomalies | MappingResult | Never invent; pre-filter with rapidfuzz |
| AuditWriter | Executor function | No | MappingResult + file_path | AuditResult | Verify each correction vs. CSV via DuckDB |
