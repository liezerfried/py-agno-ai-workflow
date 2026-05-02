"""
Thin helpers that serialize/deserialize Pydantic models into Agno StepOutput objects.
Used by every Step executor in the pipeline to avoid repeating the same boilerplate in each file.
The ok/fail pattern lets steps signal success or failure uniformly without raising exceptions.
"""
from __future__ import annotations

from typing import TypeVar

# Pydantic is a data-validation library. BaseModel is its base class.
# All pipeline result types (IngestResult, ValidatorResult, etc.) extend BaseModel
# so that Pydantic validates their fields automatically when they are constructed.
from pydantic import BaseModel

# StepOutput is the object every Agno Step executor must return.
# Agno reads its .content field to pass data to the next Step.
from agno.workflow import StepOutput

# T is a generic placeholder meaning "any class that extends BaseModel".
# This lets deserialize() return the correct concrete type
# (e.g. IngestResult, ValidatorResult) without needing a separate function for each.
T = TypeVar("T", bound=BaseModel)


def deserialize(content: str, model_class: type[T]) -> T:
    """
    Parse a JSON string back into a typed Pydantic model.

    Agno passes data between Steps as JSON strings stored in StepOutput.content.
    Call this at the start of each executor to turn the raw string into a
    fully-typed, validated Python object.

    Args:
        content: A JSON string produced by a previous ok() call (via model_dump_json()).
        model_class: The Pydantic model class to parse into (e.g. IngestResult).
                     Pydantic will raise a ValidationError if the JSON does not match
                     the class's field definitions.

    Returns:
        A new instance of model_class with all fields populated and validated.
    """
    return model_class.model_validate_json(content)


def ok(result: BaseModel) -> StepOutput:
    """
    Wrap a successful Pydantic result in an Agno StepOutput.

    The pipeline uses this wrapper instead of returning raw strings so that every
    step has a consistent, typed way to signal success to the next step.
    The result is serialized to JSON so Agno can pass it across step boundaries.

    Args:
        result: Any Pydantic model instance (e.g. ValidatorResult, MappingResult).

    Returns:
        A StepOutput whose .content is the JSON-serialized result.
        The next Step receives this and calls deserialize() to unpack it.
    """
    return StepOutput(content=result.model_dump_json())


def fail(exc: Exception) -> StepOutput:
    """
    Wrap an exception in a failed Agno StepOutput, stopping the pipeline.

    Using a result wrapper instead of re-raising the exception allows the Workflow
    to record what went wrong before halting, rather than crashing abruptly.
    stop=True tells Agno not to execute any further steps.

    Args:
        exc: The exception that caused this step to fail.

    Returns:
        A StepOutput with success=False and stop=True. The exception message is
        stored in .content so it can be logged or surfaced to the user.
    """
    return StepOutput(content=str(exc), success=False, stop=True)
