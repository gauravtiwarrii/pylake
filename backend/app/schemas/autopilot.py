from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


AutopilotPlanStatus = Literal[
    "DRAFT", "PREVIEWED", "APPROVED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"
]
AutopilotStepStatus = Literal[
    "PENDING", "SKIPPED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"
]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]


class AutopilotStepInput(BaseModel):
    action_key: str = Field(min_length=1, max_length=60)
    title: str | None = Field(default=None, max_length=200)
    rationale: str | None = Field(default=None, max_length=2000)
    arguments: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, str]] | None = None
    risk_level: RiskLevel | None = None


class AutopilotPlanCreate(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    dataset_id: UUID | None = None
    table_id: UUID | None = None
    steps: list[AutopilotStepInput] | None = None


class AutopilotApproveRequest(BaseModel):
    plan_hash: str = Field(min_length=64, max_length=64)


class AutopilotStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    step_order: int
    action_key: str
    title: str
    rationale: str | None
    arguments_json: dict[str, Any]
    evidence_json: list | None
    preview_json: dict[str, Any] | None
    risk_level: RiskLevel
    requires_approval: bool
    status: AutopilotStepStatus
    result_json: dict[str, Any] | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None


class AutopilotPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    created_by: UUID | None
    goal: str
    status: AutopilotPlanStatus
    plan_hash: str | None
    ai_provider: str | None
    ai_model: str | None
    approved_by: UUID | None
    approved_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    report_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    steps: list[AutopilotStepResponse] = Field(default_factory=list)
