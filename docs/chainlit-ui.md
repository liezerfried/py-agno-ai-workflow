# Chainlit UI & Demo Flow

## What the interface is

Not a conversational chatbot. The Chainlit UI is a shell that handles **file upload → pipeline trigger → result download**. The user never types job categories manually — they upload the Excel file that already contains them.

---

## End-to-end user flow

```
User opens Chainlit in browser
    ↓
on_chat_start fires → Chainlit renders a file upload widget in the chat
    ↓
User clicks the upload button, picks the .xlsx file, hits Send
    ↓
on_message fires → code receives the file path
    ↓
Workflow runs: IngestAgent → ValidatorAgent → MapperAgent → AuditWriter
    ↓
Chainlit streams each step as a visible message in the chat (collapsible)
    ↓
User downloads the corrected Excel with audit sheet
```

---

## What the user sees in the browser

```
┌─────────────────────────────────────────┐
│  Upload your Excel file with job cats   │
│  [ Choose file... ]  [ Send ]           │
├─────────────────────────────────────────┤
│  ✓ File received.                       │
│                                         │
│  ▶ IngestAgent        [reading...]      │
│  ▶ ValidatorAgent     [comparing...]    │
│  ▶ MapperAgent        [fuzzy+LLM...]    │
│  ▶ AuditWriter        [writing...]      │
│                                         │
│  Done. Download: [corrected.xlsx]       │
└─────────────────────────────────────────┘
```

Each `cl.Step` renders as a collapsible step — the user can expand any step to see what the agent did. This is the main reason Chainlit was chosen over Streamlit or Gradio.

---

## How the upload widget works

Chainlit's `AskFileMessage` renders a file picker + send button in the chat. No custom frontend needed.

```python
files = await cl.AskFileMessage(
    content="Upload your Excel file with job categories.",
    accept={"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"]},
    max_size_mb=10,
).send()
```

The file lands on disk. Chainlit gives back the local path. That path is passed directly to `IngestAgent`.

---

## How the pipeline connects

`app.py` (entry point) sits at the project root. It imports and calls the Workflow:

```
app.py
  └── on_chat_start  →  AskFileMessage (upload widget)
  └── on_message     →  normalization_workflow.run(file_path)
                              ├── IngestAgent
                              ├── ValidatorAgent
                              ├── MapperAgent
                              └── AuditWriter
                        → cl.File(corrected.xlsx) sent back to user
```

---

## `app.py` structure (sketch)

```python
import chainlit as cl
from workflows.normalization_workflow import run_workflow

@cl.on_chat_start
async def start():
    files = await cl.AskFileMessage(
        content="Upload your Excel file with job categories.",
        accept={"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"]},
        max_size_mb=10,
    ).send()

    cl.user_session.set("uploaded_file", files[0])
    await cl.Message("File received. Type 'run' to start normalization.").send()


@cl.on_message
async def main(message: cl.Message):
    uploaded = cl.user_session.get("uploaded_file")

    async with cl.Step(name="IngestAgent") as step:
        step.output = "Reading Excel and extracting unique categories..."

    async with cl.Step(name="ValidatorAgent") as step:
        step.output = "Comparing against 923 O*NET titles..."

    async with cl.Step(name="MapperAgent") as step:
        step.output = "Running rapidfuzz + LLM on anomalies..."

    async with cl.Step(name="AuditWriter") as step:
        step.output = "Writing corrected Excel + audit log..."

    output_path = "data/output_corrected.xlsx"
    await cl.Message(
        content="Done. Download your corrected file:",
        elements=[cl.File(name="corrected.xlsx", path=output_path)]
    ).send()
```

---

## How to run

```bash
chainlit run app.py
```

Opens at `http://localhost:8000`.

---

## How to prove the system works

### Stage 1 — manual demo
Run `chainlit run app.py`. Upload `data/sample_input.xlsx`. Verify the downloaded Excel has correct O\*NET titles and the audit sheet records confidence + method per row.

### Stage 2 — automated eval
```bash
pytest evaluation/
```
Asserts `precision ≥ 0.85` and `hallucination_rate ≤ 0.05` against `data/golden_dataset.csv`.

### Stage 3 — portfolio demo
Screen-record the full flow: upload dirty Excel → agents run visibly step by step → download clean file. That 60-second video is the proof of concept for any technical interview or portfolio.
