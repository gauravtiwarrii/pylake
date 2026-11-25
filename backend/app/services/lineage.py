from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.entities import LineageEdge


def record_lineage(
    db: Session,
    workspace_id: UUID,
    relation_type: str,
    source_type: str,
    source_id: str,
    target_type: str,
    target_id: str,
    source_asset_id: UUID | None = None,
    target_asset_id: UUID | None = None,
    execution_status: str | None = None,
    execution_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> LineageEdge:
    edge = LineageEdge(
        workspace_id=workspace_id,
        source_asset_id=source_asset_id,
        target_asset_id=target_asset_id,
        relation_type=relation_type,
        source_type=source_type,
        source_id=source_id,
        target_type=target_type,
        target_id=target_id,
        execution_status=execution_status,
        execution_id=execution_id,
        metadata_json=metadata or {},
    )
    db.add(edge)
    return edge
