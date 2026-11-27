from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


ChangeType = Literal["rename_column", "drop_column", "change_type", "rename_table", "drop_table",
                     "change_transformation", "remove_pipeline_step"]


class ImpactChange(BaseModel):
    type: ChangeType
    column: str | None = Field(default=None, max_length=200)
    new_name: str | None = Field(default=None, max_length=200)
    new_type: str | None = Field(default=None, max_length=100)
    step_id: UUID | None = None

    @model_validator(mode="after")
    def validate_change(self):
        if self.type == "rename_column" and (not self.column or not self.new_name):
            raise ValueError("rename_column requires column and new_name")
        if self.type in {"drop_column", "change_type"} and not self.column:
            raise ValueError(f"{self.type} requires column")
        if self.type == "change_type" and not self.new_type:
            raise ValueError("change_type requires new_type")
        if self.type == "rename_table" and not self.new_name:
            raise ValueError("rename_table requires new_name")
        if self.type in {"remove_pipeline_step", "change_transformation"} and not self.step_id:
            raise ValueError(f"{self.type} requires step_id")
        return self


class ImpactSimulationRequest(BaseModel):
    asset_id: UUID
    change: ImpactChange
    depth: int = Field(default=5, ge=1, le=10)


class ImpactGraphResponse(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    depth: int
    truncated: bool
    uncovered: list[str]

