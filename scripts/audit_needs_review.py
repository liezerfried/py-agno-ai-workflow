"""
Audit harness: produces a detailed report on every anomaly that ends up in
the review queue, so we can inspect why the pipeline rejected the LLM's
proposed match (or refused to make one).

For each needs_review case it prints:
  - raw input as typed by the user
  - preprocessed form after pre_processor.normalize_title
  - the rapidfuzz top-3 candidates with scores
  - whether translation was attempted, and its result
  - the review_reason from the pipeline (low_confidence, llm_no_match,
    llm_hallucination, llm_error)

Run:
    .venv/Scripts/python.exe scripts/audit_needs_review.py data/test_100_autodetect.xlsx
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agno.db.sqlite import SqliteDb
from agno.tracing import setup_tracing

setup_tracing(db=SqliteDb(db_file="tmp/agentos.db"), batch_processing=True)

from agno.workflow import StepInput

from agents.ingest_agent import detect_job_column, ingest_executor, scan_headers
from agents.mapper_agent import _decide, _CONFIG
from agents.mapping_pipeline import score
from agents.translator_agent import translate
from agents.validator_agent import ValidatorResult, validator_executor
from infrastructure.pipeline.session import PipelineSession
from infrastructure.pipeline.step_io import deserialize
from workflows.normalization_workflow import load_valid_categories


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file")
    parser.add_argument("--column", help="Target column (default: auto-detect)")
    args = parser.parse_args()

    file_path = str(Path(args.file).resolve())

    if args.column:
        target_column = args.column
    else:
        scan = scan_headers(file_path)
        col, conf = detect_job_column(scan.column_names)
        if conf < 0.85:
            print(f"could not auto-detect column ({col!r}, score={conf})", file=sys.stderr)
            return 2
        target_column = col

    session = PipelineSession(
        file_path=file_path,
        target_column=target_column,
        valid_categories=load_valid_categories(),
    )
    ss = session.to_dict()

    ing = ingest_executor(StepInput(previous_step_content=None), ss)
    assert ing.success
    val = validator_executor(StepInput(previous_step_content=ing.content), ss)
    assert val.success
    vr = deserialize(val.content, ValidatorResult)

    print(f"file={Path(file_path).name}  target_column={target_column!r}")
    print(f"anomalies={len(vr.anomalies)}\n")

    # Re-decide per anomaly so we have access to fuzzy + translation detail
    # alongside the final decision. Bypasses _decide_cached on purpose so the
    # audit reflects a real LLM evaluation, not a previous cached result.
    # Parallelised at 4 workers — same setting as the production mapper, so
    # the audit finishes in ~3 min on 100 anomalies instead of ~6 in serial.
    by_reason: Counter[str] = Counter()
    details: list[dict] = []

    def evaluate(anomaly):
        decision = _decide(anomaly, session.valid_categories, session.valid_categories_set)
        if decision.method != "needs_review":
            return None
        fuzzy = score(anomaly.raw, session.valid_categories, _CONFIG)
        translation = translate(anomaly.raw) if decision.review_reason == "low_confidence" else None
        return {
            "raw": anomaly.raw,
            "preprocessed": fuzzy.preprocessed,
            "top_score": fuzzy.top_score,
            "candidates": fuzzy.candidates,
            "reason": decision.review_reason or "unknown",
            "translation": translation,
        }

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="audit") as ex:
        futures = {ex.submit(evaluate, a): a for a in vr.anomalies}
        completed = 0
        for future in as_completed(futures):
            completed += 1
            result = future.result()
            if completed % 10 == 0 or completed == len(vr.anomalies):
                print(f"  progress: {completed}/{len(vr.anomalies)}", flush=True)
            if result is None:
                continue
            details.append(result)
            by_reason[result["reason"]] += 1

    print(f"\nneeds_review total: {len(details)}")
    print(f"by_reason: {dict(by_reason)}\n")
    print("=" * 80)

    for d in details:
        print(f"raw          : {d['raw']!r}")
        print(f"preprocessed : {d['preprocessed']!r}")
        print(f"top_score    : {d['top_score']:.4f}")
        print(f"reason       : {d['reason']}")
        print(f"top-3 candidates:")
        for title, sc in d["candidates"]:
            print(f"  - {title!r} ({sc:.4f})")
        if d["translation"] is not None:
            t = d["translation"]
            print(f"translation  : {t.english_title!r}  was_translated={t.was_translated}  type={t.normalization_type}")
        print("-" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
