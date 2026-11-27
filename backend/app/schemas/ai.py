from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


AIMode = Literal["simple", "detailed", "technical"]
AIPageType = Literal[
    "dashboard",
    "data",
    "dataset",
    "lakehouse",
    "quality",
    "lineage",
    "sql",
    "pipelines",
    "catalog",
    "audit",
    "workspace",
    "ai",
    "autopilot",
]


class AIStatusResponse(BaseModel):
    configured: bool
    provider: str
    model: str


class AIChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    conversation_id: UUID | None = None
    mode: AIMode = "detailed"
    dataset_id: UUID | None = None
    table_id: UUID | None = None
    pipeline_id: UUID | None = None
    catalog_asset_id: UUID | None = None
    page_type: AIPageType = "ai"
    active_view: str | None = Field(default=None, max_length=40)
    sql_text: str | None = Field(default=None, max_length=100000)


class AIRecommendationsRequest(BaseModel):
    page_type: AIPageType = "dashboard"
    active_view: str | None = Field(default=None, max_length=40)
    dataset_id: UUID | None = None
    table_id: UUID | None = None
    pipeline_id: UUID | None = None
    catalog_asset_id: UUID | None = None
    sql_text: str | None = Field(default=None, max_length=100000)


class AIRecommendationFeedbackRequest(BaseModel):
    decision: Literal["ACCEPTED", "REJECTED"]


class AIRecommendationResponse(BaseModel):
    id: UUID
    page_type: AIPageType
    category: str
    title: str
    description: str
    evidence: list[dict[str, str]]
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    expected_impact: str
    proposed_action: dict[str, Any]
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    required_permissions: list[str]
    approval_required: bool
    status: Literal["PROPOSED", "ACCEPTED", "REJECTED", "DISMISSED"]
    created_at: datetime


class AIMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    content: str
    created_at: datetime


class AIConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class AIConversationDetailResponse(AIConversationResponse):
    messages: list[AIMessageResponse]


class AIDatasetAnalysisResponse(BaseModel):
    dataset_id: UUID
    profile: dict[str, Any]
    explanation: str | None
    provider_available: bool
    ai_error: str | None = None


class AISQLGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    sql_text: str | None = Field(default=None, max_length=100000)


class AISQLTextRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=100000)
    error: str | None = Field(default=None, max_length=4000)


class AISQLResponse(BaseModel):
    sql: str | None = None
    explanation: str
    validated: bool = False


class AITransformationGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    dataset_id: UUID | None = None
    table_id: UUID | None = None

    @model_validator(mode="after")
    def require_resource(self) -> AITransformationGenerateRequest:
        if self.dataset_id is None and self.table_id is None:
            raise ValueError("A workspace dataset or lakehouse table is required")
        return self


class AITransformationDraftResponse(BaseModel):
    transformation_type: str
    configuration: dict[str, Any]
    target_layer: str
    explanation: str


class AIPipelineGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    dataset_id: UUID | None = None


class AIPipelineDraftResponse(BaseModel):
    name: str
    description: str | None
    status: str
    steps: list[dict[str, Any]]
    explanation: str


class AIUsageResponse(BaseModel):
    period_days: int
    requests: int
    input_tokens: int
    output_tokens: int
    token_limit_per_day: int
    tokens_reported: bool
