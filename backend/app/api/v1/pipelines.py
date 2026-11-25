from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import UUID

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.v1.workspaces import membership, require_role
from app.core.db import get_db
from app.models.entities import (
    Pipeline,
    PipelineRun,
    PipelineSchedule,
    PipelineStatus,
    PipelineStep,
    PipelineStepRun,
    RunStatus,
    StepStatus,
    User,
    WorkspaceRole,
)
from app.schemas.pipelines import (
    PipelineCreate,
    PipelineUpdate,
    ScheduleCreate,
    ScheduleUpdate,
)
from app.services.pipeline_graph import PipelineGraphError, validate_pipeline_graph
from app.models.entities import AuditLog, WorkerHeartbeat, PipelineStepRun
from app.core.audit import record_audit

router = APIRouter(prefix="/workspaces", tags=["pipelines"])


def scoped_pipeline(db: Session, workspace_id: UUID, pipeline_id: UUID) -> Pipeline:
    item = db.query(Pipeline).filter(Pipeline.id == pipeline_id, Pipeline.workspace_id == workspace_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")
    return item


def replace_steps(db: Session, pipeline: Pipeline, step_inputs: list) -> None:
    db.query(PipelineStep).filter(PipelineStep.pipeline_id == pipeline.id).delete()
    db.flush()
    for step in sorted(step_inputs, key=lambda item: item.execution_order):
        db.add(PipelineStep(
            pipeline_id=pipeline.id,
            step_key=step.step_key,
            name=step.name,
            step_type=step.step_type,
            configuration_json=step.configuration,
            dependencies_json=step.dependencies,
            execution_order=step.execution_order,
        ))


@router.post("/{workspace_id}/pipelines", status_code=status.HTTP_201_CREATED)
def create_pipeline(payload: PipelineCreate, workspace_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    if db.query(Pipeline).filter(Pipeline.workspace_id == workspace_id, Pipeline.name == payload.name).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A pipeline with this name already exists")
    steps = [step.model_dump() for step in payload.steps]
    try:
        validate_pipeline_graph(steps)
    except PipelineGraphError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    pipeline = Pipeline(
        workspace_id=workspace_id,
        name=payload.name.strip(),
        description=payload.description,
        status=PipelineStatus(payload.status),
        configuration_json={},
        created_by=user.id,
    )
    db.add(pipeline)
    db.flush()
    replace_steps(db, pipeline, payload.steps)
    record_audit(db, workspace_id, user.id, "PIPELINE_CREATED", "pipeline", pipeline.id)
    db.commit()
    db.refresh(pipeline)
    return pipeline


@router.get("/{workspace_id}/pipelines")
def list_pipelines(workspace_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    membership(db, workspace_id, user.id)
    return db.query(Pipeline).filter(Pipeline.workspace_id == workspace_id).order_by(Pipeline.updated_at.desc()).all()


@router.get("/{workspace_id}/pipelines/{pipeline_id}")
def get_pipeline(workspace_id: UUID, pipeline_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    membership(db, workspace_id, user.id)
    pipeline = scoped_pipeline(db, workspace_id, pipeline_id)
    steps = db.query(PipelineStep).filter(PipelineStep.pipeline_id == pipeline.id).order_by(PipelineStep.execution_order).all()
    return {"pipeline": pipeline, "steps": steps}


@router.patch("/{workspace_id}/pipelines/{pipeline_id}")
def update_pipeline(workspace_id: UUID, pipeline_id: UUID, payload: PipelineUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    pipeline = scoped_pipeline(db, workspace_id, pipeline_id)
    if payload.name is not None:
        duplicate = db.query(Pipeline).filter(Pipeline.workspace_id == workspace_id, Pipeline.name == payload.name, Pipeline.id != pipeline.id).first()
        if duplicate:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A pipeline with this name already exists")
        pipeline.name = payload.name.strip()
    if payload.description is not None:
        pipeline.description = payload.description
    if payload.status is not None:
        pipeline.status = PipelineStatus(payload.status)
    if payload.steps is not None:
        steps = [step.model_dump() for step in payload.steps]
        try:
            validate_pipeline_graph(steps)
        except PipelineGraphError as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
        replace_steps(db, pipeline, payload.steps)
    record_audit(db, workspace_id, user.id, "PIPELINE_UPDATED", "pipeline", pipeline.id)
    db.commit()
    db.refresh(pipeline)
    return pipeline


@router.delete("/{workspace_id}/pipelines/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pipeline(workspace_id: UUID, pipeline_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(db, workspace_id, user, WorkspaceRole.ADMIN)
    pipeline = scoped_pipeline(db, workspace_id, pipeline_id)
    record_audit(db, workspace_id, user.id, "PIPELINE_DELETED", "pipeline", pipeline.id)
    db.delete(pipeline)
    db.commit()


@router.post("/{workspace_id}/pipelines/{pipeline_id}/validate")
def validate_pipeline(workspace_id: UUID, pipeline_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    membership(db, workspace_id, user.id)
    pipeline = scoped_pipeline(db, workspace_id, pipeline_id)
    steps = db.query(PipelineStep).filter(PipelineStep.pipeline_id == pipeline.id).all()
    payload = [{
        "step_key": step.step_key,
        "name": step.name,
        "step_type": step.step_type,
        "dependencies": step.dependencies_json,
        "execution_order": step.execution_order,
    } for step in steps]
    try:
        ordered = validate_pipeline_graph(payload)
    except PipelineGraphError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    return {"valid": True, "execution_order": [step["step_key"] for step in ordered]}


@router.post("/{workspace_id}/pipelines/{pipeline_id}/runs", status_code=status.HTTP_202_ACCEPTED)
def create_run(workspace_id: UUID, pipeline_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    pipeline = scoped_pipeline(db, workspace_id, pipeline_id)
    run = PipelineRun(pipeline_id=pipeline.id, workspace_id=workspace_id, triggered_by=user.id, status=RunStatus.QUEUED)
    db.add(run)
    record_audit(db, workspace_id, user.id, "PIPELINE_EXECUTION_STARTED", "pipeline_run", run.id)
    db.commit()
    db.refresh(run)
    return run


@router.get("/{workspace_id}/pipelines/{pipeline_id}/runs")
def list_runs(workspace_id: UUID, pipeline_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    membership(db, workspace_id, user.id)
    scoped_pipeline(db, workspace_id, pipeline_id)
    return db.query(PipelineRun).filter(PipelineRun.pipeline_id == pipeline_id).order_by(PipelineRun.created_at.desc()).all()


@router.get("/{workspace_id}/pipelines/runs/{run_id}")
def get_run(workspace_id: UUID, run_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    membership(db, workspace_id, user.id)
    run = db.query(PipelineRun).filter(PipelineRun.id == run_id, PipelineRun.workspace_id == workspace_id).first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline run not found")
    return run


@router.get("/{workspace_id}/pipelines/runs/{run_id}/logs")
def run_logs(workspace_id: UUID, run_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    membership(db, workspace_id, user.id)
    run = db.query(PipelineRun).filter(PipelineRun.id == run_id, PipelineRun.workspace_id == workspace_id).first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline run not found")
    steps = db.query(PipelineStepRun).filter(PipelineStepRun.pipeline_run_id == run.id).all()
    return {"run": run, "steps": steps}


@router.post("/{workspace_id}/pipelines/runs/{run_id}/cancel")
def cancel_run(workspace_id: UUID, run_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    run = db.query(PipelineRun).filter(PipelineRun.id == run_id, PipelineRun.workspace_id == workspace_id).first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline run not found")
    if run.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only active runs can be cancelled")
    run.status = RunStatus.CANCELLED
    run.completed_at = datetime.utcnow()
    record_audit(db, workspace_id, user.id, "PIPELINE_CANCELLED", "pipeline_run", run.id)
    db.commit()
    return run


def next_schedule(cron_expression: str, timezone_name: str):
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid timezone")
    if not croniter.is_valid(cron_expression):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cron expression")
    now = datetime.now(tz)
    return croniter(cron_expression, now).get_next(datetime)


@router.post("/{workspace_id}/pipelines/{pipeline_id}/schedules", status_code=status.HTTP_201_CREATED)
def create_schedule(workspace_id: UUID, pipeline_id: UUID, payload: ScheduleCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    scoped_pipeline(db, workspace_id, pipeline_id)
    next_run = next_schedule(payload.cron_expression, payload.timezone)
    schedule = PipelineSchedule(
        pipeline_id=pipeline_id,
        workspace_id=workspace_id,
        cron_expression=payload.cron_expression,
        timezone=payload.timezone,
        enabled=payload.enabled,
        next_run_at=next_run.replace(tzinfo=None),
    )
    db.add(schedule)
    record_audit(db, workspace_id, user.id, "PIPELINE_SCHEDULE_CREATED", "schedule", schedule.id)
    db.commit()
    db.refresh(schedule)
    return schedule


@router.get("/{workspace_id}/pipelines/{pipeline_id}/schedules")
def list_schedules(workspace_id: UUID, pipeline_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    membership(db, workspace_id, user.id)
    scoped_pipeline(db, workspace_id, pipeline_id)
    return db.query(PipelineSchedule).filter(PipelineSchedule.pipeline_id == pipeline_id).all()


@router.patch("/{workspace_id}/pipelines/schedules/{schedule_id}")
def update_schedule(workspace_id: UUID, schedule_id: UUID, payload: ScheduleUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    schedule = db.query(PipelineSchedule).filter(PipelineSchedule.id == schedule_id, PipelineSchedule.workspace_id == workspace_id).first()
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    if payload.cron_expression is not None:
        if not croniter.is_valid(payload.cron_expression):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cron expression")
        schedule.cron_expression = payload.cron_expression
    if payload.timezone is not None:
        try:
            ZoneInfo(payload.timezone)
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid timezone")
        schedule.timezone = payload.timezone
    if payload.enabled is not None:
        schedule.enabled = payload.enabled
    schedule.next_run_at = next_schedule(schedule.cron_expression, schedule.timezone).replace(tzinfo=None)
    record_audit(db, workspace_id, user.id, "PIPELINE_SCHEDULE_UPDATED", "schedule", schedule.id)
    db.commit()
    db.refresh(schedule)
    return schedule


@router.delete("/{workspace_id}/pipelines/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(workspace_id: UUID, schedule_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(db, workspace_id, user, WorkspaceRole.ADMIN)
    schedule = db.query(PipelineSchedule).filter(PipelineSchedule.id == schedule_id, PipelineSchedule.workspace_id == workspace_id).first()
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    record_audit(db, workspace_id, user.id, "PIPELINE_SCHEDULE_DELETED", "schedule", schedule.id)
    db.delete(schedule)
    db.commit()


@router.get("/{workspace_id}/pipelines/metrics")
def pipeline_metrics(workspace_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    membership(db, workspace_id, user.id)
    runs = db.query(PipelineRun).filter(PipelineRun.workspace_id == workspace_id).all()
    statuses = {
        "QUEUED": 0,
        "RUNNING": 0,
        "SUCCEEDED": 0,
        "FAILED": 0,
        "CANCELLED": 0,
    }
    durations = []
    for run in runs:
        statuses[run.status.value] = statuses.get(run.status.value, 0) + 1
        if run.duration_ms is not None:
            durations.append(run.duration_ms)
    step_rows = db.query(PipelineStepRun).join(PipelineRun).filter(PipelineRun.workspace_id == workspace_id).all()
    step_durations = [row.duration_ms for row in step_rows if row.duration_ms is not None]
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
def worker_health(workspace_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(db, workspace_id, user, WorkspaceRole.ADMIN)
    from app.core.config import get_settings
    from datetime import timedelta, datetime, timezone
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
    page: int = 1,
    page_size: int = 25,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(db, workspace_id, user, WorkspaceRole.ADMIN)
    page = max(1, page)
    page_size = min(100, max(1, page_size))
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
