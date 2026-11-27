import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.v1.workspaces import membership, require_role
from app.ai.engine import run_structured_task
from app.ai.providers import AIConfigurationError, AIProvider, get_provider, provider_status
from app.core.audit import record_audit
from app.core.db import get_db
from app.core.config import Settings, get_settings
from app.core.rate_limit import check_database_rate_limit
from app.models.entities import CatalogAsset, QualityRule, QualityRuleSeverity, QualityRuleType, TrustSnapshot, User, WorkspaceRole
from app.schemas.trust import FreshnessPatch, QualityRuleCreate, QualityRulePatch, TrustComputeResponse, TrustExplainResponse, validate_config
from app.services.trust import compute_trust, serialize_snapshot
from app.storage.factory import get_storage

router = APIRouter(prefix="/workspaces", tags=["trust"])
logger = logging.getLogger("pylake.trust")


def _configured_provider(settings: Settings) -> AIProvider:
    try:
        return get_provider(settings)
    except AIConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def scoped_asset(db: Session, workspace_id: UUID, asset_id: UUID) -> CatalogAsset:
    item = db.query(CatalogAsset).filter(CatalogAsset.id == asset_id, CatalogAsset.workspace_id == workspace_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Catalog asset not found")
    return item


def _rule_json(rule: QualityRule) -> dict:
    return {"id": str(rule.id), "asset_id": str(rule.asset_id), "column_name": rule.column_name,
            "rule_type": rule.rule_type.value, "config_json": rule.config_json, "severity": rule.severity.value,
            "enabled": rule.enabled, "created_at": rule.created_at, "updated_at": rule.updated_at}


@router.get("/{workspace_id}/trust/summary")
def trust_summary(workspace_id: UUID, limit: int = Query(default=10, ge=1, le=100),
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    membership(db, workspace_id, user.id)
    assets = db.query(CatalogAsset).filter(CatalogAsset.workspace_id == workspace_id).all()
    items = []
    for asset in assets:
        snapshot = db.query(TrustSnapshot).filter(TrustSnapshot.workspace_id == workspace_id,
            TrustSnapshot.asset_id == asset.id).order_by(TrustSnapshot.computed_at.desc()).first()
        items.append({"asset_id": str(asset.id), "name": asset.name, "asset_type": asset.asset_type,
                      "overall_score": snapshot.overall_score if snapshot else None,
                      "snapshot_id": str(snapshot.id) if snapshot else None,
                      "computed_at": snapshot.computed_at.isoformat() if snapshot else None})
    items.sort(key=lambda row: (row["overall_score"] is None, row["overall_score"] if row["overall_score"] is not None else 101))
    return {"items": items[:limit], "total": len(items)}


@router.get("/{workspace_id}/trust/{asset_id}")
def trust_latest(workspace_id: UUID, asset_id: UUID, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)) -> dict:
    membership(db, workspace_id, user.id)
    scoped_asset(db, workspace_id, asset_id)
    item = db.query(TrustSnapshot).filter(TrustSnapshot.workspace_id == workspace_id,
        TrustSnapshot.asset_id == asset_id).order_by(TrustSnapshot.computed_at.desc()).first()
    if not item:
        return {"asset_id": str(asset_id), "snapshot": None, "message": "No trust snapshot has been computed."}
    return serialize_snapshot(item)


@router.post("/{workspace_id}/trust/{asset_id}/compute", response_model=TrustComputeResponse)
def trust_compute(workspace_id: UUID, asset_id: UUID, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)) -> dict:
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    asset = scoped_asset(db, workspace_id, asset_id)
    check_database_rate_limit(db, str(user.id), "trust_compute", attempts=20, window_seconds=3600)
    try:
        result = compute_trust(db, get_storage(), workspace_id, asset, "MANUAL", user.id)
    except Exception as exc:
        logger.exception("Trust compute failed for asset %s", asset_id)
        raise HTTPException(status_code=422, detail="Trust computation could not complete") from exc
    record_audit(db, workspace_id, user.id, "TRUST_SNAPSHOT_COMPUTED", "catalog_asset", asset_id,
                 {"snapshot_id": result["id"], "trigger": "MANUAL"})
    db.commit()
    return result


@router.get("/{workspace_id}/trust/{asset_id}/history")
def trust_history(workspace_id: UUID, asset_id: UUID, limit: int = Query(default=30, ge=1, le=100),
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    membership(db, workspace_id, user.id)
    scoped_asset(db, workspace_id, asset_id)
    rows = db.query(TrustSnapshot).filter(TrustSnapshot.workspace_id == workspace_id,
        TrustSnapshot.asset_id == asset_id).order_by(TrustSnapshot.computed_at.desc()).limit(limit).all()
    return {"items": [serialize_snapshot(row) for row in rows]}


@router.post("/{workspace_id}/trust/{asset_id}/explain", response_model=TrustExplainResponse)
def trust_explain(workspace_id: UUID, asset_id: UUID, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)) -> dict:
    membership(db, workspace_id, user.id)
    scoped_asset(db, workspace_id, asset_id)
    snapshot = db.query(TrustSnapshot).filter(TrustSnapshot.workspace_id == workspace_id,
        TrustSnapshot.asset_id == asset_id).order_by(TrustSnapshot.computed_at.desc()).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Compute a trust snapshot before requesting an explanation")
    settings = get_settings()
    if not provider_status(settings).get("configured"):
        raise HTTPException(status_code=503, detail="AI provider is disabled")
    aggregates = {key: value for key, value in snapshot.metrics_json.items() if key != "_metadata"}
    rule_aggregates = [{key: rule.get(key) for key in ("rule_type", "column_name", "severity", "status", "passed", "checked")}
                       for rule in snapshot.rule_results_json]

    def validate(payload: dict[str, Any]) -> dict[str, Any]:
        summary = payload.get("summary")
        recommendations = payload.get("recommendations")
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 3000:
            raise ValueError("Invalid summary")
        if not isinstance(recommendations, list) or len(recommendations) > 5 or any(
            not isinstance(item, str) or len(item) > 500 for item in recommendations
        ):
            raise ValueError("Invalid recommendations")
        return {"summary": summary.strip(), "recommendations": recommendations}

    result = run_structured_task(
        db, workspace_id, user, settings,
        task="Explain aggregate Trust Passport measurements and offer cautious next steps",
        request="Return JSON with summary and recommendations array. Label uncertainty; never claim unmeasured properties are good.",
        validator=validate, provider=_configured_provider(settings), page_type="quality",
        context_override={"trust_metrics": aggregates, "rule_outcomes": rule_aggregates,
                          "overall_score": snapshot.overall_score, "sample_rows": snapshot.sample_rows,
                          "sampled": snapshot.sampled, "limitations": snapshot.limitations_json},
    )
    return {"ai_estimate": True, **result.value}


@router.get("/{workspace_id}/catalog/{asset_id}/quality-rules")
def list_rules(workspace_id: UUID, asset_id: UUID, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)) -> list[dict]:
    membership(db, workspace_id, user.id)
    asset = scoped_asset(db, workspace_id, asset_id)
    return [_rule_json(row) for row in db.query(QualityRule).filter(QualityRule.workspace_id == workspace_id,
        QualityRule.asset_id == asset.id).order_by(QualityRule.created_at).all()]


@router.post("/{workspace_id}/catalog/{asset_id}/quality-rules", status_code=201)
def create_rule(workspace_id: UUID, asset_id: UUID, payload: QualityRuleCreate,
                db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    asset = scoped_asset(db, workspace_id, asset_id)
    rule = QualityRule(workspace_id=workspace_id, asset_id=asset.id, column_name=payload.column_name,
        rule_type=QualityRuleType(payload.rule_type), config_json=payload.config_json,
        severity=QualityRuleSeverity(payload.severity), enabled=payload.enabled, created_by=user.id)
    db.add(rule); db.flush()
    record_audit(db, workspace_id, user.id, "QUALITY_RULE_CREATED", "quality_rule", rule.id,
                 {"rule_type": rule.rule_type.value, "severity": rule.severity.value})
    db.commit(); db.refresh(rule)
    return _rule_json(rule)


@router.patch("/{workspace_id}/catalog/{asset_id}/quality-rules/{rule_id}")
def update_rule(workspace_id: UUID, asset_id: UUID, rule_id: UUID, payload: QualityRulePatch,
                db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    asset = scoped_asset(db, workspace_id, asset_id)
    rule = db.query(QualityRule).filter(QualityRule.id == rule_id, QualityRule.asset_id == asset.id,
        QualityRule.workspace_id == workspace_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Quality rule not found")
    changes = payload.model_dump(exclude_unset=True)
    config = changes.get("config_json", rule.config_json)
    validate_config(rule.rule_type.value, config)
    if "column_name" in changes and rule.rule_type != QualityRuleType.MIN_ROW_COUNT and not changes["column_name"]:
        raise HTTPException(status_code=422, detail="column_name is required for this rule")
    for key, value in changes.items():
        setattr(rule, key, value)
    record_audit(db, workspace_id, user.id, "QUALITY_RULE_UPDATED", "quality_rule", rule.id,
                 {"changed_fields": sorted(changes)})
    db.commit(); db.refresh(rule)
    return _rule_json(rule)


@router.delete("/{workspace_id}/catalog/{asset_id}/quality-rules/{rule_id}", status_code=204)
def delete_rule(workspace_id: UUID, asset_id: UUID, rule_id: UUID, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> None:
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    asset = scoped_asset(db, workspace_id, asset_id)
    rule = db.query(QualityRule).filter(QualityRule.id == rule_id, QualityRule.asset_id == asset.id,
        QualityRule.workspace_id == workspace_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Quality rule not found")
    record_audit(db, workspace_id, user.id, "QUALITY_RULE_DELETED", "quality_rule", rule.id)
    db.delete(rule); db.commit()


@router.patch("/{workspace_id}/catalog/{asset_id}/freshness")
def set_freshness(workspace_id: UUID, asset_id: UUID, payload: FreshnessPatch,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    asset = scoped_asset(db, workspace_id, asset_id)
    asset.freshness_target_hours = payload.freshness_target_hours
    record_audit(db, workspace_id, user.id, "TRUST_FRESHNESS_TARGET_UPDATED", "catalog_asset", asset.id,
                 {"freshness_target_hours": payload.freshness_target_hours})
    db.commit(); db.refresh(asset)
    return {"asset_id": str(asset.id), "freshness_target_hours": asset.freshness_target_hours}
