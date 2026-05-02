"""
Holds the shared, read-only state that all pipeline steps need to do their work.
Created once when a file is uploaded and passed through the Agno Workflow as session_state.
Invariant: valid_categories must be the complete O*NET list — a partial list will silently
reduce recall and cause valid categories to be flagged as anomalies.
"""
from __future__ import annotations

# dataclass auto-generates __init__, __repr__, and __eq__ from the field annotations below.
# frozen=True additionally prevents any field from being reassigned after construction —
# like a tuple but with named fields. Used here because all pipeline steps share this
# object and none of them should be able to mutate it.
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PipelineSession:
    """
    Immutable snapshot of everything the pipeline needs to process one uploaded file.

    Passed to every Step executor via Agno's session_state dict. Steps call
    PipelineSession.from_dict() to reconstruct a typed object from that dict.

    Fields:
        file_path:            Absolute path to the uploaded Excel workbook.
        target_column:        Name of the column that holds the raw job category values.
        valid_categories:     Full list of 923 O*NET canonical titles loaded from
                              data/valid_categories.csv. Used by ValidatorAgent and MapperAgent.
        valid_categories_set: Derived read-only set of the same titles. Provides O(1) membership
                              checks instead of O(n) list scans — critical for the
                              hallucination guard in AuditWriter.
    """
    file_path: str
    target_column: str
    valid_categories: list[str]
    # field(init=False) means this field is NOT accepted by the constructor.
    # It is computed automatically in __post_init__ from valid_categories.
    valid_categories_set: set[str] = field(init=False)

    def __post_init__(self) -> None:
        """
        Derive valid_categories_set from valid_categories right after construction.

        Python calls __post_init__ automatically after __init__ for dataclasses.
        Because this dataclass is frozen, normal field assignment raises a FrozenInstanceError —
        object.__setattr__ bypasses the freeze for this one-time derived-field initialization.
        """
        # Bypass the frozen guard to set a derived field exactly once at construction.
        object.__setattr__(self, "valid_categories_set", set(self.valid_categories))

    @classmethod
    def from_dict(cls, d: dict) -> PipelineSession:
        """
        Reconstruct a PipelineSession from the plain dict stored in Agno's session_state.

        Agno passes session state between steps as a plain Python dict, not as a
        PipelineSession object. Each Step executor calls this method to get a
        fully-typed session back, with valid_categories_set already computed.

        Args:
            d: Dictionary with keys "file_path", "target_column", and "valid_categories".
               Typically produced by a previous call to to_dict().

        Returns:
            A new PipelineSession with valid_categories_set already computed.
        """
        return cls(
            file_path=d["file_path"],
            target_column=d["target_column"],
            valid_categories=d["valid_categories"],
        )

    def to_dict(self) -> dict:
        """
        Serialize this session to a plain dict suitable for Agno's session_state.

        valid_categories_set is deliberately excluded — it is a derived field that
        can be cheaply recomputed from valid_categories by from_dict().

        Returns:
            A dict with three string-serializable keys: file_path, target_column,
            and valid_categories.
        """
        return {
            "file_path": self.file_path,
            "target_column": self.target_column,
            "valid_categories": self.valid_categories,
        }
