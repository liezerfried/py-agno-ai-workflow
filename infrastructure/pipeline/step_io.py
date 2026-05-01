from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from agno.workflow import StepOutput

T = TypeVar("T", bound=BaseModel)


def deserialize(content: str, model_class: type[T]) -> T:
    return model_class.model_validate_json(content)


def ok(result: BaseModel) -> StepOutput:
    return StepOutput(content=result.model_dump_json())


def fail(exc: Exception) -> StepOutput:
    return StepOutput(content=str(exc), success=False, stop=True)