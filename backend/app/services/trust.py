"""Measured, bounded Data Trust Passport calculations. No AI output affects scores."""
from __future__ import annotations

import math
import logging
import re
import tempfile
from datetime import datetime, timezone
from typing import Any

import polars as pl
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import (
    CatalogAsset, CatalogSchemaHistory, Dataset, DatasetVersion, LakehouseVersionStatus,
    LineageEdge, PipelineStep, PipelineStepRun, PipelineRun, QualityRule,
    StepStatus, TrustSnapshot,
)
from app.services.lakehouse import copy_source_to_temp, read_source
from app.storage.base import StorageInterface

WEIGHTS = {"completeness": .20, "uniqueness": .15, "validity": .20, "consistency": .15,
           "freshness": .10, "schema_stability": .10, "lineage_completeness": .10}
logger = logging.getLogger("pylake.trust")
SEVERITY_WEIGHT = {"LOW": 1.0, "MEDIUM": 2.0, "HIGH": 3.0}


def _metric(score: float | None, value: Any, detail: str, basis: str) -> dict[str, Any]:
    measured = score is not None and math.isfinite(float(score))
    return {"score": round(max(0.0, min(100.0, float(score))), 2) if measured else None,
            "status": "MEASURED" if measured else "NOT_MEASURED", "value": value,
            "detail": detail, "basis": basis}


def _rule_passes(rule: QualityRule, frame: pl.DataFrame) -> tuple[bool | None, int, int, str]:
    cfg = rule.config_json or {}
    col = rule.column_name
    if rule.rule_type.value == "MIN_ROW_COUNT":
        return frame.height >= int(cfg["minimum"]), frame.height, frame.height, f"Rows >= {cfg['minimum']}"
    if not col or col not in frame.columns:
        return None, 0, 0, "Configured column is absent from this sample"
    series = frame[col]
    values = series.to_list()
    non_null = [v for v in values if v is not None]
    if rule.rule_type.value == "NOT_NULL":
        count = len(non_null)
        return count == len(values), count, len(values), "Non-null rows / sampled rows"
    if rule.rule_type.value == "UNIQUE":
        unique = len(set(map(repr, non_null)))
        return unique == len(non_null), unique, len(non_null), "Distinct non-null values / non-null rows"
    if rule.rule_type.value == "RANGE":
        low, high = cfg.get("minimum"), cfg.get("maximum")
        checked = [v for v in non_null if isinstance(v, (int, float)) and not isinstance(v, bool)]
        passed = sum((low is None or v >= low) and (high is None or v <= high) for v in checked)
        return len(checked) == len(non_null) and passed == len(non_null), passed, len(values), "Values within inclusive configured range / sampled rows"
    if rule.rule_type.value == "REGEX":
        pattern = re.compile(cfg["pattern"])
        passed = sum(isinstance(v, str) and pattern.fullmatch(v) is not None for v in non_null)
        return passed == len(values), passed, len(values), "Full matches / sampled rows"
    if rule.rule_type.value == "ALLOWED_VALUES":
        allowed = {repr(v) for v in cfg["values"]}
        passed = sum(v is not None and repr(v) in allowed for v in values)
        return passed == len(values), passed, len(values), "Allowed values / sampled rows"
    return None, 0, 0, "Unsupported rule"


def _source(db: Session, storage: StorageInterface, workspace_id, asset):
    version = None
    if asset.asset_type == "TABLE" and asset.lakehouse_table_id:
        version = db.query(DatasetVersion).filter(
            DatasetVersion.lakehouse_table_id == asset.lakehouse_table_id,
            DatasetVersion.status == LakehouseVersionStatus.COMPLETED,
        ).order_by(DatasetVersion.version_number.desc()).first()
        if not version:
            return None, None, None, (False, None)
        suffix = f".{version.file_format}"
        key = version.storage_key
        total = version.row_count
    elif asset.asset_type == "DATASET" and asset.dataset_id:
        dataset = db.query(Dataset).filter(Dataset.id == asset.dataset_id, Dataset.workspace_id == workspace_id).first()
        if not dataset:
            return None, None, None, (False, None)
        version = db.query(DatasetVersion).filter(DatasetVersion.dataset_id == dataset.id).order_by(DatasetVersion.version_number.desc()).first()
        suffix = f".{dataset.file_format}"
        # The catalog DATASET points at the original uploaded object. Its Bronze
        # version is Parquet and belongs to the separate TABLE asset.
        key = dataset.storage_key
        total = dataset.row_count
    else:
        return None, None, None, (False, None)
    directory, path = copy_source_to_temp(storage, key, suffix)
    try:
        cap = min(get_settings().trust_sample_rows, 100_000)
        fmt = suffix.lstrip(".")
        cap = min(get_settings().trust_sample_rows, 100_000)
        if fmt == "parquet":
            lazy = pl.scan_parquet(path)
            actual_total = int(lazy.select(pl.len()).collect().item())
            frame = lazy.head(cap).collect()
        elif fmt == "csv":
            lazy = pl.scan_csv(path, infer_schema_length=1000)
            actual_total = int(lazy.select(pl.len()).collect().item())
            frame = lazy.head(cap).collect()
        else:
            frame = read_source(path, fmt).head(cap)
            actual_total = total if total is not None else frame.height
        sampled = actual_total > cap
        return frame.head(cap), actual_total, version, (sampled, directory)
    except Exception:
        directory.cleanup()
        raise


def compute_trust(db: Session, storage: StorageInterface, workspace_id, asset: CatalogAsset,
                  trigger: str, user_id=None) -> dict[str, Any]:
    frame, total_rows, version, sample_state = _source(db, storage, workspace_id, asset)
    limitations: list[str] = []
    results: list[dict[str, Any]] = []
    if frame is None:
        frame = pl.DataFrame()
        limitations.append("Data source is unavailable; row-dependent metrics were not measured.")
    sampled, directory = sample_state if sample_state else (False, None)
    if sampled:
        limitations.append("Metrics use a bounded sample of rows and may not represent the complete asset.")
    try:
        if frame.height and frame.width:
            null_rates = [frame[c].null_count() / frame.height for c in frame.columns]
            completeness = 100 * (1 - sum(null_rates) / len(null_rates))
            duplicate_count = frame.height - frame.unique().height
            uniqueness = 100 * (1 - duplicate_count / frame.height)
            metrics = {
                "completeness": _metric(completeness, {"mean_null_percent": round(100 - completeness, 4),
                                                         "column_null_percent": {c: round(100 * null_rates[i], 4) for i, c in enumerate(frame.columns)}},
                                         "Mean per-column null percentage across sampled rows.", "Polars null_count for every sampled column."),
                "uniqueness": _metric(uniqueness, {"duplicate_rows": duplicate_count, "sample_rows": frame.height},
                                       "100 minus duplicate whole-row percentage.", "frame.height - frame.unique().height."),
            }
        else:
            metrics = {
                "completeness": _metric(None, None, "No non-empty tabular sample available.", "Requires at least one row and column."),
                "uniqueness": _metric(None, None, "No non-empty tabular sample available.", "Requires at least one row and column."),
            }
        rules = db.query(QualityRule).filter(QualityRule.asset_id == asset.id, QualityRule.workspace_id == workspace_id,
                                             QualityRule.enabled.is_(True)).all()
        weighted_pass = weighted_total = 0.0
        for rule in rules:
            try:
                passed, pass_count, denominator, basis = _rule_passes(rule, frame)
            except (KeyError, TypeError, ValueError, re.error):
                passed, pass_count, denominator, basis = None, 0, 0, "Invalid rule configuration; not measured"
            weight = SEVERITY_WEIGHT[rule.severity.value]
            if passed is not None:
                weighted_total += weight * denominator
                weighted_pass += weight * pass_count
            results.append({"rule_id": str(rule.id), "rule_type": rule.rule_type.value, "column_name": rule.column_name,
                            "severity": rule.severity.value, "status": "PASS" if passed is True else "FAIL" if passed is False else "NOT_MEASURED",
                            "passed": pass_count, "checked": denominator, "basis": basis})
        validity_score = 100 * weighted_pass / weighted_total if weighted_total else None
        metrics["validity"] = _metric(validity_score, {"enabled_rules": len(rules), "weighted_pass": weighted_pass,
                                                        "weighted_checked": weighted_total},
                                      "Enabled rule pass percentage, weighted by severity and checked rows.",
                                      "LOW=1, MEDIUM=2, HIGH=3; rules without a usable sample are excluded.")
        parseable = parse_total = 0
        outliers = numeric_total = 0
        consistency_basis = []
        for name in frame.columns:
            series = frame[name]
            dtype = str(series.dtype)
            vals = [v for v in series.to_list() if v is not None]
            if dtype == "String" and vals:
                lowered = [v.strip() for v in vals if isinstance(v, str)]
                if lowered and (sum(bool(re.fullmatch(r"[+-]?(?:\d+\.?\d*|\.\d+)", v)) for v in lowered) / len(lowered) >= .8):
                    count = sum(bool(re.fullmatch(r"[+-]?(?:\d+\.?\d*|\.\d+)", v)) for v in lowered)
                    parseable += count; parse_total += len(lowered); consistency_basis.append(f"{name}: numeric string parse rate")
                elif lowered and (sum(_looks_date(v) for v in lowered) / len(lowered) >= .8):
                    count = sum(_looks_date(v) for v in lowered)
                    parseable += count; parse_total += len(lowered); consistency_basis.append(f"{name}: date string parse rate")
            if dtype.startswith(("Int", "UInt", "Float", "Decimal")) and vals:
                numeric = series.cast(pl.Float64, strict=False).drop_nulls()
                q1, q3 = numeric.quantile(.25), numeric.quantile(.75)
                if q1 is not None and q3 is not None:
                    spread = q3 - q1
                    outside = int(((numeric < q1 - 1.5 * spread) | (numeric > q3 + 1.5 * spread)).sum())
                    outliers += outside; numeric_total += len(numeric)
                    consistency_basis.append(f"{name}: IQR outlier rate")
        consistency_parts = []
        if parse_total:
            consistency_parts.append((parseable / parse_total, parse_total))
        if numeric_total:
            consistency_parts.append((1 - outliers / numeric_total, numeric_total))
        consistency_score = 100 * sum(rate * count for rate, count in consistency_parts) / sum(count for _, count in consistency_parts) if consistency_parts else None
        metrics["consistency"] = _metric(consistency_score, {"parseable": parseable, "parse_checked": parse_total,
                                                              "iqr_outliers": outliers, "numeric_checked": numeric_total},
                                          "Weighted average of parseability for string columns that appear numeric/date and 1 minus numeric IQR outlier rate.",
                                          "; ".join(consistency_basis) if consistency_basis else "No candidate string or numeric columns were measurable.")
        if asset.freshness_target_hours and asset.freshness_target_hours > 0:
            latest = db.query(DatasetVersion).filter(DatasetVersion.status == LakehouseVersionStatus.COMPLETED).join(
                Dataset, DatasetVersion.dataset_id == Dataset.id).filter(Dataset.workspace_id == workspace_id).filter(
                    (DatasetVersion.dataset_id == asset.dataset_id) | (DatasetVersion.lakehouse_table_id == asset.lakehouse_table_id)
                ).order_by(DatasetVersion.created_at.desc()).first() if (asset.dataset_id or asset.lakehouse_table_id) else None
            timestamp = latest.created_at if latest else None
            if timestamp:
                age = max(0.0, (datetime.now(timezone.utc) - timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else datetime.now(timezone.utc) - timestamp).total_seconds() / 3600)
                score = max(0, 100 * (1 - age / (3 * asset.freshness_target_hours)))
                metrics["freshness"] = _metric(score, {"age_hours": round(age, 3), "target_hours": asset.freshness_target_hours},
                                                "Linear decay from 100 at ingestion to 0 at three times the configured target.", "Latest completed version created_at.")
            else:
                metrics["freshness"] = _metric(None, None, "No completed ingestion/version timestamp exists.", "Requires latest completed DatasetVersion.")
        else:
            metrics["freshness"] = _metric(None, None, "No freshness target configured.", "Configure freshness_target_hours to measure freshness.")
        history = db.query(CatalogSchemaHistory).filter(CatalogSchemaHistory.asset_id == asset.id).order_by(CatalogSchemaHistory.created_at.desc()).limit(10).all()
        if len(history) < 2:
            metrics["schema_stability"] = _metric(None, {"history_entries": len(history)}, "At least two schema observations are required.", "Last 10 CatalogSchemaHistory entries.")
        else:
            breaking = 0
            for newer, older in zip(history, history[1:]):
                old = {c.get("name"): c.get("type") for c in (older.schema_json or {}).get("columns", [])}
                new = {c.get("name"): c.get("type") for c in (newer.schema_json or {}).get("columns", [])}
                breaking += len(set(old) - set(new)) + sum(old[k] != new[k] for k in set(old) & set(new))
            metrics["schema_stability"] = _metric(max(0, 100 - 20 * breaking), {"breaking_changes": breaking, "history_entries": len(history)},
                                                   "100 minus 20 points for each adjacent schema pair with a dropped column or type change.", "Adjacent comparisons across at most 10 latest schema history entries.")
        edge = db.query(LineageEdge.id).filter(LineageEdge.workspace_id == workspace_id,
            (LineageEdge.source_asset_id == asset.id) | (LineageEdge.target_asset_id == asset.id)).first()
        lineage_score = 100 if edge or asset.asset_type == "DATASET" else 50
        metrics["lineage_completeness"] = _metric(lineage_score, {"has_recorded_edge": bool(edge), "raw_ingested_dataset": asset.asset_type == "DATASET"},
                                                    "Raw ingested datasets count as complete source nodes; other assets receive full credit with an edge, partial credit otherwise.", "CatalogAsset type and workspace-scoped LineageEdge records.")
        measured = [key for key, metric in metrics.items() if metric["status"] == "MEASURED"]
        excluded = [key for key in metrics if key not in measured]
        total_weight = sum(WEIGHTS[key] for key in measured)
        overall = round(sum(metrics[key]["score"] * WEIGHTS[key] for key in measured) / total_weight, 2) if total_weight else None
        if excluded:
            limitations.extend(f"{name} was not measured: {metrics[name]['detail']}" for name in excluded)
        validation = db.query(PipelineStepRun, PipelineRun).join(PipelineRun, PipelineRun.id == PipelineStepRun.pipeline_run_id).join(
            PipelineStep, PipelineStep.id == PipelineStepRun.pipeline_step_id).filter(
                PipelineRun.workspace_id == workspace_id, PipelineStep.step_type == "DATA_QUALITY",
                PipelineStepRun.status == StepStatus.SUCCEEDED).order_by(PipelineStepRun.completed_at.desc()).first()
        last_validation = validation[0].completed_at.isoformat() if validation and validation[0].completed_at else None
        if last_validation is None:
            previous = db.query(TrustSnapshot).filter(TrustSnapshot.workspace_id == workspace_id, TrustSnapshot.asset_id == asset.id).order_by(TrustSnapshot.computed_at.desc()).first()
            last_validation = previous.computed_at.isoformat() if previous else None
        metrics["_metadata"] = {"measured_metrics": measured, "excluded_metrics": excluded,
                                "last_successful_validation": last_validation}
        snapshot = TrustSnapshot(workspace_id=workspace_id, asset_id=asset.id, version_id=version.id if version else None,
            overall_score=overall, metrics_json=metrics, rule_results_json=results, limitations_json=limitations,
            sample_rows=frame.height, total_rows=total_rows, sampled=sampled, trigger=trigger[:30], created_by=user_id)
        db.add(snapshot); db.commit(); db.refresh(snapshot)
        return serialize_snapshot(snapshot)
    finally:
        if directory:
            directory.cleanup()


def _looks_date(value: str) -> bool:
    from datetime import date
    try:
        date.fromisoformat(value[:10])
        return True
    except ValueError:
        return False


def serialize_snapshot(item: TrustSnapshot) -> dict[str, Any]:
    metadata = item.metrics_json.get("_metadata", {})
    return {"id": str(item.id), "workspace_id": str(item.workspace_id), "asset_id": str(item.asset_id),
            "version_id": str(item.version_id) if item.version_id else None, "overall_score": item.overall_score,
            "metrics": {key: value for key, value in item.metrics_json.items() if key != "_metadata"},
            "measured_metrics": metadata.get("measured_metrics", []),
            "excluded_metrics": metadata.get("excluded_metrics", []), "rule_results": item.rule_results_json,
            "limitations": item.limitations_json, "sample_rows": item.sample_rows, "total_rows": item.total_rows,
            "sampled": item.sampled, "trigger": item.trigger, "computed_at": item.computed_at.isoformat(),
            "last_successful_validation": metadata.get("last_successful_validation")}


def compute_trust_best_effort(db: Session, storage: StorageInterface, workspace_id, asset: CatalogAsset,
                              trigger: str, user_id=None) -> dict[str, Any] | None:
    """Run automatic triggers without allowing trust failures to break primary work."""
    try:
        return compute_trust(db, storage, workspace_id, asset, trigger, user_id)
    except Exception:
        db.rollback()
        logger.exception("Automatic trust snapshot failed for asset %s trigger=%s", asset.id, trigger)
        return None
