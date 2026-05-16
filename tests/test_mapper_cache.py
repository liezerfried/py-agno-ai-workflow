"""
Tests for the MapperAgent decision cache.

Run-to-run variance was the last residual annoyance after the cuelgue fix:
identical input files would give 78/75/74 corrected on consecutive runs.
With temperature=0 the model layer is deterministic; the cache makes the
pipeline layer skip work it already did, both within a single run (duplicate
anomalies after dedup) and across runs in the same process.
"""
from __future__ import annotations

from agno.workflow import StepInput

from agents import mapper_agent
from agents.mapper_agent import (
    MappingResult,
    clear_decision_cache,
    mapper_executor,
)
from infrastructure.pipeline.contracts import CategoryValidation
from tests.test_integration_seams import _base_session, make_step_input
from tests.test_mapper_progress import _validator_output_for


def test_repeated_raw_calls_decide_once(stub_llm, monkeypatch) -> None:
    """
    Two invocations of mapper_executor with the same anomaly raw should
    call the underlying _decide() function only once — the second go is
    served from the cache.
    """
    clear_decision_cache()
    call_log: list[str] = []
    real_decide = mapper_agent._decide

    def counting_decide(anomaly: CategoryValidation, valid_categories, valid_set, **kwargs):
        call_log.append(anomaly.raw)
        return real_decide(anomaly, valid_categories, valid_set, **kwargs)

    monkeypatch.setattr(mapper_agent, "_decide", counting_decide)
    # Serial path keeps the assertion simple — no race with the thread pool.
    monkeypatch.setenv("MAPPER_CONCURRENCY", "1")

    validator_content = _validator_output_for(["xyz_unique_one"])

    first = mapper_executor(StepInput(previous_step_content=validator_content), _base_session())
    second = mapper_executor(StepInput(previous_step_content=validator_content), _base_session())

    assert first.success and second.success
    assert call_log == ["xyz_unique_one"], (
        f"_decide should be called exactly once for repeated raws; got {call_log}"
    )

    # Both runs must produce identical decisions — that is the point of the cache.
    first_decisions = MappingResult.model_validate_json(first.content).decisions
    second_decisions = MappingResult.model_validate_json(second.content).decisions
    assert first_decisions == second_decisions


def test_distinct_raws_each_get_their_own_decide_call(stub_llm, monkeypatch) -> None:
    """Cache must not collapse distinct anomalies — each unique raw needs its own decision."""
    clear_decision_cache()
    call_log: list[str] = []
    real_decide = mapper_agent._decide

    def counting_decide(anomaly: CategoryValidation, valid_categories, valid_set, **kwargs):
        call_log.append(anomaly.raw)
        return real_decide(anomaly, valid_categories, valid_set, **kwargs)

    monkeypatch.setattr(mapper_agent, "_decide", counting_decide)
    monkeypatch.setenv("MAPPER_CONCURRENCY", "1")

    validator_content = _validator_output_for(["xyz_a", "xyz_b", "xyz_c"])
    out = mapper_executor(StepInput(previous_step_content=validator_content), _base_session())

    assert out.success
    assert sorted(call_log) == ["xyz_a", "xyz_b", "xyz_c"]


def test_clear_decision_cache_resets_state(stub_llm, monkeypatch) -> None:
    """After clear_decision_cache(), the next call must recompute, not reuse the old decision."""
    clear_decision_cache()
    call_log: list[str] = []
    real_decide = mapper_agent._decide

    def counting_decide(anomaly, valid_categories, valid_set, **kwargs):
        call_log.append(anomaly.raw)
        return real_decide(anomaly, valid_categories, valid_set, **kwargs)

    monkeypatch.setattr(mapper_agent, "_decide", counting_decide)
    monkeypatch.setenv("MAPPER_CONCURRENCY", "1")

    validator_content = _validator_output_for(["xyz_reset"])

    mapper_executor(StepInput(previous_step_content=validator_content), _base_session())
    assert call_log == ["xyz_reset"]

    clear_decision_cache()
    mapper_executor(StepInput(previous_step_content=validator_content), _base_session())
    assert call_log == ["xyz_reset", "xyz_reset"], (
        f"clear_decision_cache should force recomputation; got {call_log}"
    )


def test_cache_survives_concurrency(stub_llm, monkeypatch) -> None:
    """
    Under MAPPER_CONCURRENCY>1, the cache must still serve hits and not
    corrupt itself. A repeated raw should be computed at most once even
    when workers race to fill the same key.
    """
    clear_decision_cache()
    call_log: list[str] = []
    real_decide = mapper_agent._decide

    def counting_decide(anomaly, valid_categories, valid_set, **kwargs):
        call_log.append(anomaly.raw)
        return real_decide(anomaly, valid_categories, valid_set, **kwargs)

    monkeypatch.setattr(mapper_agent, "_decide", counting_decide)
    monkeypatch.setenv("MAPPER_CONCURRENCY", "4")

    # Two distinct raws, repeated to force cache hits in a single run after
    # the first occurrence of each. ingest_executor dedups upstream, so the
    # second mapper_executor call below is what exercises across-run reuse.
    validator_content = _validator_output_for(["dup_a", "dup_b"])

    mapper_executor(StepInput(previous_step_content=validator_content), _base_session())
    mapper_executor(StepInput(previous_step_content=validator_content), _base_session())

    # First run computes both; second run is fully cached. Total: 2 _decide calls.
    assert sorted(call_log) == ["dup_a", "dup_b"], (
        f"Expected one _decide call per unique raw across both runs; got {call_log}"
    )
