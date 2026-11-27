from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.v1.workspaces import membership
from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.db import get_db
from app.core.rate_limit import check_database_rate_limit
from app.impact.graph import build_graph
from app.impact.simulate import simulate_change
from app.models.entities import User
from app.schemas.impact import ImpactGraphResponse, ImpactSimulationRequest

logger = logging.getLogger("pylake.impact")
router = APIRouter(prefix="/workspaces", tags=["impact"])


@router.get("/{workspace_id}/impact/graph", response_model=ImpactGraphResponse)
def impact_graph(workspace_id: UUID, asset_id: UUID | None = None,
                 depth: int = Query(default=5, ge=1, le=10),
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    membership(db, workspace_id, user.id)
    try:
        return build_graph(db, workspace_id, asset_id, depth)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.post("/{workspace_id}/impact/simulate")
def impact_simulate(workspace_id: UUID, payload: ImpactSimulationRequest,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    membership(db, workspace_id, user.id)
    settings = get_settings()
    check_database_rate_limit(db, f"{workspace_id}:{user.id}", "impact_simulate",
                              attempts=getattr(settings, "impact_rate_limit_requests", 30),
                              window_seconds=3600)
    try:
        result = simulate_change(db, workspace_id, payload.asset_id, payload.change.model_dump(mode="json"), payload.depth)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    record_audit(db, workspace_id, user.id, "IMPACT_SIMULATED", "catalog_asset", result["asset_id"],
                 {"change_type": payload.change.type, "severity_counts": result["summary"]})
    db.commit()
    return result
