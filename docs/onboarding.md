# Onboarding Guide: py-agno-ai-workflow

## What this project does

Someone uploads an Excel file full of messy job titles — things like `"Dev Front"`, `"RRHH"`, `"Desarrolladora Backend"`. The system reads that file, figures out what each title *should* be, corrects it to an official job title from the US Department of Labor list (called O*NET), and gives back a clean Excel file plus a full audit trail.

One file in, one corrected file out.

---

## The two entry points

| File | What it is | How to start |
|------|-----------|--------------|
| `app.py` | Chainlit web UI — user uploads file, sees per-agent progress in real time | `chainlit run app.py` |
| `agent_os.py` | REST API via AgentOS — call the pipeline from code | `uvicorn agent_os:app --reload` |

Both run the same 4-step pipeline underneath. `app.py` is for humans; `agent_os.py` is for other systems.

---

## The pipeline — 4 steps, in order

```
Excel file
    ↓
[1] IngestAgent         → reads the file, extracts the unique job titles
    ↓
[2] ValidatorAgent      → checks which titles are already correct, flags the rest
    ↓
[3] MapperAgent         → tries to fix each flagged title (rapidfuzz first, LLM second)
    ↓
[4] AuditWriter         → writes the corrected Excel + audit log + review queue sheet
    ↓
Corrected file
```

Each step receives the *output of the previous step* as its input — a JSON string passed forward via `StepOutput.content`.

---

## Folder map — what lives where

```
agents/
  ingest_agent.py         Step 1: reads Excel, finds unique job titles
  validator_agent.py      Step 2: checks which titles need fixing (rapidfuzz)
  mapper_agent.py         Step 3: fixes titles — rapidfuzz, then LLM, then review queue
  mapping_pipeline.py     Scoring logic used by MapperAgent: score(), routing_band()
  pre_processor.py        Text normalizer (no LLM): strips seniority, fixes casing, removes noise
  translator_agent.py     Sub-agent of MapperAgent: translates non-English or expands abbreviations
  audit_writer_agent.py   Step 4: writes corrected Excel + audit log + review queue

infrastructure/
  llm/provider.py         One function: get_model() — returns the LLM; all agents import from here
  pipeline/contracts.py   Shared Pydantic types passed between pipeline steps
  pipeline/session.py     PipelineSession: typed wrapper around the session_state dict
  pipeline/step_io.py     ok(), fail(), deserialize() — helpers that wrap/unwrap JSON between steps

domain/
  onet.py                 is_valid_onet_title() — single source of truth for "is this a valid O*NET title?"

workflows/
  normalization_workflow.py   load_valid_categories() — loads valid_categories.csv
  pipeline.py                 PipelineError — the error type raised when a step fails

data/
  valid_categories.csv    The 923 official O*NET job titles; the pipeline never invents a title
  raw/                    Original O*NET spreadsheet from US Dept of Labor

tests/
  conftest.py             Shared fixtures: fake Excel files, stub LLM agents
  domain/                 Tests for domain/onet.py
  test_pre_processor.py   Tests for text normalization
  test_validator.py       Tests for ValidatorAgent
  test_mapper.py          Tests for MapperAgent (including TranslatorAgent sub-agent)
  test_mapping_pipeline.py    Tests for score() and routing_band()
  test_translator.py      Tests for TranslatorAgent in isolation
  test_column_detection.py    Tests for auto-detecting the job column in Excel
  test_integration_pipeline.py    End-to-end: all 4 agents connected
  test_integration_golden_path.py Pipeline run over golden_input.xlsx static fixture
  test_integration_seams.py   Serialization/deserialization between agent steps
  test_smoke.py           Import-time sanity check — project starts without errors

scripts/
  build_valid_categories.py   One-time: generates valid_categories.csv from O*NET spreadsheet
  audit_collisions.py         Utility: checks for fuzzy collisions in the valid categories list
  generate_test_files.py      Utility: generates sample Excel files for testing

app.py          Entry point 1: Chainlit web UI
agent_os.py     Entry point 2: REST API via AgentOS
```

---

## How data flows between steps

Each agent serializes its result as a JSON string. The next agent deserializes it. That's all `StepOutput.content` is — a JSON string traveling down the assembly line.

```
IngestAgent    →  IngestResult     → JSON
ValidatorAgent →  ValidatorResult  → JSON
MapperAgent    →  MappingResult    → JSON
AuditWriter    →  AuditResult      (writes Excel, no further step)
```

The helpers `ok()`, `fail()`, and `deserialize()` in `infrastructure/pipeline/step_io.py` handle this so each agent just calls `ok(result)` or `deserialize(content, ModelClass)`.

---

## Which agents actually call the LLM

Not all agents are LLM agents — three of the four are pure Python wrapped in Agno `Step`:

| Agent | Type | Uses LLM |
|-------|------|-----------|
| `IngestAgent` | Python (openpyxl) wrapped in Step | No |
| `ValidatorAgent` | Python (rapidfuzz) wrapped in Step | No |
| `MapperAgent` | Agno `Agent` with `output_schema=SemanticMatch` | Yes — only in the 0.70–0.89 band |
| `AuditWriter` | Python (openpyxl) wrapped in Step | No |

The LLM enters only when the problem is semantic or linguistic and no algorithm is sufficient: translations, abbreviations, gender inflection.

`TranslatorAgent` is a sub-agent called internally by `MapperAgent` — it is not a pipeline step. It runs when a title scores < 0.70 on first pass, attempts to normalize it (translate/expand), then re-scores. If the translated form scores higher, it proceeds; otherwise the row goes to the review queue.

---

## How the AI routing works

MapperAgent uses two layers before calling the LLM:

1. **pre_processor.py** — strips noise (`"Senior"`, `"- Remote"`, `"(Contract)"`), fixes casing. Zero cost.
2. **rapidfuzz** — measures string similarity (0–100 scale). If ≥ 90: auto-corrects with no LLM call.
3. **TranslatorAgent** — if score < 0.70, tries to normalize via LLM translation/abbreviation expansion, then re-scores.
4. **MapperAgent LLM** — if score is 0.70–0.89 (or post-translation), the LLM evaluates semantic equivalence against the top-3 candidates.
5. **Review queue** — score < 0.70 after all layers → never guesses, flags for human.

```
confidence ≥ 0.90   →  auto-correct  (no LLM, zero token cost)
0.70–0.89           →  LLM evaluates semantic equivalence
< 0.70              →  human-in-the-loop (system never guesses)
```

---

## Switching between local dev and production LLM

One environment variable controls the entire LLM routing. No agent file ever names a model directly — all import `get_model()` from `infrastructure/llm/provider.py`.

```
LLM_PROVIDER=lmstudio  →  uses LM Studio on localhost (free, no API key)
LLM_PROVIDER=groq      →  uses Groq cloud with llama-3.3-70b-versatile (needs GROQ_API_KEY)
```

Optional overrides:
- `LMSTUDIO_MODEL` — local model name (default: `qwen/qwen3.5-9b`)
- `GROQ_MODEL` — Groq model (default: `llama-3.3-70b-versatile`)

---

## The `infrastructure/` layer — why it exists

`infrastructure/` is the shared technical plumbing that all agents use, so they don't repeat boilerplate:

| File | Problem it solves |
|------|-------------------|
| `llm/provider.py` | Single place to switch LLM providers — agents never instantiate models directly |
| `pipeline/contracts.py` | Shared Pydantic types so ValidatorAgent and MapperAgent have a strict contract |
| `pipeline/session.py` | Typed wrapper around `session_state` dict — avoids scattered `session_state["key"]` calls |
| `pipeline/step_io.py` | `ok(result)` / `deserialize(content, T)` — each agent's boundary with the Agno Workflow |

`infrastructure/pipeline/` is NOT the pipeline itself. The actual pipeline is the Agno Workflow in `workflows/`. The helpers here just make each step's code cleaner.

---

## The `domain/` layer

`domain/onet.py` contains one function:

```python
def is_valid_onet_title(title: str | None, valid_categories_set: set[str]) -> bool:
    if title is None:
        return False
    return title in valid_categories_set
```

It is called by `MapperAgent` (before accepting an LLM suggestion) and `AuditWriter` (before writing any correction). This is the hard invariant: **the system never writes a title that isn't in this set**. Centralizing the check means one change covers both call sites.

---

## The test suite

Run all tests:
```bash
uv run pytest
```

Skip tests that require a live LLM:
```bash
uv run pytest -m "not real_llm"
```

| Test file | What it covers |
|-----------|----------------|
| `tests/domain/test_onet.py` | `is_valid_onet_title()` contract |
| `test_pre_processor.py` | Seniority stripping, casing, noise removal |
| `test_validator.py` | ValidatorAgent classifies valid vs. anomaly correctly |
| `test_mapper.py` | MapperAgent routing decisions per confidence band |
| `test_mapping_pipeline.py` | `score()` and `routing_band()` return expected values |
| `test_translator.py` | TranslatorAgent normalizes language/abbreviation/gender |
| `test_column_detection.py` | Auto-detection of the job column in Excel files |
| `test_integration_pipeline.py` | All 4 agents wired end-to-end |
| `test_integration_golden_path.py` | Full pipeline on static `golden_input.xlsx` |
| `test_integration_seams.py` | JSON serialization/deserialization between steps |
| `test_smoke.py` | Project imports without errors |

`tests/fixtures/golden_input.xlsx` is a static Excel with 4 rows that cover the key cases: already-valid title, seniority strip, typo, and abbreviation. The golden path test runs the whole pipeline and asserts there are no hallucinations and every correction is a valid O*NET title.

---

## How to run locally

```bash
# Install dependencies
uv sync

# Copy and fill in environment variables
cp .env.example .env   # set LLM_PROVIDER and GROQ_API_KEY if using Groq

# Start the web UI
chainlit run app.py
# → opens at http://localhost:8000

# Or start the REST API
uvicorn agent_os:app --reload
```

---

## Common tasks — where to look

| I want to… | File |
|-----------|------|
| Change how Excel is read | `agents/ingest_agent.py` |
| Change validation logic | `agents/validator_agent.py` |
| Change how titles are fixed | `agents/mapper_agent.py` |
| Change what goes into the output Excel | `agents/audit_writer_agent.py` |
| Switch the LLM or provider | `infrastructure/llm/provider.py` |
| Understand how steps share state | `infrastructure/pipeline/session.py` |
| Add or update valid O*NET titles | `data/valid_categories.csv` |
| Run the tests | `uv run pytest` |
| Regenerate valid_categories.csv | `uv run python scripts/build_valid_categories.py` |
