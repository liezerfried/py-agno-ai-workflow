# Onboarding Guide: py-agno-ai-workflow

## What this project does

Someone uploads an Excel file full of messy job titles — things like `"Dev Front"`, `"RRHH"`, `"Desarrolladora Backend"`. The system reads that file, figures out what each title *should* be, corrects it to an official job title from the US Department of Labor list (called O*NET), and gives back a clean Excel file plus a report.

That's it. One file in, one corrected file out.

---

## The two ways to run it

There are two entry points — two files that "start" the system:

| File | What it is | How to start it |
|------|-----------|-----------------|
| `app.py` | A chat-style web page where a user uploads a file and sees the results | `chainlit run app.py` |
| `agent_os.py` | A REST API — a URL you can call with code instead of a browser | `uvicorn agent_os:app` |

Both do the same work underneath. `app.py` is for humans. `agent_os.py` is for other programs talking to this one.

---

## The pipeline — 4 steps, in order

The core logic is always these four steps, one after the other. Think of it as an assembly line:

```
Excel file
    ↓
[1] IngestAgent       → reads the file, extracts the unique job titles
    ↓
[2] ValidatorAgent    → checks which titles are already correct, flags the rest
    ↓
[3] MapperAgent       → tries to fix each flagged title (fast match first, AI second)
    ↓
[4] AuditWriter       → writes the corrected Excel + a report
    ↓
Corrected file
```

Each step receives the *output of the previous step* as its input. That's the `previous_content` variable you see in `app.py` — it's just the JSON result of the last step, passed forward.

---

## Folder map — what lives where

```
agents/             The four pipeline steps, one file each
  ingest_agent.py     Step 1: reads Excel, finds unique job titles
  validator_agent.py  Step 2: checks which titles need fixing
  mapper_agent.py     Step 3: fixes titles (rapidfuzz + AI)
  audit_writer_agent.py  Step 4: writes the output file

infrastructure/     Shared plumbing used by all agents
  llm/provider.py     One function: get_model() — returns the AI model
  pipeline/session.py The shared "memory" passed between all 4 steps
  pipeline/step_io.py Helpers to serialize/deserialize data between steps

domain/
  onet.py             One function: is_valid_onet_title() — the single
                      source of truth for "is this an official title?"

data/
  valid_categories.csv  The 923 official O*NET job titles. The pipeline
                        never invents a title — it only picks from this list.

workflows/
  pipeline.py         PipelineError — the error type raised when a step fails
  normalization_workflow.py  Loads valid_categories.csv

tests/              Automated tests — run with: uv run pytest
  conftest.py         Shared test setup (fake Excel files, stub AI, etc.)

scripts/
  build_valid_categories.py  One-time script that built valid_categories.csv
                             from the original O*NET spreadsheet

app.py              Entry point 1: the Chainlit web UI
agent_os.py         Entry point 2: the REST API
```

---

## How data flows between steps

Each agent writes its result as a **JSON string**. The next agent reads that string and turns it back into a Python object. That's all `previous_content` is — a JSON string traveling down the assembly line.

```
IngestAgent writes:   IngestResult     → JSON string
ValidatorAgent reads: that JSON string → ValidatorResult → JSON string
MapperAgent reads:    that JSON string → MappingResult   → JSON string
AuditWriter reads:    that JSON string → writes the Excel file
```

The helpers `ok()` and `deserialize()` in `infrastructure/pipeline/step_io.py` do this wrapping/unwrapping so each agent doesn't have to repeat the same boilerplate.

---

## How the AI part works

MapperAgent uses **two layers** before calling AI — to save time and money:

1. **Pre-processor** (`agents/pre_processor.py`) — strips noise like `"Senior"`, `"- Remote"`, fixes casing. Free, instant.
2. **rapidfuzz** — measures how similar two strings are (0–100). If the match is close enough (≥ 90), it corrects automatically. No AI needed.
3. **AI (LLM)** — only called when the rapidfuzz score is 70–89. For ambiguous cases like language differences (`"Desarrollador"`) or abbreviations (`"RRHH"`).
4. **Human review queue** — when the score is below 70, the system never guesses. It flags the row for a human.

---

## Switching between local dev and production AI

There is one environment variable that controls which AI the pipeline uses:

```
LLM_PROVIDER=lmstudio   → uses your local machine (LM Studio must be running)
LLM_PROVIDER=groq       → uses Groq's cloud API (needs GROQ_API_KEY in .env)
```

The logic lives in one place: `infrastructure/llm/provider.py`. No agent file ever names a specific AI model directly.

---

## Common tasks — where to look

| I want to… | File to open |
|-----------|-------------|
| Understand what the web UI does | `app.py` |
| Understand the REST API | `agent_os.py` |
| Change how the Excel file is read | `agents/ingest_agent.py` |
| Change how titles are validated | `agents/validator_agent.py` |
| Change how the AI fixes titles | `agents/mapper_agent.py` |
| Change what goes into the output file | `agents/audit_writer_agent.py` |
| Switch the AI model or provider | `infrastructure/llm/provider.py` |
| Understand shared pipeline data | `infrastructure/pipeline/session.py` |
| Add or update official job titles | `data/valid_categories.csv` |
| Run the tests | `uv run pytest` in terminal |

---

## How to run it locally

```bash
# Install dependencies
uv sync

# Copy the example env file and fill in your keys
cp .env.example .env

# Start the web UI (option 1)
chainlit run app.py

# Start the REST API (option 2)
uvicorn agent_os:app --reload
```