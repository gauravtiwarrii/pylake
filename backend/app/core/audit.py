from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.entities import AuditLog


def record_audit(
    db: Session,
    workspace_id: UUID,
    actor_id: UUID | None,
    action: str,
    target_type: str,
    target_id: str | UUID | None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    item = AuditLog(
        workspace_id=workspace_id,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        metadata_json=metadata or {},
    )
    db.add(item)
    return item
