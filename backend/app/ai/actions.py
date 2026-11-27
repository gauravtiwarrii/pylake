"""Autopilot action allowlist: preview (no writes) + execute via existing services."""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from croniter import croniter
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai.drafts import validate_pipeline_draft, validate_transformation_draft
from app.ai.tools import ROLE_RANK
from app.core.audit import record_audit
from app.engines.query_executor import execute_workspace_query
from app.engines.query_validator import SQLValidationError, validate_read_only_sql
from app.engines.catalog_resolver import resolve_catalog
from app.models.entities import (
    Dataset,
    DatasetStatus,
    DatasetVersion,
    LakehouseLayer,
    LakehouseTable,
    LakehouseVersionStatus,
    Pipeline,
    PipelineSchedule,
    PipelineStatus,
    PipelineStep,
    CatalogAsset,
    QualityRule,
    QualityRuleSeverity,
    QualityRuleType,
    StorageObject,
    TransformationRecord,
    TransformationStatus,
    User,
)
from app.schemas.lakehouse import PromoteRequest
from app.schemas.trust import QualityRuleCreate
from app.services import trust as trust_service
from app.services.catalog import ensure_dataset_asset, ensure_table_asset, profile_asset
from app.services.lakehouse import (
    checksum_file,
    copy_source_to_temp,
    frame_schema,
    normalize_frame,
    read_source,
    write_parquet,
)
from app.services.lineage import record_lineage
from app.storage.factory import get_storage
import polars as pl


RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]


class ActionValidationError(ValueError):
    pass


class ProfileDatasetArgs(BaseModel):
    dataset_id: UUID


class PromoteTableArgs(BaseModel):
    table_id: UUID
    target_layer: Literal["SILVER", "GOLD"]
    source_version_id: UUID | None = None
    partition_columns: list[str] = Field(default_factory=list, max_length=4)


class ApplyTransformationArgs(BaseModel):
    table_id: UUID
    transformation_type: Literal[
        "rename", "drop", "cast", "deduplicate", "filter",
        "fill_null", "normalize_names", "calculated", "select", "sort",
    ]
    configuration: dict[str, Any] = Field(default_factory=dict)
    target_layer: Literal["SILVER", "GOLD"] = "SILVER"
    source_version_id: UUID | None = None


class RunReadonlySqlArgs(BaseModel):
    sql: str = Field(min_length=1, max_length=100000)
    limit: int | None = Field(default=100, ge=1, le=1000)


class CreatePipelineArgs(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    steps: list[dict[str, Any]] = Field(default_factory=list)


class CreateScheduleArgs(BaseModel):
    pipeline_id: UUID
    cron_expression: str = Field(min_length=9, max_length=200)
    timezone: str = "UTC"
    enabled: bool = True


class ComputeTrustArgs(BaseModel):
    asset_id: UUID


class CreateQualityRuleArgs(QualityRuleCreate):
    asset_id: UUID


class SimulateImpactArgs(BaseModel):
    asset_id: UUID
    change: dict[str, Any]


@dataclass(frozen=True)
class ActionDefinition:
    key: str
    title: str
    min_role: str
    risk_level: RiskLevel
    requires_approval: bool
    args_schema: type[BaseModel]
    preview: Callable[[Session, UUID, dict[str, Any]], dict[str, Any]]
    execute: Callable[[Session, UUID, User, dict[str, Any]], dict[str, Any]]


def _next_version(db: Session, dataset_id: UUID) -> int:
    maximum = db.query(func.max(DatasetVersion.version_number)).filter(
        DatasetVersion.dataset_id == dataset_id,
    ).scalar()
    return int(maximum or 0) + 1


def _scoped_dataset(db: Session, workspace_id: UUID, dataset_id: UUID) -> Dataset:
    dataset = db.query(Dataset).filter(
        Dataset.id == dataset_id,
        Dataset.workspace_id == workspace_id,
    ).first()
    if not dataset:
        raise ActionValidationError("Dataset not found in workspace")
    return dataset


def _scoped_table(db: Session, workspace_id: UUID, table_id: UUID) -> LakehouseTable:
    table = db.query(LakehouseTable).filter(
        LakehouseTable.id == table_id,
        LakehouseTable.workspace_id == workspace_id,
    ).first()
    if not table:
        raise ActionValidationError("Lakehouse table not found in workspace")
    return table


def _dataset_for_table(db: Session, table: LakehouseTable) -> Dataset:
    dataset = db.query(Dataset).join(DatasetVersion).filter(
        Dataset.id == DatasetVersion.dataset_id,
        DatasetVersion.lakehouse_table_id == table.id,
    ).first()
    if not dataset:
        raise ActionValidationError("Dataset not found for table")
    return dataset


def _latest_version(db: Session, table_id: UUID, version_id: UUID | None = None) -> DatasetVersion:
    if version_id:
        source = db.query(DatasetVersion).filter(
            DatasetVersion.id == version_id,
            DatasetVersion.lakehouse_table_id == table_id,
            DatasetVersion.status == LakehouseVersionStatus.COMPLETED,
        ).first()
    else:
        source = db.query(DatasetVersion).filter(
            DatasetVersion.lakehouse_table_id == table_id,
            DatasetVersion.status == LakehouseVersionStatus.COMPLETED,
        ).order_by(DatasetVersion.version_number.desc()).first()
    if not source:
        raise ActionValidationError("Source version not found")
    return source


def _preview_profile(db: Session, workspace_id: UUID, args: dict[str, Any]) -> dict[str, Any]:
    payload = ProfileDatasetArgs.model_validate(args)
    dataset = _scoped_dataset(db, workspace_id, payload.dataset_id)
    if dataset.ingestion_status != DatasetStatus.COMPLETED:
        raise ActionValidationError("Dataset is not ready for profiling")
    return {
        "action": "profile_dataset",
        "dataset_id": str(dataset.id),
        "dataset_name": dataset.name,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "writes": False,
        "note": "Preview only — profiling metrics will be computed on execute",
    }


def _execute_profile(db: Session, workspace_id: UUID, user: User, args: dict[str, Any]) -> dict[str, Any]:
    payload = ProfileDatasetArgs.model_validate(args)
    dataset = _scoped_dataset(db, workspace_id, payload.dataset_id)
    if dataset.ingestion_status != DatasetStatus.COMPLETED:
        raise ActionValidationError("Dataset is not ready for profiling")
    asset = ensure_dataset_asset(db, workspace_id, dataset)
    profile = profile_asset(db, get_storage(), asset)
    return {
        "dataset_id": str(dataset.id),
        "asset_id": str(asset.id),
        "row_count": profile.get("row_count"),
        "column_count": profile.get("column_count"),
        "sample_rows": profile.get("sample_rows"),
    }


def _preview_promote(db: Session, workspace_id: UUID, args: dict[str, Any]) -> dict[str, Any]:
    payload = PromoteTableArgs.model_validate(args)
    table = _scoped_table(db, workspace_id, payload.table_id)
    source = _latest_version(db, table.id, payload.source_version_id)
    rank = {"BRONZE": 1, "SILVER": 2, "GOLD": 3}
    if rank[payload.target_layer] < rank[source.layer.value]:
        raise ActionValidationError("Promotion cannot move data backward")
    result = {
        "action": "promote_table",
        "table_id": str(table.id),
        "table_name": table.name,
        "source_version": source.version_number,
        "source_layer": source.layer.value,
        "target_layer": payload.target_layer,
        "partition_columns": payload.partition_columns,
        "writes": False,
        "note": "Preview only — a new lakehouse version will be created on execute",
    }
    result.update(_table_impact_summary(db, workspace_id, table.id))
    return result


def _execute_promote(db: Session, workspace_id: UUID, user: User, args: dict[str, Any]) -> dict[str, Any]:
    payload = PromoteTableArgs.model_validate(args)
    request = PromoteRequest(
        target_layer=payload.target_layer,
        source_version_id=payload.source_version_id,
        partition_columns=payload.partition_columns,
    )
    table = _scoped_table(db, workspace_id, payload.table_id)
    dataset = _dataset_for_table(db, table)
    storage = get_storage()
    source = _latest_version(db, table.id, request.source_version_id)
    target = LakehouseLayer(request.target_layer)
    rank = {"BRONZE": 1, "SILVER": 2, "GOLD": 3}
    if rank[target.value] < rank[source.layer.value]:
        raise ActionValidationError("Promotion cannot move data backward")

    temp_dir, source_path = copy_source_to_temp(storage, source.storage_key, f".{source.file_format}")
    try:
        if target == LakehouseLayer.SILVER:
            frame = normalize_frame(read_source(source_path, source.file_format))
        else:
            frame = (
                pl.read_parquet(source_path)
                if source.file_format == "parquet"
                else normalize_frame(read_source(source_path, source.file_format))
            )
        for column in request.partition_columns:
            if column not in frame.columns:
                raise ActionValidationError(f"Unknown partition column: {column}")
        output_dir = tempfile.TemporaryDirectory(prefix="pylake-autopilot-promote-")
        output = Path(output_dir.name) / "data.parquet"
        write_parquet(frame, output)
        checksum = checksum_file(output)
        number = _next_version(db, dataset.id)
        key = f"workspaces/{workspace_id}/{target.value.lower()}/{dataset.id}/versions/{number}/data/data.parquet"
        with output.open("rb") as source_file:
            storage.upload(key, source_file, "application/vnd.apache.parquet")
        size = output.stat().st_size
        schema = frame_schema(frame)
        if request.partition_columns:
            schema["partition_columns"] = request.partition_columns
        version = DatasetVersion(
            dataset_id=dataset.id,
            lakehouse_table_id=table.id,
            version_number=number,
            layer=target,
            storage_key=key,
            schema_json=schema,
            row_count=frame.height,
            column_count=frame.width,
            file_size_bytes=size,
            file_format="parquet",
            checksum=checksum,
            created_by=user.id,
            status=LakehouseVersionStatus.COMPLETED,
        )
        db.add(version)
        db.flush()
        db.add(StorageObject(
            workspace_id=workspace_id,
            dataset_id=dataset.id,
            version_id=version.id,
            layer=target,
            storage_key=key,
            file_size_bytes=size,
            checksum=checksum,
        ))
        table.current_layer = target
        source_asset = ensure_dataset_asset(db, workspace_id, dataset)
        target_asset = ensure_table_asset(db, workspace_id, table)
        record_lineage(
            db,
            workspace_id,
            "TRANSFORM" if source.layer != target else "PROMOTE",
            "DATASET_VERSION",
            str(source.id),
            "DATASET_VERSION",
            str(version.id),
            source_asset_id=source_asset.id,
            target_asset_id=target_asset.id,
            execution_status="SUCCESS",
            execution_id=str(version.id),
            metadata={
                "source_version": source.version_number,
                "target_version": version.version_number,
                "layer": target.value,
                "via": "autopilot",
            },
        )
        db.flush()
        output_dir.cleanup()
        return {
            "table_id": str(table.id),
            "version_id": str(version.id),
            "version_number": version.version_number,
            "layer": target.value,
            "row_count": version.row_count,
        }
    finally:
        temp_dir.cleanup()


def _preview_transform(db: Session, workspace_id: UUID, args: dict[str, Any]) -> dict[str, Any]:
    payload = ApplyTransformationArgs.model_validate(args)
    table = _scoped_table(db, workspace_id, payload.table_id)
    draft = validate_transformation_draft(
        db,
        workspace_id,
        {
            "transformation_type": payload.transformation_type,
            "configuration": payload.configuration,
            "target_layer": payload.target_layer,
            "source_version_id": payload.source_version_id,
        },
        None,
        payload.table_id,
    )
    source = _latest_version(db, table.id, payload.source_version_id)
    result = {
        "action": "apply_transformation",
        "table_id": str(table.id),
        "table_name": table.name,
        "transformation_type": draft.transformation_type,
        "target_layer": draft.target_layer,
        "source_version": source.version_number,
        "writes": False,
        "note": "Preview only — a new lakehouse version will be created on execute",
    }
    result.update(_table_impact_summary(db, workspace_id, table.id))
    return result


def _table_impact_summary(db: Session, workspace_id: UUID, table_id: UUID) -> dict[str, Any]:
    """Include existing downstream context in previews when dependencies exist."""
    from app.impact.graph import build_graph

    asset = db.query(CatalogAsset).filter(CatalogAsset.workspace_id == workspace_id,
        CatalogAsset.lakehouse_table_id == table_id).first()
    if not asset:
        return {}
    graph = build_graph(db, workspace_id, asset.id, depth=5)
    dependents = [node for node in graph["nodes"] if node.get("type") in {
        "pipeline_step", "saved_query", "observed_query", "asset"} and node.get("id") != f"asset:{asset.id}"]
    if not dependents:
        return {}
    return {"impact_summary": {"downstream_count": len(dependents), "truncated": graph["truncated"],
        "uncovered": graph["uncovered"],
        "note": "Existing downstream dependencies may be affected; this preview does not apply changes."}}


def _preview_impact(db: Session, workspace_id: UUID, args: dict[str, Any]) -> dict[str, Any]:
    from app.impact.simulate import simulate_change

    payload = SimulateImpactArgs.model_validate(args)
    try:
        result = simulate_change(db, workspace_id, payload.asset_id, payload.change)
    except (LookupError, ValueError) as error:
        raise ActionValidationError(str(error)) from error
    return {"action": "simulate_impact", "writes": False, "simulation": result}


def _execute_impact(db: Session, workspace_id: UUID, user: User, args: dict[str, Any]) -> dict[str, Any]:
    return _preview_impact(db, workspace_id, args)


def _execute_transform(db: Session, workspace_id: UUID, user: User, args: dict[str, Any]) -> dict[str, Any]:
    payload = ApplyTransformationArgs.model_validate(args)
    draft = validate_transformation_draft(
        db,
        workspace_id,
        {
            "transformation_type": payload.transformation_type,
            "configuration": payload.configuration,
            "target_layer": payload.target_layer,
            "source_version_id": payload.source_version_id,
        },
        None,
        payload.table_id,
    )
    table = _scoped_table(db, workspace_id, payload.table_id)
    dataset = _dataset_for_table(db, table)
    storage = get_storage()
    source = _latest_version(db, table.id, draft.source_version_id)
    record = TransformationRecord(
        dataset_id=dataset.id,
        source_version_id=source.id,
        transformation_type=draft.transformation_type,
        configuration_json=draft.configuration,
        created_by=user.id,
        execution_status=TransformationStatus.PENDING,
    )
    db.add(record)
    db.flush()

    temp_dir, source_path = copy_source_to_temp(storage, source.storage_key, f".{source.file_format}")
    try:
        frame = normalize_frame(read_source(source_path, source.file_format))
        operation = draft.transformation_type
        config = draft.configuration

        if operation == "rename":
            mapping = config.get("mapping")
            if not isinstance(mapping, dict):
                raise ActionValidationError("Rename mapping is required")
            frame = frame.rename(mapping)
        elif operation == "drop":
            frame = frame.drop(config["columns"])
        elif operation == "cast":
            allowed = {
                "string": pl.String, "int": pl.Int64, "float": pl.Float64,
                "boolean": pl.Boolean, "date": pl.Date, "datetime": pl.Datetime("us"),
            }
            expressions = [
                pl.col(column).cast(allowed[type_name], strict=False)
                for column, type_name in config["columns"].items()
            ]
            frame = frame.with_columns(expressions)
        elif operation == "deduplicate":
            columns = config.get("columns")
            frame = frame.unique(subset=columns if isinstance(columns, list) else None)
        elif operation == "filter":
            expression = config["expression"]
            column = expression["column"]
            operator = expression["operator"]
            value = expression["value"]
            series = pl.col(column)
            operations = {
                "eq": series == value, "neq": series != value, "gt": series > value,
                "gte": series >= value, "lt": series < value, "lte": series <= value,
                "contains": series.cast(pl.String).str.contains(str(value)),
            }
            frame = frame.filter(operations[operator])
        elif operation == "fill_null":
            frame = frame.with_columns([
                pl.col(column).fill_null(config["value"]) for column in config["columns"]
            ])
        elif operation == "normalize_names":
            mapping = {
                column: column.strip().lower().replace(" ", "_").replace("-", "_")
                for column in frame.columns
            }
            frame = frame.rename(mapping)
        elif operation == "calculated":
            expressions = {
                "add": pl.col(config["source_column"]) + config["operand"],
                "subtract": pl.col(config["source_column"]) - config["operand"],
                "multiply": pl.col(config["source_column"]) * config["operand"],
                "divide": pl.col(config["source_column"]) / config["operand"],
            }
            frame = frame.with_columns(expressions[config["operator"]].alias(config["name"]))
        elif operation == "select":
            frame = frame.select(config["columns"])
        elif operation == "sort":
            frame = frame.sort(config["columns"], descending=bool(config.get("descending", False)))

        target = LakehouseLayer(draft.target_layer)
        output_dir = tempfile.TemporaryDirectory(prefix="pylake-autopilot-transform-")
        output = Path(output_dir.name) / "data.parquet"
        write_parquet(frame, output)
        checksum = checksum_file(output)
        number = _next_version(db, dataset.id)
        key = f"workspaces/{workspace_id}/{target.value.lower()}/{dataset.id}/versions/{number}/data/data.parquet"
        with output.open("rb") as source_file:
            storage.upload(key, source_file, "application/vnd.apache.parquet")
        size = output.stat().st_size
        version = DatasetVersion(
            dataset_id=dataset.id,
            lakehouse_table_id=table.id,
            version_number=number,
            layer=target,
            storage_key=key,
            schema_json=frame_schema(frame),
            row_count=frame.height,
            column_count=frame.width,
            file_size_bytes=size,
            file_format="parquet",
            checksum=checksum,
            created_by=user.id,
            status=LakehouseVersionStatus.COMPLETED,
        )
        db.add(version)
        db.flush()
        record.output_version_id = version.id
        record.execution_status = TransformationStatus.COMPLETED
        db.add(StorageObject(
            workspace_id=workspace_id,
            dataset_id=dataset.id,
            version_id=version.id,
            layer=target,
            storage_key=key,
            file_size_bytes=size,
            checksum=checksum,
        ))
        table.current_layer = target
        source_asset = ensure_dataset_asset(db, workspace_id, dataset)
        target_asset = ensure_table_asset(db, workspace_id, table)
        record_lineage(
            db,
            workspace_id,
            "TRANSFORM",
            "DATASET_VERSION",
            str(source.id),
            "DATASET_VERSION",
            str(version.id),
            source_asset_id=source_asset.id,
            target_asset_id=target_asset.id,
            execution_status="COMPLETED",
            execution_id=str(record.id),
            metadata={
                "transformation_type": draft.transformation_type,
                "source_version": source.version_number,
                "target_version": version.version_number,
                "via": "autopilot",
            },
        )
        db.flush()
        output_dir.cleanup()
        return {
            "table_id": str(table.id),
            "version_id": str(version.id),
            "version_number": version.version_number,
            "layer": target.value,
            "transformation_type": draft.transformation_type,
        }
    except Exception:
        record.execution_status = TransformationStatus.FAILED
        db.flush()
        raise
    finally:
        temp_dir.cleanup()


def _preview_sql(db: Session, workspace_id: UUID, args: dict[str, Any]) -> dict[str, Any]:
    payload = RunReadonlySqlArgs.model_validate(args)
    try:
        table_names, _ = validate_read_only_sql(payload.sql)
        resolve_catalog(db, workspace_id, table_names)
    except (SQLValidationError, KeyError) as error:
        raise ActionValidationError(str(error)) from error
    return {
        "action": "run_readonly_sql",
        "tables": sorted(table_names),
        "limit": payload.limit,
        "valid": True,
        "writes": False,
        "note": "Preview only — SQL was validated and will not execute until approved",
    }


def _execute_sql(db: Session, workspace_id: UUID, user: User, args: dict[str, Any]) -> dict[str, Any]:
    payload = RunReadonlySqlArgs.model_validate(args)
    try:
        result = execute_workspace_query(
            db=db,
            storage=get_storage(),
            workspace_id=workspace_id,
            sql=payload.sql,
            limit=payload.limit,
        )
    except SQLValidationError as error:
        raise ActionValidationError(str(error)) from error
    return {
        "returned_rows": result["returned_rows"],
        "truncated": result["truncated"],
        "duration_ms": result["duration_ms"],
        "columns": [column.get("name") for column in result["columns"]],
    }


def _preview_pipeline(db: Session, workspace_id: UUID, args: dict[str, Any]) -> dict[str, Any]:
    payload = CreatePipelineArgs.model_validate(args)
    draft = validate_pipeline_draft(
        db,
        workspace_id,
        {
            "name": payload.name,
            "description": payload.description,
            "status": "DRAFT",
            "steps": payload.steps,
        },
    )
    return {
        "action": "create_pipeline",
        "name": draft.name,
        "step_count": len(draft.steps),
        "status": "DRAFT",
        "writes": False,
        "note": "Preview only — a DRAFT pipeline will be created on execute",
    }


def _execute_pipeline(db: Session, workspace_id: UUID, user: User, args: dict[str, Any]) -> dict[str, Any]:
    payload = CreatePipelineArgs.model_validate(args)
    draft = validate_pipeline_draft(
        db,
        workspace_id,
        {
            "name": payload.name,
            "description": payload.description,
            "status": "DRAFT",
            "steps": payload.steps,
        },
    )
    if db.query(Pipeline).filter(
        Pipeline.workspace_id == workspace_id,
        Pipeline.name == draft.name,
    ).first():
        raise ActionValidationError("A pipeline with this name already exists")
    pipeline = Pipeline(
        workspace_id=workspace_id,
        name=draft.name.strip(),
        description=draft.description,
        status=PipelineStatus.DRAFT,
        configuration_json={},
        created_by=user.id,
    )
    db.add(pipeline)
    db.flush()
    for step in draft.steps:
        db.add(PipelineStep(
            pipeline_id=pipeline.id,
            step_key=step.step_key,
            name=step.name,
            step_type=step.step_type,
            configuration_json=step.configuration,
            dependencies_json=step.dependencies,
            execution_order=step.execution_order,
        ))
    db.flush()
    return {
        "pipeline_id": str(pipeline.id),
        "name": pipeline.name,
        "status": pipeline.status.value,
        "step_count": len(draft.steps),
    }


def _preview_schedule(db: Session, workspace_id: UUID, args: dict[str, Any]) -> dict[str, Any]:
    payload = CreateScheduleArgs.model_validate(args)
    pipeline = db.query(Pipeline).filter(
        Pipeline.id == payload.pipeline_id,
        Pipeline.workspace_id == workspace_id,
    ).first()
    if not pipeline:
        raise ActionValidationError("Pipeline not found in workspace")
    try:
        ZoneInfo(payload.timezone)
    except Exception as error:
        raise ActionValidationError("Invalid timezone") from error
    if not croniter.is_valid(payload.cron_expression):
        raise ActionValidationError("Invalid cron expression")
    return {
        "action": "create_schedule",
        "pipeline_id": str(pipeline.id),
        "pipeline_name": pipeline.name,
        "cron_expression": payload.cron_expression,
        "timezone": payload.timezone,
        "enabled": payload.enabled,
        "writes": False,
        "note": "Preview only — schedule will be created on execute",
    }


def _execute_schedule(db: Session, workspace_id: UUID, user: User, args: dict[str, Any]) -> dict[str, Any]:
    payload = CreateScheduleArgs.model_validate(args)
    pipeline = db.query(Pipeline).filter(
        Pipeline.id == payload.pipeline_id,
        Pipeline.workspace_id == workspace_id,
    ).first()
    if not pipeline:
        raise ActionValidationError("Pipeline not found in workspace")
    try:
        tz = ZoneInfo(payload.timezone)
    except Exception as error:
        raise ActionValidationError("Invalid timezone") from error
    if not croniter.is_valid(payload.cron_expression):
        raise ActionValidationError("Invalid cron expression")
    next_run = croniter(payload.cron_expression, datetime.now(tz)).get_next(datetime)
    schedule = PipelineSchedule(
        pipeline_id=pipeline.id,
        workspace_id=workspace_id,
        cron_expression=payload.cron_expression,
        timezone=payload.timezone,
        enabled=payload.enabled,
        next_run_at=next_run.replace(tzinfo=None),
    )
    db.add(schedule)
    db.flush()
    return {
        "schedule_id": str(schedule.id),
        "pipeline_id": str(pipeline.id),
        "cron_expression": schedule.cron_expression,
        "next_run_at": next_run.isoformat(),
    }


def _preview_trust(db: Session, workspace_id: UUID, args: dict[str, Any]) -> dict[str, Any]:
    payload = ComputeTrustArgs.model_validate(args)
    asset = db.query(CatalogAsset).filter(CatalogAsset.id == payload.asset_id,
        CatalogAsset.workspace_id == workspace_id).first()
    if not asset:
        raise ActionValidationError("Catalog asset not found in workspace")
    return {"action": "compute_trust", "asset_id": str(asset.id), "asset_name": asset.name,
            "writes": False, "note": "Preview only — no snapshot is stored until execution."}


def _execute_trust(db: Session, workspace_id: UUID, user: User, args: dict[str, Any]) -> dict[str, Any]:
    payload = ComputeTrustArgs.model_validate(args)
    asset = db.query(CatalogAsset).filter(CatalogAsset.id == payload.asset_id,
        CatalogAsset.workspace_id == workspace_id).first()
    if not asset:
        raise ActionValidationError("Catalog asset not found in workspace")
    snapshot = trust_service.compute_trust(db, get_storage(), workspace_id, asset, "AUTOPILOT", user.id)
    return {"snapshot_id": snapshot["id"], "asset_id": str(asset.id),
            "overall_score": snapshot["overall_score"], "sample_rows": snapshot["sample_rows"]}


def _preview_quality_rule(db: Session, workspace_id: UUID, args: dict[str, Any]) -> dict[str, Any]:
    payload = CreateQualityRuleArgs.model_validate(args)
    asset = db.query(CatalogAsset).filter(CatalogAsset.id == payload.asset_id,
        CatalogAsset.workspace_id == workspace_id).first()
    if not asset:
        raise ActionValidationError("Catalog asset not found in workspace")
    return {"action": "create_quality_rule", "asset_id": str(asset.id), "asset_name": asset.name,
            "rule_type": payload.rule_type, "column_name": payload.column_name,
            "severity": payload.severity, "writes": False,
            "note": "Preview only — the rule will be saved after approval."}


def _execute_quality_rule(db: Session, workspace_id: UUID, user: User, args: dict[str, Any]) -> dict[str, Any]:
    payload = CreateQualityRuleArgs.model_validate(args)
    asset = db.query(CatalogAsset).filter(CatalogAsset.id == payload.asset_id,
        CatalogAsset.workspace_id == workspace_id).first()
    if not asset:
        raise ActionValidationError("Catalog asset not found in workspace")
    rule = QualityRule(workspace_id=workspace_id, asset_id=asset.id, column_name=payload.column_name,
        rule_type=QualityRuleType(payload.rule_type), config_json=payload.config_json,
        severity=QualityRuleSeverity(payload.severity), enabled=payload.enabled, created_by=user.id)
    db.add(rule); db.flush()
    record_audit(db, workspace_id, user.id, "QUALITY_RULE_CREATED", "quality_rule", rule.id,
                 {"source": "autopilot", "rule_type": rule.rule_type.value})
    return {"quality_rule_id": str(rule.id), "asset_id": str(asset.id), "rule_type": rule.rule_type.value}


ACTION_REGISTRY: dict[str, ActionDefinition] = {
    "profile_dataset": ActionDefinition(
        key="profile_dataset",
        title="Profile dataset",
        min_role="VIEWER",
        risk_level="LOW",
        requires_approval=False,
        args_schema=ProfileDatasetArgs,
        preview=_preview_profile,
        execute=_execute_profile,
    ),
    "promote_table": ActionDefinition(
        key="promote_table",
        title="Promote table",
        min_role="EDITOR",
        risk_level="MEDIUM",
        requires_approval=True,
        args_schema=PromoteTableArgs,
        preview=_preview_promote,
        execute=_execute_promote,
    ),
    "apply_transformation": ActionDefinition(
        key="apply_transformation",
        title="Apply transformation",
        min_role="EDITOR",
        risk_level="MEDIUM",
        requires_approval=True,
        args_schema=ApplyTransformationArgs,
        preview=_preview_transform,
        execute=_execute_transform,
    ),
    "run_readonly_sql": ActionDefinition(
        key="run_readonly_sql",
        title="Run read-only SQL",
        min_role="VIEWER",
        risk_level="LOW",
        requires_approval=False,
        args_schema=RunReadonlySqlArgs,
        preview=_preview_sql,
        execute=_execute_sql,
    ),
    "create_pipeline": ActionDefinition(
        key="create_pipeline",
        title="Create pipeline",
        min_role="EDITOR",
        risk_level="MEDIUM",
        requires_approval=True,
        args_schema=CreatePipelineArgs,
        preview=_preview_pipeline,
        execute=_execute_pipeline,
    ),
    "create_schedule": ActionDefinition(
        key="create_schedule",
        title="Create schedule",
        min_role="EDITOR",
        risk_level="MEDIUM",
        requires_approval=True,
        args_schema=CreateScheduleArgs,
        preview=_preview_schedule,
        execute=_execute_schedule,
    ),
    "compute_trust": ActionDefinition(
        key="compute_trust", title="Compute Trust Passport", min_role="VIEWER",
        risk_level="LOW", requires_approval=False, args_schema=ComputeTrustArgs,
        preview=_preview_trust, execute=_execute_trust,
    ),
    "create_quality_rule": ActionDefinition(
        key="create_quality_rule", title="Create quality rule", min_role="EDITOR",
        risk_level="MEDIUM", requires_approval=True, args_schema=CreateQualityRuleArgs,
        preview=_preview_quality_rule, execute=_execute_quality_rule,
    ),
    "simulate_impact": ActionDefinition(
        key="simulate_impact", title="Simulate schema impact", min_role="VIEWER",
        risk_level="LOW", requires_approval=False, args_schema=SimulateImpactArgs,
        preview=_preview_impact, execute=_execute_impact,
    ),
}


def get_action(action_key: str) -> ActionDefinition:
    action = ACTION_REGISTRY.get(action_key)
    if not action:
        raise ActionValidationError(f"Unknown action: {action_key}")
    return action


def validate_action_arguments(
    db: Session,
    workspace_id: UUID,
    action_key: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Validate action key + args against allowlist and workspace resources. No writes."""
    try:
        action = get_action(action_key)
    except ActionValidationError:
        raise
    try:
        parsed = action.args_schema.model_validate(arguments)
    except ValidationError as error:
        raise ActionValidationError("Invalid action arguments") from error
    # Run preview to resolve workspace-scoped IDs and reject foreign resources.
    action.preview(db, workspace_id, parsed.model_dump(mode="json"))
    return parsed.model_dump(mode="json")


def role_satisfies(role: str, minimum: str) -> bool:
    return ROLE_RANK.get(role, -1) >= ROLE_RANK.get(minimum, 999)


def max_min_role(action_keys: list[str]) -> str:
    best = "VIEWER"
    for key in action_keys:
        action = get_action(key)
        if ROLE_RANK[action.min_role] > ROLE_RANK[best]:
            best = action.min_role
    return best
