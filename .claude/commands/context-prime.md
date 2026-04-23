Load context before a complex task. Read the following documents in order:

1. CLAUDE.md — architecture, hard invariants, decisions already made
2. docs/04-agent-orchestration-and-project-design.md — agent design and pipeline decisions
3. docs/07-implementation-and-validation-strategy.md — detection layers, evaluation, golden dataset
4. $ARGUMENTS — the specific document for the area I am about to work on

After reading all four, produce a context summary with exactly these sections:

**Constraints that apply to this task**
List every hard invariant, threshold, or design decision from CLAUDE.md that is
directly relevant to what I am about to do. Be specific — no generic reminders.

**APIs to verify before writing code**
List every library from the stack that I will touch in this task.
For each one, state: look up via Context7 before writing any call.

**What must NOT change**
List any decisions already made (from CLAUDE.md or docs/09) that this task
must not reopen or contradict.

Then ask me: what specifically do you want to build?
