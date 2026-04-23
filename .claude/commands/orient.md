Read the current state of the repository. Check which files exist under src/, agents/,
workflows/, infrastructure/, tests/, scripts/, data/, and api/. Then read CLAUDE.md.

Report the following, in this exact order:

**1. What is already implemented**
List every file that exists (outside docs/, .git/, and .claude/) with a one-line summary
of what it does. If nothing exists yet beyond docs and scripts, say so explicitly.

**2. What is missing**
Compare against the 4-agent architecture defined in CLAUDE.md:
- IngestAgent
- ValidatorAgent
- MapperAgent
- AuditWriter

For each agent, state: NOT STARTED / IN PROGRESS / DONE.
Also check for: infrastructure/llm/provider.py, agents/pre_processor.py,
data/valid_categories.csv, pyproject.toml, .env.example, Chainlit UI,
FastAPI layer (api/routes.py), normalization_workflow.py, tests/.

**3. The single next step**
Name exactly one thing to work on next. Include:
- The file to create or edit
- What it should contain (one paragraph)
- Which hard invariant from CLAUDE.md is most relevant to this step

Do not suggest more than one next step. Do not give generic advice.
