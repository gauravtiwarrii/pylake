from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    uploaded_by: UUID | None
    name: str
    original_filename: str
    description: str | None
    file_format: str
    mime_type: str
    file_size_bytes: int
    storage_backend: str
    ingestion_status: str
    ingestion_error: str | None
    schema_json: dict[str, Any] | None
    row_count: int | None
    column_count: int | None
    created_at: datetime
    updated_at: datetime


class DatasetListResponse(BaseModel):
    items: list[DatasetResponse]
    total: int
    page: int
    page_size: int


class PreviewResponse(BaseModel):
    columns: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    row_count: int
    returned_rows: int
