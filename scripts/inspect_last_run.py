"""
Inspect the most recent pipeline run captured in tmp/traces.db.

Prints an execution tree of all spans, flags hangs (spans with no end_time),
and summarises LLM latency + token usage so we can identify the cuello of a slow run.

Usage:
    .venv/Scripts/python.exe scripts/inspect_last_run.py
    .venv/Scripts/python.exe scripts/inspect_last_run.py --run-id <RUN_ID>
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

DB_PATH = Path("tmp/agentos.db")


def _fmt_ms(ms: int | None) -> str:
    if ms is None:
        return "  ?ms (NO end_time — possible hang)"
    if ms < 1000:
        return f"{ms}ms"
    return f"{ms / 1000:.1f}s"


def _latest_run_id(con: sqlite3.Connection) -> str | None:
    # Filter run_id IS NOT NULL: low-level model calls (e.g. LMStudio.invoke) are also stored
    # as traces with no run_id. We want the most recent agent/workflow trace, not those.
    row = con.execute(
        "SELECT run_id FROM agno_traces WHERE run_id IS NOT NULL ORDER BY start_time DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def _recent_traces(con: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT trace_id, run_id, name, status, duration_ms, start_time "
        "FROM agno_traces WHERE run_id IS NOT NULL "
        "ORDER BY start_time DESC LIMIT ?",
        (limit,),
    ).fetchall()


def _trace_for_run(con: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM agno_traces WHERE run_id = ? ORDER BY start_time DESC LIMIT 1",
        (run_id,),
    ).fetchone()


def _spans_for_trace(con: sqlite3.Connection, trace_id: str) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT * FROM agno_spans WHERE trace_id = ? ORDER BY start_time",
        (trace_id,),
    ).fetchall()


def _print_tree(spans: list[sqlite3.Row]) -> None:
    children: dict[str | None, list[sqlite3.Row]] = defaultdict(list)
    for s in spans:
        children[s["parent_span_id"]].append(s)

    def walk(parent_id: str | None, depth: int) -> None:
        for s in children[parent_id]:
            indent = "  " * depth
            attrs = json.loads(s["attributes"]) if s["attributes"] else {}
            kind = attrs.get("openinference.span.kind") or s["span_kind"] or "?"
            extra = ""
            if kind == "LLM":
                model = attrs.get("llm.model_name") or attrs.get("gen_ai.request.model", "?")
                pt = attrs.get("llm.token_count.prompt") or attrs.get("gen_ai.usage.prompt_tokens", 0)
                ct = attrs.get("llm.token_count.completion") or attrs.get("gen_ai.usage.completion_tokens", 0)
                extra = f"  Model={model}  Tokens={pt}/{ct}"
            elif kind == "TOOL":
                extra = f"  Tool={attrs.get('tool.name', '?')}"
            status = s["status_code"] or "?"
            marker = " [HANG?]" if s["end_time"] is None else ""
            print(f"{indent}- {s['name']} ({_fmt_ms(s['duration_ms'])}) [{status}] kind={kind}{extra}{marker}")
            walk(s["span_id"], depth + 1)

    walk(None, 0)


def _summary(spans: list[sqlite3.Row]) -> None:
    llm_durations: list[int] = []
    llm_by_model: dict[str, list[int]] = defaultdict(list)
    total_prompt = 0
    total_completion = 0
    hangs = 0
    errors = 0
    by_status: dict[str, int] = defaultdict(int)

    for s in spans:
        if s["end_time"] is None:
            hangs += 1
        if (s["status_code"] or "").upper() == "ERROR":
            errors += 1
        by_status[s["status_code"] or "?"] += 1
        attrs = json.loads(s["attributes"]) if s["attributes"] else {}
        kind = attrs.get("openinference.span.kind") or s["span_kind"]
        if kind == "LLM" and s["duration_ms"] is not None:
            llm_durations.append(s["duration_ms"])
            model = attrs.get("llm.model_name") or attrs.get("gen_ai.request.model", "unknown")
            llm_by_model[model].append(s["duration_ms"])
            total_prompt += int(attrs.get("llm.token_count.prompt") or attrs.get("gen_ai.usage.prompt_tokens") or 0)
            total_completion += int(attrs.get("llm.token_count.completion") or attrs.get("gen_ai.usage.completion_tokens") or 0)

    print("\n=== SUMMARY ===")
    print(f"Total spans: {len(spans)}  errors: {errors}  hangs (no end_time): {hangs}")
    print(f"Status distribution: {dict(by_status)}")

    if llm_durations:
        llm_durations.sort()
        n = len(llm_durations)
        p50 = llm_durations[n // 2]
        p95 = llm_durations[min(n - 1, int(n * 0.95))]
        print(f"\nLLM calls: {n}")
        print(f"  total: {sum(llm_durations) / 1000:.1f}s   avg: {sum(llm_durations) // n}ms   p50: {p50}ms   p95: {p95}ms   max: {max(llm_durations)}ms")
        print(f"  tokens: prompt={total_prompt}  completion={total_completion}")
        for model, durs in llm_by_model.items():
            print(f"  by model [{model}]: {len(durs)} calls, total {sum(durs) / 1000:.1f}s, avg {sum(durs) // len(durs)}ms")
    else:
        print("\nNo LLM spans found — check that openinference-instrumentation-agno is installed and that the pipeline made LLM calls.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", help="Specific run_id to inspect (default: most recent)")
    parser.add_argument("--recent", type=int, metavar="N", help="List last N traces and exit (no detail)")
    parser.add_argument("--db", default=str(DB_PATH), help=f"Path to SQLite traces DB (default: {DB_PATH})")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 1

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    if args.recent:
        rows = _recent_traces(con, args.recent)
        for r in rows:
            print(f"{r['start_time']}  run_id={r['run_id']}  name={r['name']}  status={r['status']}  duration={_fmt_ms(r['duration_ms'])}")
        return 0

    run_id = args.run_id or _latest_run_id(con)
    if not run_id:
        print("No traces found in DB.", file=sys.stderr)
        return 1

    trace = _trace_for_run(con, run_id)
    if not trace:
        print(f"No trace for run_id={run_id}", file=sys.stderr)
        return 1

    print(f"Run ID:    {trace['run_id']}")
    print(f"Trace ID:  {trace['trace_id']}")
    print(f"Name:      {trace['name']}")
    print(f"Status:    {trace['status']}")
    print(f"Duration:  {_fmt_ms(trace['duration_ms'])}")
    print(f"Start:     {trace['start_time']}")
    print(f"End:       {trace['end_time'] or '(none — trace did not finish)'}")
    if trace["agent_id"]:
        print(f"Agent:     {trace['agent_id']}")
    if trace["workflow_id"]:
        print(f"Workflow:  {trace['workflow_id']}")
    print()

    spans = _spans_for_trace(con, trace["trace_id"])
    print(f"=== EXECUTION TREE ({len(spans)} spans) ===")
    _print_tree(spans)
    _summary(spans)
    return 0


if __name__ == "__main__":
    sys.exit(main())
