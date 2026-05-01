from __future__ import annotations


class PipelineError(Exception):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"Pipeline failed at {stage}: {message}")
        self.stage = stage
        self.message = message