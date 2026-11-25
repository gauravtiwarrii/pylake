from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

LakehouseLayer = Literal["BRONZE", "SILVER", "GOLD"]


class LakehouseTableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    description: str | None
    current_layer: str
    created_at: datetime
    updated_at: datetime


class DatasetVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_id: UUID
    lakehouse_table_id: UUID | None
    version_number: int
    layer: str
    storage_key: str
    schema_json: dict[str, Any] | None
    row_count: int | None
    column_count: int | None
    file_size_bytes: int
    file_format: str
    checksum: str | None
    created_by: UUID | None
    created_at: datetime
    status: str


class PromoteRequest(BaseModel):
    target_layer: LakehouseLayer
    source_version_id: UUID | None = None
    partition_columns: list[str] = Field(default_factory=list, max_length=4)


class TransformRequest(BaseModel):
    source_version_id: UUID | None = None
    transformation_type: Literal["rename", "drop", "cast", "deduplicate", "filter", "fill_null", "normalize_names", "calculated", "select", "sort"]
    configuration: dict[str, Any] = Field(default_factory=dict)
    target_layer: LakehouseLayer = "SILVER"
