"""Autopilot plan → preview → approve → execute → report API."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.ai.actions import (
    ACTION_REGISTRY,
    ActionValidationError,
    get_action,
    max_min_role,
    role_satisfies,
    validate_action_arguments,
)
from app.ai.drafts import InvalidAIDraft
from app.ai.engine import run_structured_task
from app.ai.providers import AIConfigurationError, AIProvider, get_provider, provider_status
from app.api.dependencies import get_current_user
from app.api.v1.workspaces import RANK, membership, require_role
from app.core.audit import record_audit
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.models.entities import (
    AutopilotPlan,
    AutopilotPlanStatus,
    AutopilotRiskLevel,
    AutopilotStep,
    AutopilotStepStatus,
    User,
    WorkspaceRole,
    utcnow,
)
from app.schemas.autopilot import (
    AutopilotApproveRequest,
    AutopilotPlanCreate,
    AutopilotPlanResponse,
)

logger = logging.getLogger("pylake.autopilot")
router = APIRouter(prefix="/workspaces", tags=["autopilot"])


def _configured_provider(settings: Settings) -> AIProvider:
    try:
        return get_provider(settings)
    except AIConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error


def _canonical_plan_hash(steps: list[AutopilotStep]) -> str:
    payload = [
        {"action_key": step.action_key, "arguments": step.arguments_json or {}}
        for step in sorted(steps, key=lambda item: item.step_order)
    ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _step_json(step: AutopilotStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "step_order": step.step_order,
        "action_key": step.action_key,
        "title": step.title,
        "rationale": step.rationale,
        "arguments_json": step.arguments_json,
        "evidence_json": step.evidence_json,
        "preview_json": step.preview_json,
        "risk_level": step.risk_level.value if hasattr(step.risk_level, "value") else step.risk_level,
        "requires_approval": step.requires_approval,
        "status": step.status.value if hasattr(step.status, "value") else step.status,
        "result_json": step.result_json,
        "error_message": step.error_message,
        "started_at": step.started_at,
        "completed_at": step.completed_at,
    }


def _plan_json(plan: AutopilotPlan) -> dict[str, Any]:
    steps = sorted(plan.steps, key=lambda item: item.step_order)
    return {
        "id": plan.id,
        "workspace_id": plan.workspace_id,
        "created_by": plan.created_by,
        "goal": plan.goal,
        "status": plan.status.value if hasattr(plan.status, "value") else plan.status,
        "plan_hash": plan.plan_hash,
        "ai_provider": plan.ai_provider,
        "ai_model": plan.ai_model,
        "approved_by": plan.approved_by,
        "approved_at": plan.approved_at,
        "started_at": plan.started_at,
        "completed_at": plan.completed_at,
        "error_message": plan.error_message,
        "report_json": plan.report_json,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
        "steps": [_step_json(step) for step in steps],
    }


def _scoped_plan(db: Session, workspace_id: UUID, plan_id: UUID) -> AutopilotPlan:
    plan = db.query(AutopilotPlan).options(
        joinedload(AutopilotPlan.steps),
    ).filter(
        AutopilotPlan.id == plan_id,
        AutopilotPlan.workspace_id == workspace_id,
    ).first()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Autopilot plan not found")
    return plan


def _sanitize_text(value: str, limit: int = 4000) -> str:
    return "".join(character for character in value if character.isprintable() or character in "\n\t")[:limit]


def _sanitize_evidence(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    sanitized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        entry = {
            key: _sanitize_text(item[key], limit)
            for key, limit in (("source", 80), ("detail", 500))
            if isinstance(item.get(key), str)
        }
        if entry:
            sanitized.append(entry)
        if len(sanitized) >= 10:
            break
    return sanitized


def _validate_manual_steps(
    db: Session,
    workspace_id: UUID,
    steps: list[Any],
) -> list[dict[str, Any]]:
    if not steps:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one step is required",
        )
    if len(steps) > 20:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Autopilot plans are limited to 20 steps",
        )
    validated: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        action_key = step.action_key if hasattr(step, "action_key") else step.get("action_key")
        arguments = step.arguments if hasattr(step, "arguments") else step.get("arguments", {})
        title = step.title if hasattr(step, "title") else step.get("title")
        rationale = step.rationale if hasattr(step, "rationale") else step.get("rationale")
        evidence = step.evidence if hasattr(step, "evidence") else step.get("evidence")
        try:
            action = get_action(str(action_key))
            safe_args = validate_action_arguments(db, workspace_id, action.key, arguments or {})
        except ActionValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Step {index} rejected: {error}",
            ) from error
        validated.append({
            "action_key": action.key,
            "title": _sanitize_text(title or action.title, 200),
            "rationale": _sanitize_text(rationale or "", 2000) or None,
            "arguments": safe_args,
            "evidence": _sanitize_evidence(evidence),
            "risk_level": action.risk_level,
            "requires_approval": action.requires_approval,
        })
    return validated


def _plan_from_ai(
    db: Session,
    workspace_id: UUID,
    user: User,
    goal: str,
    dataset_id: UUID | None,
    table_id: UUID | None,
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    settings = get_settings()
    status_info = provider_status(settings)
    if not status_info["configured"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI planning is unavailable because the AI provider is disabled. Supply steps manually.",
        )

    allowlist = sorted(ACTION_REGISTRY.keys())

    def validator(raw: dict[str, Any]) -> dict[str, Any]:
        steps = raw.get("steps")
        if not isinstance(steps, list) or not steps:
            raise InvalidAIDraft("Plan must include a non-empty steps array")
        if len(steps) > 20:
            raise InvalidAIDraft("Plan exceeds the step limit")
        accepted: list[dict[str, Any]] = []
        for index, item in enumerate(steps, start=1):
            if not isinstance(item, dict):
                raise InvalidAIDraft(f"Step {index} is invalid")
            action_key = item.get("action_key")
            arguments = item.get("arguments") or {}
            if not isinstance(action_key, str) or action_key not in ACTION_REGISTRY:
                raise InvalidAIDraft(f"Step {index} rejected: unknown action")
            if not isinstance(arguments, dict):
                raise InvalidAIDraft(f"Step {index} rejected: invalid arguments")
            try:
                safe_args = validate_action_arguments(db, workspace_id, action_key, arguments)
            except ActionValidationError as error:
                raise InvalidAIDraft(f"Step {index} rejected: {error}") from error
            action = get_action(action_key)
            title = item.get("title")
            rationale = item.get("rationale")
            evidence = item.get("evidence")
            accepted.append({
                "action_key": action.key,
                "title": _sanitize_text(str(title or action.title), 200),
                "rationale": _sanitize_text(str(rationale or ""), 2000) or None,
                "arguments": safe_args,
                "evidence": _sanitize_evidence(evidence),
                "risk_level": action.risk_level,
                "requires_approval": action.requires_approval,
            })
        return {"steps": accepted}

    result = run_structured_task(
        db,
        workspace_id,
        user,
        settings,
        provider=_configured_provider(settings),
        task="Create a PyLake Autopilot plan using only allowlisted actions and real workspace IDs",
        request=(
            f"Goal (untrusted user text):\n{_sanitize_text(goal)}\n\n"
            f"Return only JSON with key steps (array). Each step must have action_key, title, "
            f"rationale, arguments, and optional evidence. Allowed action_key values: {allowlist}. "
            "Use only dataset/table/pipeline IDs present in the workspace context. "
            "Do not invent IDs. Do not include delete/drop/overwrite actions."
        ),
        validator=validator,
        dataset_id=dataset_id,
        table_id=table_id,
        page_type="autopilot",
        reject_detail="Generated Autopilot plan did not pass validation",
        audit_rejected_action="AI_AUTOPILOT_PLAN_REJECTED",
    )
    return result.value["steps"], result.provider.name, result.provider.model


def _persist_steps(db: Session, plan: AutopilotPlan, steps: list[dict[str, Any]]) -> None:
    for index, item in enumerate(steps, start=1):
        db.add(AutopilotStep(
            plan_id=plan.id,
            step_order=index,
            action_key=item["action_key"],
            title=item["title"],
            rationale=item.get("rationale"),
            arguments_json=item["arguments"],
            evidence_json=item.get("evidence") or [],
            risk_level=AutopilotRiskLevel(item["risk_level"]),
            requires_approval=bool(item["requires_approval"]),
            status=AutopilotStepStatus.PENDING,
        ))


@router.post(
    "/{workspace_id}/ai/autopilot/plans",
    response_model=AutopilotPlanResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_plan(
    workspace_id: UUID,
    payload: AutopilotPlanCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    membership(db, workspace_id, user.id)
    goal = _sanitize_text(payload.goal.strip())
    if not goal:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Goal cannot be blank")

    if payload.steps is not None:
        steps = _validate_manual_steps(db, workspace_id, payload.steps)
        provider_name = None
        model_name = None
    else:
        steps, provider_name, model_name = _plan_from_ai(
            db, workspace_id, user, goal, payload.dataset_id, payload.table_id,
        )

    plan = AutopilotPlan(
        workspace_id=workspace_id,
        created_by=user.id,
        goal=goal,
        status=AutopilotPlanStatus.DRAFT,
        ai_provider=provider_name,
        ai_model=model_name,
    )
    db.add(plan)
    db.flush()
    _persist_steps(db, plan, steps)
    record_audit(db, workspace_id, user.id, "AUTOPILOT_PLAN_CREATED", "autopilot_plan", plan.id, {
        "step_count": len(steps),
        "manual": payload.steps is not None,
    })
    db.commit()
    return _plan_json(_scoped_plan(db, workspace_id, plan.id))


@router.get("/{workspace_id}/ai/autopilot/plans", response_model=list[AutopilotPlanResponse])
def list_plans(
    workspace_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    membership(db, workspace_id, user.id)
    plans = db.query(AutopilotPlan).options(
        joinedload(AutopilotPlan.steps),
    ).filter(
        AutopilotPlan.workspace_id == workspace_id,
    ).order_by(AutopilotPlan.created_at.desc()).limit(50).all()
    return [_plan_json(plan) for plan in plans]


@router.get("/{workspace_id}/ai/autopilot/plans/{plan_id}", response_model=AutopilotPlanResponse)
def get_plan(
    workspace_id: UUID,
    plan_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    membership(db, workspace_id, user.id)
    return _plan_json(_scoped_plan(db, workspace_id, plan_id))


@router.post("/{workspace_id}/ai/autopilot/plans/{plan_id}/preview", response_model=AutopilotPlanResponse)
def preview_plan(
    workspace_id: UUID,
    plan_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    membership(db, workspace_id, user.id)
    plan = _scoped_plan(db, workspace_id, plan_id)
    if plan.status not in {AutopilotPlanStatus.DRAFT, AutopilotPlanStatus.PREVIEWED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only DRAFT or PREVIEWED plans can be previewed",
        )
    steps = sorted(plan.steps, key=lambda item: item.step_order)
    for step in steps:
        try:
            action = get_action(step.action_key)
            # Re-validate arguments and run pure preview (no writes).
            safe_args = validate_action_arguments(db, workspace_id, step.action_key, step.arguments_json or {})
            step.arguments_json = safe_args
            step.preview_json = action.preview(db, workspace_id, safe_args)
        except ActionValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Step {step.step_order} preview failed: {error}",
            ) from error
    plan.plan_hash = _canonical_plan_hash(steps)
    plan.status = AutopilotPlanStatus.PREVIEWED
    plan.updated_at = utcnow()
    record_audit(db, workspace_id, user.id, "AUTOPILOT_PLAN_PREVIEWED", "autopilot_plan", plan.id, {
        "plan_hash": plan.plan_hash,
    })
    db.commit()
    return _plan_json(_scoped_plan(db, workspace_id, plan.id))


@router.post("/{workspace_id}/ai/autopilot/plans/{plan_id}/approve", response_model=AutopilotPlanResponse)
def approve_plan(
    workspace_id: UUID,
    plan_id: UUID,
    payload: AutopilotApproveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    member = membership(db, workspace_id, user.id)
    plan = _scoped_plan(db, workspace_id, plan_id)
    if plan.status != AutopilotPlanStatus.PREVIEWED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only PREVIEWED plans can be approved",
        )
    steps = sorted(plan.steps, key=lambda item: item.step_order)
    required = max_min_role([step.action_key for step in steps]) if steps else "EDITOR"
    # Approving always requires at least EDITOR so viewers cannot unlock mutating plans.
    required_rank = max(RANK[required], RANK["EDITOR"])
    if RANK[member.role.value] < required_rank:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient workspace permissions",
        )
    expected = _canonical_plan_hash(steps)
    if not plan.plan_hash or payload.plan_hash != plan.plan_hash or payload.plan_hash != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Plan hash does not match the previewed plan",
        )
    plan.status = AutopilotPlanStatus.APPROVED
    plan.approved_by = user.id
    plan.approved_at = utcnow()
    plan.updated_at = utcnow()
    record_audit(db, workspace_id, user.id, "AUTOPILOT_PLAN_APPROVED", "autopilot_plan", plan.id, {
        "plan_hash": plan.plan_hash,
    })
    db.commit()
    return _plan_json(_scoped_plan(db, workspace_id, plan.id))


def _build_report(plan: AutopilotPlan) -> dict[str, Any]:
    steps = sorted(plan.steps, key=lambda item: item.step_order)
    created: dict[str, list[str]] = {
        "version_ids": [],
        "pipeline_ids": [],
        "schedule_ids": [],
        "dataset_ids": [],
    }
    summaries = []
    not_done = []
    for step in steps:
        duration = None
        if step.started_at and step.completed_at:
            duration = int((step.completed_at - step.started_at).total_seconds() * 1000)
        summaries.append({
            "step_order": step.step_order,
            "action_key": step.action_key,
            "title": step.title,
            "status": step.status.value,
            "duration_ms": duration,
            "error_message": step.error_message,
            "result": step.result_json,
        })
        result = step.result_json or {}
        if step.status == AutopilotStepStatus.SUCCEEDED:
            if result.get("version_id"):
                created["version_ids"].append(str(result["version_id"]))
            if result.get("pipeline_id"):
                created["pipeline_ids"].append(str(result["pipeline_id"]))
            if result.get("schedule_id"):
                created["schedule_ids"].append(str(result["schedule_id"]))
            if result.get("dataset_id"):
                created["dataset_ids"].append(str(result["dataset_id"]))
        if step.status in {AutopilotStepStatus.SKIPPED, AutopilotStepStatus.CANCELLED, AutopilotStepStatus.FAILED}:
            not_done.append({
                "step_order": step.step_order,
                "action_key": step.action_key,
                "status": step.status.value,
                "reason": step.error_message or step.status.value,
            })
    return {
        "plan_id": str(plan.id),
        "status": plan.status.value,
        "goal": plan.goal,
        "steps": summaries,
        "created": created,
        "not_done": not_done,
        "error_message": plan.error_message,
    }


@router.post("/{workspace_id}/ai/autopilot/plans/{plan_id}/execute", response_model=AutopilotPlanResponse)
def execute_plan(
    workspace_id: UUID,
    plan_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    member = membership(db, workspace_id, user.id)
    plan = _scoped_plan(db, workspace_id, plan_id)
    if plan.status != AutopilotPlanStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only APPROVED plans can be executed",
        )
    steps = sorted(plan.steps, key=lambda item: item.step_order)
    required = max_min_role([step.action_key for step in steps]) if steps else "EDITOR"
    required_rank = max(RANK[required], RANK["EDITOR"])
    if RANK[member.role.value] < required_rank:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient workspace permissions",
        )
    expected = _canonical_plan_hash(steps)
    if not plan.plan_hash or plan.plan_hash != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Plan arguments changed after approval; re-preview and approve again",
        )

    started_at = utcnow()
    claimed = db.query(AutopilotPlan).filter(
        AutopilotPlan.id == plan.id,
        AutopilotPlan.workspace_id == workspace_id,
        AutopilotPlan.status == AutopilotPlanStatus.APPROVED,
    ).update(
        {
            AutopilotPlan.status: AutopilotPlanStatus.RUNNING,
            AutopilotPlan.started_at: started_at,
            AutopilotPlan.updated_at: started_at,
        },
        synchronize_session=False,
    )
    db.commit()
    if claimed != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Plan is already running or no longer approved",
        )
    db.refresh(plan)

    failed = False
    for index, step in enumerate(steps):
        if failed:
            step.status = AutopilotStepStatus.SKIPPED
            step.completed_at = utcnow()
            continue
        action = get_action(step.action_key)
        if not role_satisfies(member.role.value, action.min_role):
            step.status = AutopilotStepStatus.FAILED
            step.error_message = "Insufficient permissions for this action"
            step.completed_at = utcnow()
            failed = True
            for remaining in steps[index + 1:]:
                remaining.status = AutopilotStepStatus.SKIPPED
                remaining.completed_at = utcnow()
            break
        step.status = AutopilotStepStatus.RUNNING
        step.started_at = utcnow()
        db.commit()
        started = time.perf_counter()
        try:
            # Re-hash check per step: refuse if arguments were tampered with.
            if _canonical_plan_hash(steps) != plan.plan_hash:
                raise ActionValidationError("Plan hash mismatch during execution")
            safe_args = validate_action_arguments(db, workspace_id, step.action_key, step.arguments_json or {})
            result = action.execute(db, workspace_id, user, safe_args)
            step.result_json = result
            step.status = AutopilotStepStatus.SUCCEEDED
            step.completed_at = utcnow()
            record_audit(
                db,
                workspace_id,
                user.id,
                "AUTOPILOT_STEP_SUCCEEDED",
                "autopilot_step",
                step.id,
                {"action_key": step.action_key, "duration_ms": int((time.perf_counter() - started) * 1000)},
            )
            db.commit()
        except ActionValidationError as error:
            db.rollback()
            logger.warning("Autopilot step failed plan_id=%s step=%s", plan.id, step.step_order)
            step.status = AutopilotStepStatus.FAILED
            step.error_message = str(error)[:1000]
            step.completed_at = utcnow()
            failed = True
            for remaining in steps[index + 1:]:
                remaining.status = AutopilotStepStatus.SKIPPED
                remaining.completed_at = utcnow()
            record_audit(
                db,
                workspace_id,
                user.id,
                "AUTOPILOT_STEP_FAILED",
                "autopilot_step",
                step.id,
                {"action_key": step.action_key},
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Unexpected Autopilot step failure plan_id=%s step=%s", plan.id, step.step_order)
            step.status = AutopilotStepStatus.FAILED
            step.error_message = "Action execution failed"
            step.completed_at = utcnow()
            record_audit(
                db,
                workspace_id,
                user.id,
                "AUTOPILOT_STEP_FAILED",
                "autopilot_step",
                step.id,
                {"action_key": step.action_key},
            )
            failed = True
            for remaining in steps[index + 1:]:
                remaining.status = AutopilotStepStatus.SKIPPED
                remaining.completed_at = utcnow()
            db.commit()

    plan = _scoped_plan(db, workspace_id, plan_id)
    plan.completed_at = utcnow()
    plan.updated_at = utcnow()
    if failed:
        plan.status = AutopilotPlanStatus.FAILED
        plan.error_message = next(
            (step.error_message for step in plan.steps if step.status == AutopilotStepStatus.FAILED),
            "Autopilot execution failed",
        )
    else:
        plan.status = AutopilotPlanStatus.SUCCEEDED
        plan.error_message = None
    plan.report_json = _build_report(plan)
    record_audit(db, workspace_id, user.id, "AUTOPILOT_PLAN_EXECUTED", "autopilot_plan", plan.id, {
        "status": plan.status.value,
    })
    db.commit()
    return _plan_json(_scoped_plan(db, workspace_id, plan_id))


@router.post("/{workspace_id}/ai/autopilot/plans/{plan_id}/cancel", response_model=AutopilotPlanResponse)
def cancel_plan(
    workspace_id: UUID,
    plan_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    plan = _scoped_plan(db, workspace_id, plan_id)
    if plan.status not in {
        AutopilotPlanStatus.DRAFT,
        AutopilotPlanStatus.PREVIEWED,
        AutopilotPlanStatus.APPROVED,
        AutopilotPlanStatus.RUNNING,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Plan cannot be cancelled in its current status",
        )
    if plan.status == AutopilotPlanStatus.RUNNING:
        for step in plan.steps:
            if step.status in {AutopilotStepStatus.PENDING, AutopilotStepStatus.RUNNING}:
                step.status = AutopilotStepStatus.CANCELLED
                step.completed_at = utcnow()
    else:
        for step in plan.steps:
            if step.status == AutopilotStepStatus.PENDING:
                step.status = AutopilotStepStatus.CANCELLED
                step.completed_at = utcnow()
    plan.status = AutopilotPlanStatus.CANCELLED
    plan.completed_at = utcnow()
    plan.updated_at = utcnow()
    plan.report_json = _build_report(plan)
    record_audit(db, workspace_id, user.id, "AUTOPILOT_PLAN_CANCELLED", "autopilot_plan", plan.id)
    db.commit()
    return _plan_json(_scoped_plan(db, workspace_id, plan_id))


@router.get("/{workspace_id}/ai/autopilot/plans/{plan_id}/report")
def get_report(
    workspace_id: UUID,
    plan_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    membership(db, workspace_id, user.id)
    plan = _scoped_plan(db, workspace_id, plan_id)
    if plan.report_json:
        return plan.report_json
    return _build_report(plan)
