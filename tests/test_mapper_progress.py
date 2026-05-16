"""
Tests for MapperAgent progress reporting.

The mapper step processes anomalies serially; a 100-row file with mostly
LLM-band rows takes ~5 minutes wall clock. Without progress feedback the
caller (Chainlit UI, CLI) cannot distinguish "in progress" from "hung".
The progress callback is the seam through which the executor publishes
"i of total processed" without coupling to any specific UI.
"""
from __future__ import annotations

import time

from agno.workflow import StepInput

from agents.ingest_agent import IngestResult
from agents.mapper_agent import mapper_executor, set_progress_callback
from agents.validator_agent import validator_executor
from infrastructure.pipeline.contracts import CategoryValidation
from tests.conftest import VALID_CATEGORIES
from tests.test_integration_seams import _base_session, make_step_input


def _validator_output_for(categories: list[str]) -> str:
    """Run ingest → validate to produce a ValidatorResult JSON for the given categories."""
    ingest_result = IngestResult(
        file_path="dummy.xlsx",
        target_column="job_title",
        raw_categories=categories,
        total_rows=len(categories),
    )
    out = validator_executor(make_step_input(ingest_result.model_dump_json()), _base_session())
    assert out.success
    return out.content


def test_callback_invoked_with_zero_then_progress_then_total(stub_llm) -> None:
    """
    Callback receives (0, total) at the start, then (i, total) after each anomaly.
    The last call is always (total, total).
    """
    calls: list[tuple[int, int]] = []
    set_progress_callback(lambda processed, total: calls.append((processed, total)))
    try:
        # Three categories that are NOT in VALID_CATEGORIES → all become anomalies.
        # stub_llm returns 'not equivalent' so each goes to needs_review without real LLM.
        validator_content = _validator_output_for(["xyz1", "xyz2", "xyz3"])
        out = mapper_executor(StepInput(previous_step_content=validator_content), _base_session())
        assert out.success, out.content

        assert calls[0] == (0, 3), f"first call should be (0, total); got {calls[0]}"
        assert calls[-1] == (3, 3), f"last call should be (total, total); got {calls[-1]}"
        # All intermediate calls must keep the same total.
        assert all(t == 3 for _, t in calls)
        # processed must be monotonically non-decreasing.
        assert [p for p, _ in calls] == sorted(p for p, _ in calls)
    finally:
        set_progress_callback(None)


def test_no_callback_does_not_break_executor(stub_llm) -> None:
    """When no callback is registered, the executor still runs to completion."""
    set_progress_callback(None)  # explicit reset
    validator_content = _validator_output_for(["xyz1", "xyz2"])
    out = mapper_executor(StepInput(previous_step_content=validator_content), _base_session())
    assert out.success, out.content


def test_callback_isolation_between_runs(stub_llm) -> None:
    """Setting the callback to None after a run prevents stale calls leaking into later runs."""
    first_calls: list[tuple[int, int]] = []
    set_progress_callback(lambda p, t: first_calls.append((p, t)))
    try:
        validator_content = _validator_output_for(["xyz1"])
        mapper_executor(StepInput(previous_step_content=validator_content), _base_session())
        assert len(first_calls) >= 2  # at least (0,1) and (1,1)
    finally:
        set_progress_callback(None)

    # Second run with callback unset — no entries should be appended to first_calls.
    snapshot = list(first_calls)
    validator_content = _validator_output_for(["xyz2"])
    mapper_executor(StepInput(previous_step_content=validator_content), _base_session())
    assert first_calls == snapshot


def test_empty_anomaly_list_still_announces_zero_total(stub_llm) -> None:
    """Even when there are no anomalies, the callback fires once with (0, 0) so the UI can
    render a deterministic 'no work to do' state instead of disappearing."""
    calls: list[tuple[int, int]] = []
    set_progress_callback(lambda p, t: calls.append((p, t)))
    try:
        # All categories already valid — anomaly list is empty.
        already_valid = [c for c in VALID_CATEGORIES[:2]]
        validator_content = _validator_output_for(already_valid)
        out = mapper_executor(StepInput(previous_step_content=validator_content), _base_session())
        assert out.success
        assert calls == [(0, 0)], f"expected single (0, 0); got {calls}"
    finally:
        set_progress_callback(None)


# ── Concurrency (P1.2) ────────────────────────────────────────────────────────


def test_decisions_keep_input_order_under_concurrency(stub_llm, monkeypatch) -> None:
    """
    With concurrent _decide() calls, completion order is non-deterministic;
    decisions must still come out in the order the anomalies arrived. Audit
    writer relies on this lookup pattern indirectly (via raw->decision dict),
    but tests and downstream code that index by position must not see
    re-ordering.
    """
    monkeypatch.setenv("MAPPER_CONCURRENCY", "4")
    raws = [f"unknown_{i:02d}" for i in range(12)]
    validator_content = _validator_output_for(raws)
    out = mapper_executor(StepInput(previous_step_content=validator_content), _base_session())
    assert out.success, out.content

    from agents.mapper_agent import MappingResult
    result = MappingResult.model_validate_json(out.content)
    # Sorted in ingest_executor before validate; decisions must echo that order.
    assert [d.raw for d in result.decisions] == sorted(raws)


def test_progress_callback_is_thread_safe_and_reaches_total(stub_llm, monkeypatch) -> None:
    """
    Under concurrency the callback fires from worker threads. The pipeline
    must still reach (total, total) at the end and never report a count
    higher than total or out of bounds.
    """
    monkeypatch.setenv("MAPPER_CONCURRENCY", "4")
    calls: list[tuple[int, int]] = []
    set_progress_callback(lambda p, t: calls.append((p, t)))
    try:
        raws = [f"unknown_{i:02d}" for i in range(8)]
        validator_content = _validator_output_for(raws)
        out = mapper_executor(StepInput(previous_step_content=validator_content), _base_session())
        assert out.success
    finally:
        set_progress_callback(None)

    # First call is always (0, total); last is always (total, total).
    assert calls[0] == (0, 8)
    assert calls[-1] == (8, 8)
    # No call may exceed the total — guards against off-by-one in the counter.
    assert all(0 <= p <= 8 for p, _ in calls)
    assert all(t == 8 for _, t in calls)


def test_concurrency_env_one_falls_back_to_serial(stub_llm, monkeypatch) -> None:
    """
    MAPPER_CONCURRENCY=1 must execute serially (no thread pool overhead).
    This is the safe-default path for environments where parallel LLM calls
    are undesirable — local dev with a tiny model, or strict rate limits.
    """
    monkeypatch.setenv("MAPPER_CONCURRENCY", "1")
    raws = [f"unknown_{i:02d}" for i in range(3)]
    validator_content = _validator_output_for(raws)
    out = mapper_executor(StepInput(previous_step_content=validator_content), _base_session())
    assert out.success, out.content


def test_invalid_concurrency_value_falls_back_to_default(stub_llm, monkeypatch) -> None:
    """A non-integer MAPPER_CONCURRENCY does not abort the run."""
    monkeypatch.setenv("MAPPER_CONCURRENCY", "not-a-number")
    raws = [f"unknown_{i:02d}" for i in range(3)]
    validator_content = _validator_output_for(raws)
    out = mapper_executor(StepInput(previous_step_content=validator_content), _base_session())
    assert out.success, out.content


def test_anomalies_actually_run_in_parallel(monkeypatch) -> None:
    """
    Wall-clock test that detects whether the executor is genuinely concurrent.
    With MAPPER_CONCURRENCY=4 and 8 anomalies each sleeping 0.4s, total
    elapsed must be closer to 0.8s (two batches) than 3.2s (serial). The
    threshold of 2.0s gives generous margin for thread pool overhead while
    still failing loudly if the implementation regresses to serial.
    """
    from agents import mapper_agent
    from agents.mapper_agent import MappingDecision

    sleep_per_call = 0.4

    def slow_decide(anomaly: CategoryValidation, valid_categories, valid_set, **kwargs) -> MappingDecision:
        time.sleep(sleep_per_call)
        return MappingDecision(
            raw=anomaly.raw,
            preprocessed=anomaly.raw,
            corrected=None,
            confidence=0.0,
            method="needs_review",
            normalization_type="unknown",
            needs_review=True,
            review_reason="test_stub",
        )

    monkeypatch.setattr(mapper_agent, "_decide", slow_decide)
    monkeypatch.setenv("MAPPER_CONCURRENCY", "4")

    raws = [f"unknown_{i:02d}" for i in range(8)]
    validator_content = _validator_output_for(raws)

    t0 = time.perf_counter()
    out = mapper_executor(StepInput(previous_step_content=validator_content), _base_session())
    elapsed = time.perf_counter() - t0

    assert out.success
    serial_estimate = len(raws) * sleep_per_call
    assert elapsed < serial_estimate / 2, (
        f"Expected concurrent execution; got {elapsed:.2f}s "
        f"(serial would be ~{serial_estimate:.2f}s)"
    )
