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
    db.commit()
    db.refresh(pipeline)
    return pipeline


@router.delete("/{workspace_id}/pipelines/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pipeline(workspace_id: UUID, pipeline_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(db, workspace_id, user, WorkspaceRole.ADMIN)
    pipeline = scoped_pipeline(db, workspace_id, pipeline_id)
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
    db.commit()
    db.refresh(schedule)
    return schedule


@router.delete("/{workspace_id}/pipelines/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(workspace_id: UUID, schedule_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(db, workspace_id, user, WorkspaceRole.ADMIN)
    schedule = db.query(PipelineSchedule).filter(PipelineSchedule.id == schedule_id, PipelineSchedule.workspace_id == workspace_id).first()
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    db.delete(schedule)
    db.commit()
