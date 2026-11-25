from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.v1.workspaces import membership, require_role
from app.core.config import get_settings
from app.core.db import get_db
from app.models.entities import (
    AuditLog,
    PipelineRun,
    PipelineStepRun,
    RunStatus,
    User,
    WorkerHeartbeat,
    WorkspaceRole,
)

router = APIRouter(prefix="/workspaces", tags=["observability"])


@router.get("/{workspace_id}/pipelines/metrics")
def pipeline_metrics(
    workspace_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    membership(db, workspace_id, user.id)
    runs = db.query(PipelineRun).filter(PipelineRun.workspace_id == workspace_id).all()
    statuses = {status.value: 0 for status in RunStatus}
    durations = [run.duration_ms for run in runs if run.duration_ms is not None]
    step_runs = db.query(PipelineStepRun).join(PipelineRun).filter(
        PipelineRun.workspace_id == workspace_id
    ).all()
    step_durations = [row.duration_ms for row in step_runs if row.duration_ms is not None]
    for run in runs:
        statuses[run.status.value] += 1
    return {
        "total_runs": len(runs),
        "status_distribution": statuses,
        "average_duration_ms": int(sum(durations) / len(durations)) if durations else 0,
        "total_duration_ms": sum(durations),
        "average_step_duration_ms": int(sum(step_durations) / len(step_durations)) if step_durations else 0,
        "retry_count": sum(run.retry_count for run in runs),
        "last_successful_run": max((run.completed_at for run in runs if run.status == RunStatus.SUCCEEDED), default=None),
        "last_failed_run": max((run.completed_at for run in runs if run.status == RunStatus.FAILED), default=None),
    }


@router.get("/{workspace_id}/workers/health")
def worker_health(
    workspace_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    require_role(db, workspace_id, user, WorkspaceRole.ADMIN)
    settings = get_settings()
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=settings.worker_stale_seconds)
    workers = db.query(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen_at.desc()).all()
    return {
        "workers": [
            {
                "worker_id": worker.worker_id,
                "last_seen_at": worker.last_seen_at,
                "status": "STALE" if worker.last_seen_at < cutoff else worker.status,
                "active_job_id": worker.active_job_id,
            }
            for worker in workers
        ]
    }


@router.get("/{workspace_id}/audit")
def audit_logs(
    workspace_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    require_role(db, workspace_id, user, WorkspaceRole.ADMIN)
    query = db.query(AuditLog).filter(AuditLog.workspace_id == workspace_id)
    total = query.count()
    items = query.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [
            {
                "id": str(item.id),
                "actor_id": str(item.actor_id) if item.actor_id else None,
                "action": item.action,
                "target_type": item.target_type,
                "target_id": item.target_id,
                "metadata": item.metadata_json,
                "created_at": item.created_at,
            }
            for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
