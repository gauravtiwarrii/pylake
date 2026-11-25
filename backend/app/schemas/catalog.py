from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CatalogColumnUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=1000)
    business_name: str | None = Field(default=None, max_length=200)
    glossary_term: str | None = Field(default=None, max_length=200)


class CatalogAssetUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=1000)
    tags: list[str] | None = Field(default=None, max_length=50)
    owner_id: UUID | None = None


class CatalogColumnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    data_type: str | None
    description: str | None
    business_name: str | None
    glossary_term: str | None


class CatalogAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    asset_type: str
    name: str
    description: str | None
    owner_id: UUID | None
    tags_json: list[str]
    format: str | None
    layer: str | None
    dataset_id: UUID | None
    lakehouse_table_id: UUID | None
    created_at: datetime
    updated_at: datetime


class CatalogListResponse(BaseModel):
    items: list[CatalogAssetResponse]
    total: int
    page: int
    page_size: int
