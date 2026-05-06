# ADR 0002 — Operational Metrics: SQLite pipeline_runs table

**Status:** Accepted  
**Date:** 2026-05-05

## Context

`AuditResult` already computes per-run metrics (`precision`, `corrected_count`,
`review_queue_count`, `hallucination_count`). These are logged and shown in the
Chainlit UI but not persisted — they disappear when the session ends.

For portfolio purposes, aggregated metrics across runs ("processed 47 files, avg
precision 94%") are more compelling than per-session numbers.

## Decision

Add a `pipeline_runs` table to the existing `tmp/traces.db` SQLite database.
One row per pipeline run. Columns: `run_id`, `timestamp`, `filename`, `total_rows`,
`corrected`, `review_queue`, `hallucinations`, `precision`.

Rejected alternative:
- **Per-decision table (`run_decisions`)** — individual corrections per run.
  Adds schema complexity without meaningful additional value for the portfolio goal.

The Chainlit UI exposes this via an action at session start:
- `[ Procesar nuevo archivo ]` → existing upload flow
- `[ Ver historial de runs ]` → renders the table as a Chainlit message

## Consequences

- A new `infrastructure/pipeline/metrics_store.py` module owns the SQLite writes
- `audit_writer_agent.py` calls it after `AuditResult` is produced
- `app.py` reads from it to render the history view
- The `tmp/` directory (already gitignored) holds the DB — no new infra needed
- Schema migration is manual for now (drop and recreate `tmp/traces.db` if schema changes)