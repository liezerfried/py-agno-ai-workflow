# py-agno-ai-workflow

[![CI](https://github.com/liezerfried/py-agno-ai-workflow/actions/workflows/ci.yml/badge.svg)](https://github.com/liezerfried/py-agno-ai-workflow/actions/workflows/ci.yml)

An AI-powered data normalization system built with [Agno](https://docs.agno.com), designed to automatically classify and standardize free-text job titles and occupational categories from Excel files into structured, system-ready formats.

## Purpose

Organizations across job boards, ATS platforms, recruiting firms, and HR departments constantly deal with the same problem: humans write job titles and categories freely, but software systems expect exact, normalized values.

```
"Dev Front"             ≠  "Frontend Developer"
"RRHH"                  ≠  "Human Resources"
"Desarrollador Backend" ≠  "Backend Developer"
```

A human understands these are equivalent. A database query, search filter, or ATS does not. Today this is cleaned manually — this system automates it.

## How It Works

Users upload an Excel file through a web interface. The agent workflow processes each row, maps free-text job titles to valid standardized categories, and returns a clean, structured output ready for ingestion into any system.

The architecture uses Agno's **Workflow + Step** pattern for predictable, linear orchestration — no graph complexity, just a clear pipeline where each step has a defined role.

### Key components

- **Agno Workflow** — orchestrates the processing pipeline step by step
- **Agent(s)** — classify and normalize each job title using an LLM with domain knowledge
- **Human-in-the-loop** — unresolvable cases are flagged for manual review instead of guessed
- **Chainlit** — web interface for file upload and result display

## Target Users

| Context | User | Input |
|---------|------|-------|
| Job board (LinkedIn, Bumeran) | Company posting jobs | Excel with raw vacancy categories |
| HR / ATS system | HR analyst | System export with unnormalized candidate titles |
| Recruiting firm | Recruiter | CV database with titles as candidates wrote them |
| Legacy system migration | Data administrator | Historical database dump with inconsistent categories |
| Upskilling platform | Content team | Skills catalog with variants and synonyms |

## Stack

- **Python** — core language
- **Agno** — agent framework and workflow orchestration
- **Chainlit** — conversational web UI
- **LM Studio** — local LLM inference (model TBD)
- **Pandas / openpyxl** — Excel processing

## Project Structure

```
py-agno-ai-workflow/
├── data/
│   └── raw/                  # Input Excel files
├── docs/                     # Architecture and design documentation
├── scripts/                  # Utility scripts
└── README.md
```

## Status

Active development — currently structuring data pipeline and agent orchestration design.
