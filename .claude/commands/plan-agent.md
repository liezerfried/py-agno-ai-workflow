Do not write any code. This is a planning session only.

I am about to design and implement: $ARGUMENTS

Read CLAUDE.md and docs/04-agent-orchestration-and-project-design.md before answering.
Use the Context7 MCP tool to look up current Agno API signatures for Agent, Workflow,
Step, and output_schema before proposing any structure.

Produce a plan with these sections:

**1. Single responsibility**
One sentence. What does this agent do and nothing else?

**2. Position in the pipeline**
What does it receive from the previous step? What does it hand off to the next?

**3. Input and output models**
Define both as Pydantic v2 models (field names, types, and validators).
output_schema must be a Pydantic model — never a free-text string.

**4. Normalization types handled**
Which of the 7 types (from CLAUDE.md) does this agent deal with?
Which are handled by pre_processor.py before reaching this agent?

**5. Confidence scoring** (only for MapperAgent)
Map the three thresholds to concrete actions this agent takes.

**6. Hard invariants that apply**
List every invariant from CLAUDE.md that constrains this agent's design.
For each one, explain how the design respects it.

**7. What could go wrong**
Two or three failure modes specific to this agent. How does the design prevent each?

Wait for explicit approval before writing any code.
