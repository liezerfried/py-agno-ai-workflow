"""
Tests for session_id propagation from the workflow down to inner agent calls.

Why: the AgentOS UI groups runs into sessions. When a workflow.run() spawns
nested agent.run() calls inside its executors, those inner calls create their
own sessions unless we forward the parent session_id explicitly. Result in the
UI: a single user upload showed up as 4 separate sessions (mapperagent x 2 +
translatoragent x 2) instead of one cohesive workflow session.

These tests pin the new contract:
  - mapper_executor reads `workflow_session_id` from session_state and forwards
    it to both _decide_cached and _handle_llm
  - translate() accepts an optional session_id kwarg and forwards it to
    agent.run()
  - When no session_id is present, all paths still work (backward-compatible).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agno.workflow import StepInput

from agents.ingest_agent import IngestResult
from agents.mapper_agent import (
    MappingResult,
    SemanticMatch,
    mapper_executor,
)
from agents.translator_agent import (
    TranslationResult,
    set_agent as set_translator_agent,
    translate,
)
from agents.validator_agent import validator_executor
from tests.conftest import VALID_CATEGORIES
from tests.test_integration_seams import _base_session, make_step_input


def _validator_output_for(categories: list[str]) -> str:
    ingest_result = IngestResult(
        file_path="dummy.xlsx",
        target_column="job_title",
        raw_categories=categories,
        total_rows=len(categories),
    )
    out = validator_executor(make_step_input(ingest_result.model_dump_json()), _base_session())
    assert out.success
    return out.content


def test_translate_forwards_session_id_to_agent_run() -> None:
    """When translate(raw, session_id=...) is called, the underlying agent.run
    must receive the same session_id as a kwarg."""
    stub = MagicMock()
    stub_result = MagicMock()
    stub_result.content = TranslationResult(
        english_title="X", was_translated=True, normalization_type="language"
    )
    stub.run.return_value = stub_result
    set_translator_agent(stub)
    try:
        translate("Desarrollador Backend", session_id="workflow-session-abc")
        # Inspect how stub.run was called
        call_kwargs = stub.run.call_args.kwargs
        assert call_kwargs.get("session_id") == "workflow-session-abc", (
            f"translate() must forward session_id to agent.run(); got kwargs={call_kwargs}"
        )
    finally:
        set_translator_agent(None)


def test_translate_without_session_id_omits_kwarg() -> None:
    """Backward compatibility: callers that do not pass session_id keep the
    historical signature — agent.run() is called without that kwarg."""
    stub = MagicMock()
    stub_result = MagicMock()
    stub_result.content = TranslationResult(
        english_title="X", was_translated=True, normalization_type="language"
    )
    stub.run.return_value = stub_result
    set_translator_agent(stub)
    try:
        translate("Desarrollador Backend")
        call_kwargs = stub.run.call_args.kwargs
        assert "session_id" not in call_kwargs, (
            f"Without an explicit session_id, agent.run() must not receive the kwarg; got {call_kwargs}"
        )
    finally:
        set_translator_agent(None)


def test_mapper_executor_forwards_workflow_session_id_to_llm(monkeypatch) -> None:
    """
    Given session_state contains workflow_session_id, mapper_executor must
    forward it to the MapperAgent.run() call inside _handle_llm.
    """
    # Force a single anomaly that lands in the LLM band so _handle_llm runs.
    monkeypatch.setenv("MAPPER_CONCURRENCY", "1")
    monkeypatch.setattr(
        "agents.mapping_pipeline.process.extract",
        lambda *a, **kw: [("Human Resources Managers", 78, 0)],
    )

    semantic = SemanticMatch(
        is_equivalent=True,
        canonical_title="Human Resources Managers",
        normalization_type="abbreviation",
    )
    mock_run = MagicMock()
    mock_run.content = semantic
    mock_agent = MagicMock()
    mock_agent.run.return_value = mock_run

    session = _base_session()
    session["workflow_session_id"] = "wf-session-xyz"

    validator_content = _validator_output_for(["RRHH"])

    with patch("agents.mapper_agent._mapper_agent", mock_agent):
        out = mapper_executor(
            StepInput(previous_step_content=validator_content), session
        )

    assert out.success
    assert mock_agent.run.called, "MapperAgent.run was never invoked"
    call_kwargs = mock_agent.run.call_args.kwargs
    assert call_kwargs.get("session_id") == "wf-session-xyz", (
        f"_handle_llm must forward workflow_session_id to MapperAgent.run; got kwargs={call_kwargs}"
    )


def test_mapper_executor_without_workflow_session_id_still_works(monkeypatch, stub_llm) -> None:
    """
    Backward compatibility: when session_state lacks workflow_session_id, the
    executor must still complete successfully (existing Chainlit path).
    """
    monkeypatch.setenv("MAPPER_CONCURRENCY", "1")
    raws = ["xyz_no_session_1", "xyz_no_session_2"]
    validator_content = _validator_output_for(raws)
    out = mapper_executor(
        StepInput(previous_step_content=validator_content), _base_session()
    )
    assert out.success
    result = MappingResult.model_validate_json(out.content)
    assert len(result.decisions) == 2
