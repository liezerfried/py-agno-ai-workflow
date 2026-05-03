# Chainlit UI & Demo Flow

## What the interface is

Not a conversational chatbot. The Chainlit UI is a file upload shell: the user uploads an
Excel file, the pipeline runs, and the corrected file is available for download.
The user never types job categories manually.

---

## End-to-end user flow

```
User opens http://localhost:8000
    ↓
on_chat_start fires → AskFileMessage renders an upload widget in the chat
    ↓
User uploads the .xlsx file
    ↓
app.py scans the column headers:
    - Single column     → uses it automatically
    - Multi-column, score ≥ 0.85 auto-detected  → uses best match
    - Multi-column, low score  → AskActionMessage renders column buttons for user to pick
    ↓
_run_pipeline_with_steps() runs each agent in a background thread (run_in_executor):
    ▶ IngestAgent       "Found N unique categories (M total rows)"
    ▶ ValidatorAgent    "X anomalies flagged — Y already valid"
    ▶ MapperAgent       "N auto-corrected — M via LLM — P to review queue"
    ▶ AuditWriter       "Corrected: N — Review queue: M — Precision: X%"
    ↓
Chainlit shows summary table + download link for corrected Excel
```

---

## What the user sees in the browser

```
┌─────────────────────────────────────────────────┐
│  Upload an Excel file (.xlsx) with job           │
│  categories to normalize.                        │
│  [ Choose file... ]  [ Send ]                   │
├─────────────────────────────────────────────────┤
│  Auto-detected job category column: "Job Title" │
│                                                 │
│  ▼ IngestAgent                                  │
│    Found 47 unique categories (312 total rows)  │
│  ▼ ValidatorAgent                               │
│    12 anomalies flagged — 35 already valid      │
│  ▼ MapperAgent                                  │
│    8 auto-corrected — 3 via LLM — 1 to review  │
│  ▼ AuditWriter                                  │
│    Corrected: 11 — Review queue: 1 — Precision: 91.67% │
│                                                 │
│  Pipeline complete.                             │
│  | Corrected      | 11  |                       │
│  | Review queue   | 1   |                       │
│  | Precision      | 91% |                       │
│                                                 │
│  [Download corrected file]                      │
└─────────────────────────────────────────────────┘
```

Each `cl.Step` renders as a collapsible panel — the user can expand any step to see the
detailed output. This is why Chainlit was chosen over Streamlit or Gradio.

---

## How column detection works

```python
# app.py — on_chat_start
scan = scan_headers(uploaded.path)   # reads only the header row

if len(scan.column_names) == 1:
    target_column = scan.column_names[0]   # single column, no ambiguity

elif detect_score >= 0.85:
    target_column = best_col               # auto-detected with high confidence

else:
    # Low confidence — show buttons and let the user pick
    res = await cl.AskActionMessage(
        content="Select the column that contains job categories:",
        actions=[cl.Action(name="col", payload={"value": col}, label=col)
                 for col in scan.column_names],
    ).send()
    target_column = res["payload"]["value"]
```

---

## How the pipeline connects to the UI

Each executor is dispatched to a background thread via `run_in_executor` so the async
event loop stays free between steps (allowing Chainlit to render UI updates).

```python
# app.py — _run_pipeline_with_steps()
executors = [
    ("IngestAgent",    ingest_executor),
    ("ValidatorAgent", validator_executor),
    ("MapperAgent",    mapper_executor),
    ("AuditWriter",    audit_executor),
]

previous_content: str | None = None

for name, executor_fn in executors:
    async with cl.Step(name=name) as step:
        step.output = "Running…"
        step_input = StepInput(previous_step_content=previous_content)

        output = await loop.run_in_executor(
            None, partial(executor_fn, step_input, session_state)
        )

        if not output.success:
            step.output = f"Failed: {output.content}"
            raise PipelineError(name, output.content)

        previous_content = output.content
        step.output = _step_summary(name, previous_content)  # human-readable summary
```

`_step_summary()` deserializes each agent's JSON output and returns a short status line
specific to that agent (e.g. for `MapperAgent`: `"8 auto-corrected — 3 via LLM — 1 to review queue"`).

---

## How to run

```bash
chainlit run app.py
# → opens at http://localhost:8000
```

---

## How to prove the system works

### Manual demo

1. Run `chainlit run app.py`
2. Upload `tests/fixtures/golden_input.xlsx` (or any Excel with job titles)
3. Watch each agent step appear in real time
4. Download the corrected Excel — verify it has the "Corrected" and "Review Queue" sheets
5. Check that every value in "Corrected" is a valid O*NET title from `data/valid_categories.csv`

### Automated tests

```bash
uv run pytest tests/test_integration_golden_path.py
```

Asserts: no hallucinations, both output sheets present, precision metrics within thresholds.
