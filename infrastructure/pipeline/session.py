from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PipelineSession:
    file_path: str
    target_column: str
    valid_categories: list[str]
    valid_categories_set: set[str] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "valid_categories_set", set(self.valid_categories))

    @classmethod
    def from_dict(cls, d: dict) -> PipelineSession:
        return cls(
            file_path=d["file_path"],
            target_column=d["target_column"],
            valid_categories=d["valid_categories"],
        )

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "target_column": self.target_column,
            "valid_categories": self.valid_categories,
        }