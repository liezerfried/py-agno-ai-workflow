"""
Headless reproduction harness for the normalization pipeline.

Runs the four pipeline steps directly against an Excel file, with
per-anomaly timing and heartbeat logging on the MapperAgent step (the suspected
bottleneck). Bypasses Chainlit UI so the bug is exercised in isolation; OTEL
traces still flow to tmp/agentos.db.

Usage:
    .venv/Scripts/python.exe scripts/repro_pipeline.py data/test_100_autodetect.xlsx
    .venv/Scripts/python.exe scripts/repro_pipeline.py <file> --column <name>
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Make the project root importable when this script is launched directly (e.g.
# `python scripts/repro_pipeline.py`). Without this, the `agents` and `workflows`
# packages are not on sys.path because Python only adds the script's own dir.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Initialise tracing the same way the production entry points do, so spans land
# in tmp/agentos.db and can be inspected with scripts/inspect_last_run.py later.
from agno.db.sqlite import SqliteDb
from agno.tracing import setup_tracing
from agno.workflow import StepInput

setup_tracing(db=SqliteDb(db_file="tmp/agentos.db"), batch_processing=True)

from agents.audit_writer_agent import AuditResult, audit_executor
from agents.ingest_agent import IngestResult, detect_job_column, ingest_executor, scan_headers
from agents.mapper_agent import MappingResult, _decide, mapper_executor, set_progress_callback
from agents.validator_agent import ValidatorResult, validator_executor
from infrastructure.pipeline.session import PipelineSession
from infrastructure.pipeline.step_io import deserialize, ok
from workflows.normalization_workflow import load_valid_categories


def _heartbeat_mapper(validator_json: str, session: PipelineSession, heartbeat_every: int) -> tuple[MappingResult, list[float]]:
    """
    Run MapperAgent's _decide() per anomaly with timing + heartbeat logging.

    Returns the MappingResult plus a list of per-anomaly elapsed seconds, so the
    caller can compute p50/p95 over what is normally an opaque single Step span.
    """
    validator = deserialize(validator_json, ValidatorResult)
    anomalies = validator.anomalies
    total = len(anomalies)
    print(f"[mapper] {total} anomalies to map")

    decisions = []
    timings: list[float] = []
    t_start = time.perf_counter()

    for i, anomaly in enumerate(anomalies, 1):
        t0 = time.perf_counter()
        decision = _decide(anomaly, session.valid_categories, session.valid_categories_set)
        elapsed = time.perf_counter() - t0
        timings.append(elapsed)
        decisions.append(decision)

        flag = "[SLOW]" if elapsed > 5.0 else ""
        print(
            f"[mapper] {i}/{total} raw={anomaly.raw!r} method={decision.method} "
            f"score={decision.confidence:.3f} elapsed={elapsed:.2f}s {flag}"
        )

        if i % heartbeat_every == 0 or i == total:
            total_elapsed = time.perf_counter() - t_start
            avg = total_elapsed / i
            eta = avg * (total - i)
            print(f"[mapper] heartbeat {i}/{total}  total={total_elapsed:.1f}s  avg={avg:.2f}s  eta={eta:.1f}s")

    return MappingResult(decisions=decisions), timings


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(len(s) * p))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", help="Path to the .xlsx file to process")
    parser.add_argument("--column", help="Target column (default: auto-detect)")
    parser.add_argument("--heartbeat", type=int, default=10, metavar="N",
                        help="Print mapper heartbeat every N anomalies (default: 10)")
    parser.add_argument("--no-audit", action="store_true",
                        help="Skip the AuditWriter step (faster repro for cuelgue debugging)")
    parser.add_argument("--executor", action="store_true",
                        help="Use the production mapper_executor (parallelised) instead of the "
                             "serial per-anomaly harness — measures real wall-clock with concurrency")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_path = str(Path(args.file).resolve())
    if args.column:
        target_column = args.column
    else:
        scan = scan_headers(file_path)
        col, score = detect_job_column(scan.column_names)
        if score < 0.85:
            print(f"[ERROR] Could not auto-detect column (best={col!r} score={score}). Pass --column.", file=sys.stderr)
            return 2
        target_column = col
        print(f"[setup] auto-detected column={target_column!r} score={score}")

    session = PipelineSession(
        file_path=file_path,
        target_column=target_column,
        valid_categories=load_valid_categories(),
    )
    session_state = session.to_dict()

    # Step 1 — Ingest
    t0 = time.perf_counter()
    out = ingest_executor(StepInput(previous_step_content=None), session_state)
    print(f"[ingest] {time.perf_counter() - t0:.2f}s success={out.success}")
    if not out.success:
        print(f"[ingest] FAILED: {out.content}", file=sys.stderr)
        return 1
    ingest_result = deserialize(out.content, IngestResult)
    print(f"[ingest] total_rows={ingest_result.total_rows} unique={len(ingest_result.raw_categories)}")

    # Step 2 — Validate
    t0 = time.perf_counter()
    out = validator_executor(StepInput(previous_step_content=out.content), session_state)
    print(f"[validate] {time.perf_counter() - t0:.2f}s success={out.success}")
    if not out.success:
        print(f"[validate] FAILED: {out.content}", file=sys.stderr)
        return 1
    validator_json = out.content
    validator_result = deserialize(validator_json, ValidatorResult)
    print(f"[validate] valid={validator_result.valid_count} anomalies={validator_result.anomaly_count}")

    # Step 3 — Map. Two paths:
    #   --executor: production mapper_executor (parallel via MAPPER_CONCURRENCY).
    #              Per-anomaly timings are not available because completions are
    #              concurrent; we record callback events instead and synthesise
    #              an approximate per-anomaly duration from total / count.
    #   default:   serial harness with per-anomaly timing (used for the original
    #              cuelgue diagnosis to identify slow rows).
    t0 = time.perf_counter()
    if args.executor:
        events: list[tuple[float, int, int]] = []  # (timestamp, processed, total)
        last_print_at = [0.0]

        def progress(processed: int, total: int) -> None:
            now = time.perf_counter() - t0
            events.append((now, processed, total))
            # Throttle stdout: print on first event, every heartbeat-th, and the final.
            if processed == 0 or processed == total or processed % args.heartbeat == 0:
                last_print_at[0] = now
                print(f"[mapper] heartbeat {processed}/{total}  elapsed={now:.1f}s")

        set_progress_callback(progress)
        try:
            mapper_out = mapper_executor(StepInput(previous_step_content=validator_json), session_state)
        finally:
            set_progress_callback(None)

        if not mapper_out.success:
            print(f"[mapper] FAILED: {mapper_out.content}", file=sys.stderr)
            return 1

        mapping_result = deserialize(mapper_out.content, MappingResult)
        timings = [
            events[i][0] - events[i - 1][0]
            for i in range(1, len(events))
        ]
    else:
        mapping_result, timings = _heartbeat_mapper(validator_json, session, args.heartbeat)
    map_elapsed = time.perf_counter() - t0
    print(f"[mapper] DONE total={map_elapsed:.1f}s anomalies={len(mapping_result.decisions)}")
    if timings:
        label = "between-completion" if args.executor else "per-anomaly"
        print(
            f"[mapper] {label}: p50={_percentile(timings, 0.5):.2f}s "
            f"p95={_percentile(timings, 0.95):.2f}s "
            f"max={max(timings):.2f}s min={min(timings):.2f}s"
        )
    methods = {}
    for d in mapping_result.decisions:
        methods[d.method] = methods.get(d.method, 0) + 1
    print(f"[mapper] method distribution: {methods}")

    if args.no_audit:
        print("[audit] skipped (--no-audit)")
        return 0

    # Step 4 — Audit (writes Excel + records metrics)
    t0 = time.perf_counter()
    map_step_output = ok(mapping_result)
    out = audit_executor(StepInput(previous_step_content=map_step_output.content), session_state)
    print(f"[audit] {time.perf_counter() - t0:.2f}s success={out.success}")
    if not out.success:
        print(f"[audit] FAILED: {out.content}", file=sys.stderr)
        return 1
    audit = deserialize(out.content, AuditResult)
    print(f"[audit] corrected={audit.corrected_count} review={audit.review_queue_count} hallucinations={audit.hallucination_count}")
    print(f"[audit] output={audit.output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
