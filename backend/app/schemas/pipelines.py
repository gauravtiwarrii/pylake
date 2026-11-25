from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

StepType = Literal["SOURCE_DATASET", "TRANSFORM", "DATA_QUALITY", "SQL_QUERY", "MATERIALIZE"]


class PipelineStepInput(BaseModel):
    step_key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    step_type: StepType
    configuration: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    execution_order: int = Field(ge=1)


class PipelineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    status: Literal["DRAFT", "ACTIVE", "DISABLED"] = "DRAFT"
    steps: list[PipelineStepInput] = Field(default_factory=list)


class PipelineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    status: Literal["DRAFT", "ACTIVE", "DISABLED"] | None = None
    steps: list[PipelineStepInput] | None = None


class PipelineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    description: str | None
    status: str
    configuration_json: dict[str, Any]
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class ScheduleCreate(BaseModel):
    cron_expression: str = Field(min_length=9, max_length=200)
    timezone: str = "UTC"
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    cron_expression: str | None = Field(default=None, min_length=9, max_length=200)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
