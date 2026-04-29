# Agno Documentation Summary (Context7)

This summary is based on Context7 extracts from the official Agno docs. It is organized by module so you can navigate the system quickly, choose the right patterns, and implement high-quality agents.

## Best Format Choice
- Markdown is the best choice for this summary because it is readable, searchable, and easy to extend with links, code snippets, and headings.

## Doc References (Context7)

| Module | Key Docs |
| --- | --- |
| Agents | https://github.com/agno-agi/docs/blob/main/examples/agents/overview.mdx ; https://github.com/agno-agi/docs/blob/main/examples/basics/agent-with-typed-input-output.mdx ; https://github.com/agno-agi/docs/blob/main/examples/agent-os/os-config/basic.mdx |
| Teams | https://github.com/agno-agi/docs/blob/main/teams/overview.mdx ; https://github.com/agno-agi/docs/blob/main/examples/teams/basics/nested-teams.mdx ; https://github.com/agno-agi/docs/blob/main/teams/usage/streaming.mdx |
| Workflows | https://github.com/agno-agi/docs/blob/main/workflows/workflow-patterns/nested-workflow.mdx ; https://github.com/agno-agi/docs/blob/main/examples/workflows/basic-workflows/sequence-of-steps/workflow-with-file-input.mdx ; https://github.com/agno-agi/docs/blob/main/other/v2-changelog.mdx |
| Tools | https://github.com/agno-agi/docs/blob/main/cookbook/tools/overview.mdx ; https://github.com/agno-agi/docs/blob/main/tools/reasoning_tools/workflow-tools.mdx ; https://github.com/agno-agi/docs/blob/main/examples/tools/overview.mdx |
| Models | https://github.com/agno-agi/docs/blob/main/models/model-as-string.mdx ; https://github.com/agno-agi/docs/blob/main/models/providers/model-index.mdx ; https://github.com/agno-agi/docs/blob/main/models/fallback-models.mdx |
| Reasoning | https://github.com/agno-agi/docs/blob/main/reasoning/overview.mdx ; https://github.com/agno-agi/docs/blob/main/reasoning/reasoning-tools.mdx ; https://github.com/agno-agi/docs/blob/main/reasoning/reasoning-agents.mdx |
| Memory | https://github.com/agno-agi/docs/blob/main/memory/working-with-memories/overview.mdx ; https://github.com/agno-agi/docs/blob/main/memory/best-practices.mdx ; https://github.com/agno-agi/docs/blob/main/examples/basics/agent-with-memory.mdx |
| Knowledge | https://github.com/agno-agi/docs/blob/main/knowledge/overview.mdx ; https://github.com/agno-agi/docs/blob/main/knowledge/agents/overview.mdx ; https://github.com/agno-agi/docs/blob/main/knowledge/agents/rag-with-lance-db-and-sqlite.mdx |
| Sessions | https://github.com/agno-agi/docs/blob/main/sessions/overview.mdx ; https://github.com/agno-agi/docs/blob/main/sessions/persisting-sessions/overview.mdx ; https://github.com/agno-agi/docs/blob/main/agents/usage/agent-with-storage.mdx |
| Database and Storage | https://github.com/agno-agi/docs/blob/main/database/overview.mdx ; https://github.com/agno-agi/docs/blob/main/database/providers/overview.mdx ; https://github.com/agno-agi/docs/blob/main/cookbook/storage/overview.mdx |
| Tracing and Observability | https://github.com/agno-agi/docs/blob/main/tracing/overview.mdx ; https://github.com/agno-agi/docs/blob/main/tracing/basic-setup.mdx ; https://github.com/agno-agi/docs/blob/main/observability/overview.mdx |
| AgentOS | https://github.com/agno-agi/docs/blob/main/index.mdx ; https://github.com/agno-agi/docs/blob/main/examples/agent-os/os-config/basic.mdx ; https://github.com/agno-agi/docs/blob/main/agent-os/usage/middleware/custom-middleware.mdx |
| Security (RBAC) | https://github.com/agno-agi/docs/blob/main/agent-os/security/overview.mdx ; https://github.com/agno-agi/docs/blob/main/agent-os/security/rbac.mdx ; https://github.com/agno-agi/docs/blob/main/examples/agent-os/rbac/symmetric/basic.mdx |
| MCP | https://github.com/agno-agi/docs/blob/main/cookbook/tools/mcp.mdx ; https://github.com/agno-agi/docs/blob/main/examples/tools/mcp/overview.mdx ; https://github.com/agno-agi/docs/blob/main/examples/agent-os/advanced-demo/mcp-demo.mdx |
| Evaluations | https://github.com/agno-agi/docs/blob/main/evals/overview.mdx ; https://github.com/agno-agi/docs/blob/main/evals/accuracy/overview.mdx ; https://github.com/agno-agi/docs/blob/main/evals/agent-as-judge/overview.mdx |
| Examples and Patterns | https://github.com/agno-agi/docs/blob/main/examples/introduction.mdx ; https://github.com/agno-agi/docs/blob/main/examples/reasoning/overview.mdx |

## Project Notes
- Agent Persona guidance: [docs/agent-persona.md](docs/agent-persona.md)

## 1) Agents (core building block)
- Agents are a stateful control loop around a stateless model, using tools and instructions in a loop to reach a final response.
- Start simple: model + tools + instructions; add memory, knowledge, storage, guardrails, and followups only as needed.
- Run with `Agent.run()` or `Agent.arun()`; `print_response()` is useful for development. Streaming returns `RunOutputEvent` chunks and can include tool, reasoning, and memory events.
- Inputs can be strings, dicts, messages, or Pydantic models; outputs are `RunOutput` with IDs, content, metrics, messages, and model metadata.
- Debug with `debug_mode=True` (agent or per-run) or `AGNO_DEBUG=True`, and use the interactive CLI via `agent.cli_app()` for multi-turn testing.
- Tools: attach toolkits to enable external actions; the agent chooses when to call tools during the run loop.
- Structured output: set `output_schema` to return a typed Pydantic model instead of free text.
- Storage: attach a Db (for example SQLite) and use `session_id` plus `add_history_to_context` and `num_history_runs` for conversational continuity.
- Memory: use a `MemoryManager` with `enable_agentic_memory=True` for tool-driven memory, or `update_memory_on_run=True` for automatic capture; memory stores user facts across sessions.
- Knowledge: attach a Knowledge base backed by a vector DB and an embedder; insert content via URL, file, or text for agentic RAG.
- Followups: set `followups=True` and `num_followups` to generate suggested next prompts; optionally use a separate `followup_model` to reduce cost.
- Context engineering: use system/introduction messages, dynamic instructions, few-shot examples, datetime/location context, and tool-call filtering to shape the run context.
- Dependencies: inject runtime context into agent runs or agent context; tools can read dependencies and even change tool availability dynamically.
- Hooks and guardrails: add pre/post hooks for validation, tool hooks for middleware, and guardrails for input/output/PII/prompt-injection checks.
- HITL approvals: require confirmations or user input and route external tool execution through approval workflows (including audit-style approvals).

## 2) Teams (multi-agent collaboration)
- A Team is a collection of agents (or sub-teams) coordinated by a leader that delegates and synthesizes.
- Coordination modes include coordinate, route, broadcast, and tasks; switching modes changes topology without changing agent logic.
- Teams can pause for human-in-the-loop requirements and resume after approval.
- Team output can be structured with schemas in coordination mode for predictable responses.
- AgentOS Studio provides a visual Team Builder for composing and running teams without code.
- Dependencies: inject shared context into a team run or team context, and reference dependencies directly in team instructions.
- Context engineering for teams: tune system/instruction context and filter tool calls from team history for cleaner delegation.
- Callable members: provide a function that returns members at runtime to enable dynamic team composition.

## 3) Workflows (deterministic pipelines)
- Workflows run ordered steps; each step can be an agent or a custom executor function.
- `input_schema` validates structured inputs (dict or BaseModel) before execution.
- Workflows can be nested; inner workflow output and state flow back to the outer workflow.
- User input steps can collect required parameters with a schema before executing a step.
- Workflow history can be included in steps for context in continuous executions.
- Use typed input schemas to keep workflow inputs predictable and debuggable.
- Step types include conditional, router, loop, and parallel patterns for non-linear workflows.
- Custom function steps can stream output and update session state during execution.

## 4) Tools (capabilities and integrations)
- Tools enable external actions; custom tools use the `@tool` decorator.
- Tool hooks act as middleware to run logic before and after tool calls (validation, logging, argument transforms).
- Hooks can be applied globally or to specific tools or toolkits.
- MCP provides standardized tool integration with filtering and multi-server support.
- Tool choice and call limits constrain when and how often tools are invoked.
- Callable tool factories can build tool lists dynamically from runtime context.

## 5) Models (LLM providers and routing)
- Models can be specified via the `provider:model_id` string format and support many cloud and local providers.
- Agents and Teams can define fallback models; if the primary fails, fallbacks are tried sequentially.
- Fallbacks work with streaming and can reset output cleanly on failover.
- Some gateways (like OpenRouter) support automatic fallback routing via a models list.
- Use separate models for response shaping (`output_model`) or parsing (`parser_model`) when you want extra control over final outputs.

## 6) Reasoning (quality and reliability)
- Reasoning Tools provide explicit `think()` and `analyze()` calls for agent-controlled reasoning.
- Reasoning Agents enforce systematic reasoning for every request and work well with tool use.
- Choose tools for flexible, agent-managed reasoning; choose agents for guaranteed reasoning depth.
- Reasoning integrates with knowledge search for agentic RAG when needed.
- Use a separate reasoning model with step limits to bound reasoning depth and cost.

## 7) Memory (user-level recall)
- Memory stores user-level facts across sessions; storage is conversation history.
- Automatic memory (`update_memory_on_run=True`) is recommended for most cases; agentic memory is for real-time or command-driven updates.
- Memory search supports `last_n`, `first_n`, and `agentic` strategies.
- Use cheaper models for memory operations and prune old memories to control cost.
- Memory optimization merges related memories to reduce token usage.
- Always set a `user_id` for memory to avoid cross-user mixing.
- External memory services can be integrated to back memory operations when needed.

## 8) Knowledge (RAG and grounding)
- Knowledge enables agentic RAG: content is chunked, embedded, and retrieved at runtime.
- Vector databases store embeddings for similarity search; options include PgVector, LanceDB, Qdrant, Pinecone, Redis, and more.
- Multiple knowledge bases can be configured for separate domains.
- Content can be inserted via URL, local file, or raw text.
- Add knowledge filters (static or agentic) to scope retrieval by metadata or conditions.
- Use custom retrievers, rerankers, and reference formatting to control retrieval quality and citations.
- Choose chunking strategies, readers, and embedding providers to match data format and scale.

## 9) Sessions (conversation lifecycle)
- Sessions group multi-turn runs; `user_id` separates users and `session_id` separates threads.
- Session summaries can be enabled with `enable_session_summaries=True` to reduce token usage.
- Summary events are emitted when summaries start and complete.
- Session context supports summary mode for lightweight continuity.
- Session state tools and events let you track, update, and persist state across runs.

## 10) Database and Storage (persistence foundation)
- Databases store sessions, context, memory, learnings, and evals.
- Storage is unified under `Db` classes in v2; one Db instance can handle multiple tables.
- Supported backends include SQLite, PostgreSQL, Firestore, DynamoDB, and InMemoryDb for testing.
- Production deployments typically use PostgreSQL; InMemoryDb is for ephemeral tests.
- Async database providers are available for MongoDB, PostgreSQL, MySQL, and SQLite.
- Custom table naming and session storage patterns help align Agno with existing schemas.

## 11) Tracing and Observability (auditability and debugging)
- Tracing captures agent runs, model calls, and tool executions using OpenTelemetry.
- Enable tracing with `setup_tracing()` or `tracing=True` in AgentOS for simpler defaults.
- Traces are stored in your database; a dedicated tracing DB is recommended for consistency.
- Observability helps debug failures, analyze performance, and track cost/latency.
- Trace filtering and multi-DB tracing support targeted troubleshooting and distributed setups.
- Custom logging and token counting help monitor context growth and tool call costs.

## 12) AgentOS (runtime and control plane)
- AgentOS turns agents into a production-ready API with SSE-compatible streaming endpoints.
- It provides endpoints for agents, teams, workflows, sessions, memory, knowledge, and evals.
- AgentOS is built on FastAPI and can be integrated with custom apps and middleware.
- Data ownership stays in your database, including traces, sessions, memory, and knowledge.
- The AgentOS API is RESTful and organized around core resources (agents, teams, workflows).
- AgentOS Control Plane and Studio provide visual management for agents, teams, workflows, and registries.
- Interfaces expose agents via Slack, Telegram, WhatsApp, A2A, AG-UI, and other channels.
- Clients enable remote execution and management (AgentOS client, A2A client) across instances.
- Scheduler runs agents/teams/workflows on cron schedules with REST-managed schedules and history.
- Middleware, lifespan hooks, and custom FastAPI integration support auth, logging, and custom routes.

## 13) Security (RBAC)
- RBAC uses JWT validation and scope checks for each endpoint.
- Enable with `authorization=True` and set `JWT_VERIFICATION_KEY` for verification.
- Basic auth is available for simple dev setups; RBAC is recommended for production.
- Support symmetric/asymmetric keys, custom scope mappings, and per-agent permissions.
- JWT middleware supports authorization headers and HTTP-only cookie flows.

## 14) MCP (external tool connectivity)
- MCP provides standardized external tool integration for agents.
- Tool filtering lets you include or exclude MCP tools to control capabilities.
- MCPToolbox supports toolset filtering and avoids name collisions.
- Tool name prefixes help prevent collisions when multiple MCP servers are used.
- AgentOS can run as an MCP server and expose MCPTools to agents, teams, and workflows.
- MCP supports passing dynamic headers to external servers for user-specific context.

## 15) Evaluations (quality measurement)
- Evals measure accuracy, performance, reliability, and custom quality dimensions.
- Agent-as-judge evaluations use LLM scoring with configurable criteria.
- Evaluations can run as post-hooks to score every response automatically.
- Async evals, DB logging, and metrics tracking are supported across evaluation types.
- Team and tool-based evals validate routing, tool calls, and multi-agent outputs.

## 16) Examples and Patterns (how-to guidance)
- The cookbook provides thousands of production-ready examples across the entire stack.
- Examples cover agents, tools, reasoning, knowledge, storage, and AgentOS integrations.
- Deployment templates cover AWS, Docker, and Railway setups with CI/CD and infra guides.
- Reference apps showcase production agents, teams, and workflows (reviews, support, research, enrichment).
- Interface examples demonstrate Slack, Telegram, WhatsApp, A2A, and AG-UI integrations.
- Advanced agent patterns cover caching, compression, concurrency, background runs, and serialization.
- HITL and approval examples cover confirmation flows, audit approvals, and external execution.

---

# Build Your Agent: Practical Blueprint

## A) Minimum viable agent
1) Choose a model provider and model ID.
2) Create an Agent with a role and clear instructions.
3) Add tools only if needed for external actions.
4) Enable storage if you want multi-turn sessions.

## B) Quality and grounding upgrades
- Add Knowledge with a vector DB + embedder for RAG.
- Add Memory to retain user preferences across sessions.
- Use reasoning tools or reasoning agents for complex tasks.
- Use reasoning model + response model for higher quality outputs.
- Enable tracing to inspect failures and optimize prompts/tools.

## C) Production hardening
- Configure DB storage for sessions, memory, and tracing.
- Add fallback models and graceful failure strategies.
- Use RBAC if exposing AgentOS publicly.
- Add evals (accuracy and judge) for regression tracking.
- Pick a deployment template (AWS/Docker/Railway) and configure CI/CD, secrets, and monitoring.
- Select the interface channel (Slack/Telegram/WhatsApp/A2A/AG-UI) early to shape auth and event handling.
- Add approvals/HITL for sensitive tool calls and external execution paths.

---

# XML Prompt (Template)

Use this XML prompt to regenerate or extend the summary from Agno docs:

```xml
<prompt>
  <role>You are a senior AI engineer analyzing and enhancing an existing Agno documentation summary.</role>
  <goal>Analyze the current summary, identify gaps or weak spots, and enhance it using only the provided Agno docs while preserving structure and tone.</goal>
  <inputs>
    <doc_sources>Context7 extracts from agno-agi/docs</doc_sources>
    <scope>All modules including examples</scope>
    <format>Markdown</format>
    <current_summary>docs/agno-summary.md</current_summary>
  </inputs>
  <output_spec>
    <sections>
      <section>Agents</section>
      <section>Teams</section>
      <section>Workflows</section>
      <section>Tools</section>
      <section>Models</section>
      <section>Reasoning</section>
      <section>Memory</section>
      <section>Knowledge</section>
      <section>Sessions</section>
      <section>Database and Storage</section>
      <section>Tracing and Observability</section>
      <section>AgentOS</section>
      <section>Security (RBAC)</section>
      <section>MCP</section>
      <section>Evaluations</section>
      <section>Examples and Patterns</section>
      <section>Build Your Agent Blueprint</section>
    </sections>
    <style>
      <bullet_style>short, action-oriented</bullet_style>
      <tone>practical, production-focused</tone>
      <length>3-5 pages</length>
    </style>
    <behavior>
      <preserve_existing_structure>true</preserve_existing_structure>
      <add_missing_points_only>true</add_missing_points_only>
      <avoid_rewriting_when_complete>true</avoid_rewriting_when_complete>
    </behavior>
  </output_spec>
  <constraints>
    <no_hallucination>Only summarize what is in the provided docs.</no_hallucination>
    <no_vendor_lockin>Prefer provider-agnostic guidance.</no_vendor_lockin>
  </constraints>
</prompt>
```
