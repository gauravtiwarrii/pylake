from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SQLExecuteRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=100_000)
    query_name: str | None = Field(default=None, max_length=200)
    limit: int | None = Field(default=None, ge=1, le=1000)


class SQLAnalyzeRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=100_000)


class SQLColumn(BaseModel):
    name: str
    type: str


class SQLExecuteResponse(BaseModel):
    id: UUID
    status: str
    duration_ms: int
    columns: list[SQLColumn]
    rows: list[dict[str, Any]]
    returned_rows: int
    total_rows_available: int
    truncated: bool
    error: str | None = None


class QueryHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    user_id: UUID
    query_name: str | None
    sql_text: str
    execution_status: str
    execution_duration_ms: int | None
    rows_returned: int | None
    error_message: str | None
    created_at: datetime


class SavedQueryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    sql_text: str = Field(min_length=1, max_length=100_000)


class SavedQueryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    sql_text: str | None = Field(default=None, min_length=1, max_length=100_000)


class SavedQueryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    user_id: UUID
    name: str
    description: str | None
    sql_text: str
    created_at: datetime
    updated_at: datetime
