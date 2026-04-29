# Agent Persona

## Definition
Agent Persona defines an AI agent's role, behavior, communication style, and boundaries.

## What Is an Agent Persona?
An Agent Persona is the set of characteristics that define how an AI agent behaves, communicates, and presents itself when interacting with users or other systems.

A persona typically includes elements such as:
- Role definition: what the agent is responsible for
- Communication style: tone, format, and level of detail
- Knowledge boundaries: what it can and cannot cover
- Behavioral rules: how it handles edge cases and sensitive topics
- Brand alignment: voice and values consistency

## Why Agent Personas Matter
Personas prevent generic, inconsistent responses and make output predictable across similar requests. Consistency builds trust and protects the brand.
For businesses in Southeast Asia, cultural sensitivity is a first-order requirement, not an optional style choice.

## The Generic Persona Problem
Most personas look like this:

---
name: Assistant
description: |
	You are a helpful AI assistant that helps with coding tasks.
	Be thorough and helpful.
---

This fails because:
- No specific expertise -- could do anything (does nothing well)
- No defined process -- every task approaches differently
- No output format -- results are unpredictable
- No constraints -- no guardrails on behavior
- No identity -- interchangeable with any other assistant

The result: inconsistent output that varies based on how the request is phrased.

## The Five Elements of Effective Personas
Every effective persona definition includes five elements:

| Element | Question | Defines |
| --- | --- | --- |
| 1. Role | Who are you? | Specific title, domain expertise, perspective or stance |
| 2. Expertise | What do you know? | Knowledge areas, tools mastered, boundaries |
| 3. Process | How do you work? | Step-by-step methodology, decision criteria, escalation |
| 4. Output | What do you produce? | Exact format, required sections, examples |
| 5. Constraints | What won't you do? | Explicit boundaries, anti-patterns, when to refuse |

### 1) Role
The role establishes identity and perspective. It is not just a job title.

Bad:
"You are a helpful assistant."

Good:
"You are a senior application security engineer specializing in code review.
You think like an attacker to find vulnerabilities before they are exploited."

The good version establishes:
- Seniority -- not a beginner, has judgment
- Specialty -- security, not general coding
- Perspective -- attacker mindset, adversarial thinking

Role patterns:
- Expert -- "Senior X engineer with 10+ years experience"
- Critic -- "Devil's advocate who challenges assumptions"
- Teacher -- "Patient instructor who explains concepts clearly"
- Investigator -- "Detective who gathers evidence before conclusions"
- Advocate -- "Champion for clean code who won't accept shortcuts"

### 2) Expertise
Expertise defines what the agent knows deeply. Keep it specific and bounded.

Bad:
"You know about security."

Good:
## Expertise
- OWASP Top 10 vulnerabilities
- Authentication and authorization flaws
- Injection attacks (SQL, XSS, command)
- Cryptographic weaknesses
- Security misconfigurations
- Secure coding patterns in JavaScript or TypeScript

Note what this does not include: network security, infrastructure hardening, compliance frameworks. The agent has boundaries.

Guidelines:
- Be specific -- "OWASP Top 10" not "web security"
- Set boundaries -- what it knows, implicitly what it does not
- Include techniques -- not just topics, but methods
- Match the role -- expertise should align with identity

### 3) Process
Process is the step-by-step methodology. This is what makes output consistent -- every invocation follows the same steps.

Bad:
"Analyze the code carefully."

Good:

## Process

### 1. Threat Modeling
- What are the assets being protected?
- Who are the potential attackers?
- What are the attack surfaces?

### 2. Code Analysis
- Input validation and sanitization
- Authentication mechanisms
- Authorization checks
- Data handling and storage
- Error handling and logging

### 3. Risk Assessment
- Severity (Critical/High/Medium/Low)
- Exploitability (Easy/Moderate/Difficult)
- Impact (Data breach/Service disruption/Reputation)

### 4. Recommendation Formation
- Prioritize by risk
- Provide specific fixes
- Include code examples

Guidelines:
- Number the steps -- creates checkpoints
- Make steps actionable -- verbs, not nouns
- Include decision points -- when to go deeper, when to stop
- Define order -- sequential when order matters

### 4) Output
Output defines the exact format of what the agent produces. This is critical for consistency.

Bad:
"Provide a report of your findings."

Good:

## Output Format

## Security Audit Report

### Summary
[1-2 sentence overview: critical count, recommendation]

### Critical Issues
1. **[Vulnerability Name]**
	 - Location: file:line
	 - Risk: [severity] - [impact description]
	 - Exploit: [how it could be attacked]
	 - Fix: [specific remediation with code]

### High Priority Issues
[Same format as Critical]

### Recommendations
1. [Prioritized action item]
2. [Next action item]

### Notes
[Context, limitations of analysis, areas not covered]

Guidelines:
- Show the exact structure -- Markdown template
- Label required sections -- what must appear
- Provide field descriptions -- what goes in each
- Include examples -- especially for complex fields

### 5) Constraints
Constraints are explicit boundaries -- what the agent will not do, patterns it avoids, when it escalates.

Bad:
"Be careful with security recommendations."

Good:

## Constraints
- Never assume code is safe without evidence
- Always provide proof-of-concept for vulnerabilities (but sanitized, not weaponized)
- Do not recommend security theater (checkbox measures that do not add protection)
- Prioritize by actual risk, not theoretical severity
- If unsure about a finding, flag for human review rather than omitting
- Do not analyze code outside the specified scope without asking
- Never suggest "just disable security" as a fix

Constraint categories:
- Evidence requirements -- "Never guess -- gather evidence first"
- Scope limits -- "Only analyze specified files"
- Escalation triggers -- "If unsure, flag for human review"
- Anti-patterns -- "Do not suggest disabling validation"
- Output guards -- "Never include actual secrets in reports"

## Operational Considerations
- Tone and voice should be explicit (length, structure, formality).
- Cultural sensitivity is required for ASEAN markets.
- Escalation protocols must be clear and testable.

## Persona Patterns
Different tasks benefit from different persona patterns:

- Specialist: narrow expertise, deep knowledge, stays in lane
- Generalist: broad knowledge, coordinates and delegates
- Contrarian: challenges assumptions, stress-tests decisions
- Producer: creates artifacts like docs, tests, reports
- Investigator: gathers evidence, forms and tests hypotheses

## Agent Portfolio
Reference portfolio covering common development needs:

| Category | Agent | Pattern | Triggers On |
| --- | --- | --- | --- |
| Review | CodeReviewer | Specialist | "review", "check quality" |
| Security | SecurityAuditor | Specialist | "security", "vulnerabilities" |
| Critique | Critic | Contrarian | "challenge", "critique" |
| Create | TestEngineer | Producer | "test", "coverage" |
| Create | Documenter | Producer | "document", "readme" |
| Create | BlogWriter | Producer | "blog", "article" |
| Analyze | Architect | Generalist | "design", "architecture" |
| Analyze | IntentArchitect | Generalist | vague requirements |
| Research | Researcher | Investigator | "how does", "where is" |
| Debug | Debugger | Investigator | "bug", "error", "fix" |
| Meta | MetaAnalyzer | Investigator | session analysis |
| Improve | Refactorer | Specialist | "refactor", "restructure" |
| Improve | Optimizer | Specialist | "optimize", "performance" |
| Summarize | Changelog | Producer | "summarize", "changelog" |
| Plan | Planner | Generalist | "plan", "break down" |

## Agent Personas in Practice

### Customer-Facing Applications
Customer service chatbots and virtual assistants need consistent tone, boundaries, and escalation behavior.

### Internal Enterprise Tools
Internal assistants should match the audience (sales, engineering, legal) and the task type.

### Multi-Agent Systems
Multi-agent systems benefit from clear persona differentiation per role.

## Common Mistakes in Persona Design
- Too broad: does everything, good at nothing
- No process: lacks numbered steps
- Vague output: missing a template
- Missing constraints: no guardrails or escalation
- Generic role: no identity or stance
- Not tested: no validation on edge cases

## Testing Your Personas
- Run a typical task and check output format
- Run an edge case and verify constraints
- Check step adherence in order
- Verify out-of-scope refusals
- Compare outputs across similar prompts

## Key Takeaways for Decision-Makers
Agent personas shape trust, output quality, and adoption. Specificity, process, and constraints are the core levers.

## Business Impact
Persona design is a brand and customer experience investment. Better personas correlate with higher satisfaction, lower escalations, and higher adoption.

## Key Considerations
- Define personas with the same rigor as hiring guidelines
- Tailor personas for market and cultural context
- Make escalation rules explicit
- Set guardrails for prohibited topics
- Iterate based on real user feedback

## Common Questions

### How detailed should an agent persona be?
Detailed enough that a new team member can predict consistent behavior. At minimum: role, communication style, knowledge boundaries, escalation rules, prohibited behaviors.

### Can one AI agent have different personas for different markets?
Yes. Use persona overlays by market, language, or segment while keeping brand consistency.

## References
- NIST Artificial Intelligence Risk Management Framework (AI RMF 1.0). National Institute of Standards and Technology (NIST) (2023).
- Stanford HAI AI Index Report 2025. Stanford Institute for Human-Centered AI (2025).
- Anthropic Research - AI Safety and Alignment Directions. Anthropic (2025).
- Google DeepMind Research. Google DeepMind (2024).
- LangChain State of AI Agents Report: 2024 Trends. LangChain (2024).
- AutoGen: A Programming Framework for Agentic AI. Microsoft Research (2024).
- Function Calling - OpenAI API Documentation. OpenAI (2024).
- Agents - OpenAI API Documentation. OpenAI (2025).
- LangGraph: Agent Orchestration Framework for Reliable AI Agents. LangChain (2024).
- Microsoft Agent Framework Overview. Microsoft (2025).
