import signal
import logging
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.engines.query_executor import execute_workspace_query
from app.models.entities import (
    Dataset,
    DatasetVersion,
    LakehouseLayer,
    LakehouseTable,
    LakehouseVersionStatus,
    Pipeline,
    PipelineRun,
    PipelineStep,
    PipelineStepRun,
    RunStatus,
    StepStatus,
)
from app.services.lakehouse import frame_schema, quality_summary, read_source, write_parquet, checksum_file
from app.services.lakehouse import copy_source_to_temp
from app.storage.factory import get_storage
from app.services.catalog import ensure_dataset_asset, ensure_table_asset
from app.services.lineage import record_lineage
from app.services import trust as trust_service

logger = logging.getLogger("pylake.pipeline")


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def elapsed_milliseconds(started_at: datetime, completed_at: datetime) -> int:
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)
    return int((completed_at - started_at).total_seconds() * 1000)


class PipelineStepTimeoutError(TimeoutError):
    pass


def run_step_with_timeout(function, timeout_seconds: int):
    if not hasattr(signal, "setitimer"):
        return function()

    def timeout_handler(signum, frame):
        raise PipelineStepTimeoutError("Pipeline step exceeded its execution timeout")

    previous = signal.signal(signal.SIGALRM, timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        return function()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def claim_next_job(worker_id: str) -> PipelineRun | None:
    db = SessionLocal()
    try:
        settings = get_settings()
        stale_before = utcnow() - timedelta(seconds=settings.pipeline_job_claim_seconds)
        run = db.query(PipelineRun).filter(
            PipelineRun.status == RunStatus.QUEUED,
        ).with_for_update(skip_locked=True).order_by(PipelineRun.created_at.asc()).first()
        if not run:
            run = db.query(PipelineRun).filter(
                PipelineRun.status == RunStatus.RUNNING,
                PipelineRun.claimed_at.is_not(None),
                PipelineRun.claimed_at < stale_before,
            ).order_by(PipelineRun.created_at.asc()).first()
            if run:
                run.status = RunStatus.QUEUED
                run.started_at = None
                run.claimed_at = None
                run.worker_id = None
        if not run:
            db.commit()
            return None
        claimed_at = utcnow()
        result = db.query(PipelineRun).filter(
            PipelineRun.id == run.id,
            PipelineRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
        ).update(
            {
                PipelineRun.status: RunStatus.RUNNING,
                PipelineRun.started_at: claimed_at,
                PipelineRun.claimed_at: claimed_at,
                PipelineRun.worker_id: worker_id,
                PipelineRun.max_retries: settings.pipeline_max_retries,
            },
            synchronize_session=False,
        )
        if result != 1:
            db.rollback()
            return None
        db.commit()
        db.expire_all()
        claimed = db.query(PipelineRun).filter(PipelineRun.id == run.id).first()
        return claimed
    finally:
        db.close()


def execute_pipeline_run(run_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        run = db.query(PipelineRun).filter(PipelineRun.id == run_id).first()
        if not run:
            return
        pipeline = db.query(Pipeline).filter(Pipeline.id == run.pipeline_id).first()
        steps = db.query(PipelineStep).filter(PipelineStep.pipeline_id == pipeline.id).order_by(PipelineStep.execution_order).all()
        if not run.started_at:
            run.started_at = utcnow()
        run.status = RunStatus.RUNNING
        db.commit()

        graph = {
            step.step_key: {
                "step_key": step.step_key,
                "step_type": step.step_type,
                "dependencies": step.dependencies_json,
                "execution_order": step.execution_order,
            }
            for step in steps
        }
        step_runs: dict[str, PipelineStepRun] = {}
        for step in steps:
            step_run = db.query(PipelineStepRun).filter(
                PipelineStepRun.pipeline_run_id == run.id,
                PipelineStepRun.pipeline_step_id == step.id,
            ).first()
            if not step_run:
                step_run = PipelineStepRun(
                    pipeline_run_id=run.id,
                    pipeline_step_id=step.id,
                    status=StepStatus.PENDING,
                    output_metadata_json={},
                )
                db.add(step_run)
                db.flush()
            elif step_run.status == StepStatus.RUNNING:
                step_run.status = StepStatus.PENDING
                step_run.started_at = None
                step_run.error_message = None
                db.flush()
            step_runs[step.step_key] = step_run
        db.commit()

        overall_failed = False
        execution_failed = False
        by_key = {step.step_key: step for step in steps}
        processed = set()
        while len(processed) < len(steps):
            ready = [
                step for step in steps
                if step.step_key not in processed
                and all(dependency in processed for dependency in (step.dependencies_json or []))
            ]
            if not ready:
                break
            step = ready[0]
            processed.add(step.step_key)
            step_run = step_runs[step.step_key]
            db.refresh(run)
            if step_run.status == StepStatus.SUCCEEDED:
                continue
            if run.status == RunStatus.CANCELLED:
                step_run.status = StepStatus.SKIPPED
                step_run.error_message = "Run cancelled"
                step_run.completed_at = utcnow()
                db.commit()
                continue
            dependency_failed = any(
                step_runs[dependency].status in {StepStatus.FAILED, StepStatus.SKIPPED}
                for dependency in (step.dependencies_json or [])
            )
            if dependency_failed:
                step_run.status = StepStatus.SKIPPED
                step_run.error_message = "Prerequisite step did not succeed"
                step_run.completed_at = utcnow()
                db.commit()
                continue

            step_run.status = StepStatus.RUNNING
            step_run.started_at = utcnow()
            db.commit()
            started = time.perf_counter()
            try:
                settings = get_settings()
                metadata = run_step_with_timeout(
                    lambda: execute_step(db, run.id, run.workspace_id, run.triggered_by, step),
                    settings.pipeline_step_timeout_seconds,
                )
                step_run.status = StepStatus.SUCCEEDED
                step_run.rows_processed = metadata.get("row_count")
                step_run.output_metadata_json = metadata
                step_run.error_message = None
            except Exception as error:
                step_run.status = StepStatus.FAILED
                step_run.error_message = str(error)[:1000]
                execution_failed = True
            finally:
                step_run.completed_at = utcnow()
                step_run.duration_ms = int((time.perf_counter() - started) * 1000)
                db.commit()

        retry_scheduled = False
        if execution_failed:
            settings = get_settings()
            if run.retry_count < run.max_retries:
                run.retry_count += 1
                run.status = RunStatus.QUEUED
                run.failure_class = "STEP_FAILURE"
                run.error_message = "Retry scheduled after step failure"
                run.started_at = None
                run.completed_at = None
                run.claimed_at = None
                run.worker_id = None
                for step in steps:
                    step_run = step_runs[step.step_key]
                    if step_run.status == StepStatus.FAILED:
                        step_run.status = StepStatus.PENDING
                        step_run.started_at = None
                        step_run.completed_at = None
                        step_run.error_message = None
                    if step_run.status == StepStatus.SKIPPED:
                        step_run.status = StepStatus.PENDING
                run.duration_ms = None
                retry_scheduled = True
            else:
                run.status = RunStatus.FAILED
                run.failure_class = "STEP_FAILURE"
                run.error_message = "One or more pipeline steps failed after retry limit"
        else:
            run.status = RunStatus.SUCCEEDED
            run.error_message = None
        if retry_scheduled:
            run.completed_at = None
        else:
            run.completed_at = utcnow()
            run.duration_ms = elapsed_milliseconds(run.started_at, run.completed_at)
        db.commit()
    finally:
        db.close()


def execute_step(db, run_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID | None, step: PipelineStep) -> dict:
    config = step.configuration_json or {}
    storage = get_storage()

    if step.step_type == "SOURCE_DATASET":
        dataset_id = config.get("dataset_id")
        if not dataset_id:
            raise ValueError("SOURCE_DATASET requires dataset_id")
        try:
            dataset_uuid = uuid.UUID(str(dataset_id))
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError("SOURCE_DATASET requires a valid dataset_id") from error
        dataset = db.query(Dataset).filter(Dataset.id == dataset_uuid, Dataset.workspace_id == workspace_id).first()
        if not dataset:
            raise ValueError("Dataset not found in workspace")
        if not storage.exists(dataset.storage_key):
            raise ValueError("Dataset source object is unavailable")
        asset = ensure_dataset_asset(db, workspace_id, dataset)
        record_lineage(
            db,
            workspace_id,
            "PIPELINE_SOURCE",
            "PIPELINE_RUN",
            str(run_id),
            "DATASET",
            str(dataset.id),
            source_asset_id=asset.id,
            target_asset_id=asset.id,
            execution_status="SUCCESS",
            execution_id=str(run_id),
            metadata={"step_id": str(step.id), "step_type": step.step_type},
        )
        return {"dataset_id": str(dataset.id), "row_count": dataset.row_count}

    if step.step_type == "SQL_QUERY":
        sql = config.get("sql")
        if not isinstance(sql, str):
            raise ValueError("SQL_QUERY requires sql")
        result = execute_workspace_query(db, storage, workspace_id, sql, config.get("limit"))
        return {"row_count": result["returned_rows"], "duration_ms": result["duration_ms"]}

    if step.step_type == "DATA_QUALITY":
        table_name = config.get("table_name")
        if not isinstance(table_name, str):
            raise ValueError("DATA_QUALITY requires table_name")
        table = db.query(LakehouseTable).filter(
            LakehouseTable.workspace_id == workspace_id,
            LakehouseTable.name.ilike(table_name),
        ).first()
        if not table:
            raise ValueError("Table not found in workspace")
        version = db.query(DatasetVersion).filter(
            DatasetVersion.lakehouse_table_id == table.id,
            DatasetVersion.status == LakehouseVersionStatus.COMPLETED,
            DatasetVersion.file_format == "parquet",
        ).order_by(DatasetVersion.version_number.desc()).first()
        if not version:
            raise ValueError("No queryable table version")
        directory, path = copy_source_to_temp(storage, version.storage_key, ".parquet")
        try:
            frame = read_source(path, "parquet")
            summary = quality_summary(frame)
            maximum_null = config.get("max_null_rows")
            maximum_duplicate = config.get("max_duplicate_rows")
            if maximum_null is not None and sum(summary["null_counts"].values()) > int(maximum_null):
                raise ValueError("Data quality null threshold exceeded")
            if maximum_duplicate is not None and summary["duplicate_rows"] > int(maximum_duplicate):
                raise ValueError("Data quality duplicate threshold exceeded")
            asset = ensure_table_asset(db, workspace_id, table)
            trust_service.compute_trust_best_effort(db, storage, workspace_id, asset, "DATA_QUALITY", user_id)
            return summary
        finally:
            directory.cleanup()

    if step.step_type in {"TRANSFORM", "MATERIALIZE"}:
        table_name = config.get("table_name")
        if not isinstance(table_name, str):
            raise ValueError("Step requires table_name")
        table = db.query(LakehouseTable).filter(
            LakehouseTable.workspace_id == workspace_id,
            LakehouseTable.name.ilike(table_name),
        ).first()
        if not table:
            raise ValueError("Table not found in workspace")
        dataset = db.query(Dataset).join(DatasetVersion).filter(
            Dataset.id == DatasetVersion.dataset_id,
            DatasetVersion.lakehouse_table_id == table.id,
        ).first()
        version = db.query(DatasetVersion).filter(
            DatasetVersion.lakehouse_table_id == table.id,
            DatasetVersion.status == LakehouseVersionStatus.COMPLETED,
        ).order_by(DatasetVersion.version_number.desc()).first()
        if not dataset or not version:
            raise ValueError("No source version available")
        directory, path = copy_source_to_temp(storage, version.storage_key, f".{version.file_format}")
        try:
            frame = read_source(path, version.file_format)
            if step.step_type == "TRANSFORM":
                operation = config.get("operation")
                if operation == "deduplicate":
                    columns = config.get("columns")
                    frame = frame.unique(subset=columns if isinstance(columns, list) else None)
                elif operation == "drop":
                    frame = frame.drop(config["columns"])
                elif operation == "select":
                    frame = frame.select(config["columns"])
                elif operation == "sort":
                    frame = frame.sort(config["columns"], descending=bool(config.get("descending", False)))
                elif operation == "fill_null":
                    frame = frame.with_columns([
                        pl.col(column).fill_null(config.get("value"))
                        for column in config["columns"]
                    ])
                elif operation not in {None, ""}:
                    raise ValueError(f"Unsupported pipeline transform: {operation}")

            target = LakehouseLayer(config.get("target_layer", "GOLD"))
            if target not in {LakehouseLayer.SILVER, LakehouseLayer.GOLD}:
                raise ValueError("Materialization target must be SILVER or GOLD")
            output_dir = tempfile.TemporaryDirectory(prefix="pylake-pipeline-")
            output = Path(output_dir.name) / "data.parquet"
            write_parquet(frame, output)
            number = int(db.query(DatasetVersion).filter(DatasetVersion.dataset_id == dataset.id).count()) + 1
            existing_numbers = {row[0] for row in db.query(DatasetVersion.version_number).filter(DatasetVersion.dataset_id == dataset.id).all()}
            while number in existing_numbers:
                number += 1
            key = f"workspaces/{workspace_id}/{target.value.lower()}/{dataset.id}/pipeline-runs/{run_id}/steps/{step.id}/data.parquet"
            existing = db.query(DatasetVersion).filter(DatasetVersion.storage_key == key).first()
            if existing:
                source_asset = ensure_table_asset(db, workspace_id, table)
                target_asset = ensure_table_asset(db, workspace_id, table)
                record_lineage(
                    db, workspace_id, "PIPELINE_MATERIALIZE",
                    "PIPELINE_RUN", str(run_id),
                    "DATASET_VERSION", str(existing.id),
                    source_asset_id=source_asset.id,
                    target_asset_id=target_asset.id,
                    execution_status="SUCCESS",
                    execution_id=str(run_id),
                    metadata={"pipeline_step_id": str(step.id), "version": existing.version_number, "layer": existing.layer.value},
                )
                db.commit()
                return {"row_count": existing.row_count, "version_id": str(existing.id), "layer": existing.layer.value}
            with output.open("rb") as source_file:
                storage.upload(key, source_file, "application/vnd.apache.parquet")
            size = output.stat().st_size
            checksum = checksum_file(output)
            schema = frame_schema(frame)
            output_version = DatasetVersion(
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
                created_by=user_id,
                status=LakehouseVersionStatus.COMPLETED,
            )
            db.add(output_version)
            db.flush()
            table.current_layer = target
            source_asset = ensure_table_asset(db, workspace_id, table)
            target_asset = ensure_table_asset(db, workspace_id, table)
            record_lineage(
                db, workspace_id, "PIPELINE_MATERIALIZE",
                "DATASET_VERSION", str(version.id),
                "DATASET_VERSION", str(output_version.id),
                source_asset_id=source_asset.id,
                target_asset_id=target_asset.id,
                execution_status="SUCCESS",
                execution_id=str(run_id),
                metadata={"pipeline_step_id": str(step.id), "source_version": version.version_number, "target_version": output_version.version_number, "layer": target.value},
            )
            db.commit()
            output_dir.cleanup()
            return {"row_count": frame.height, "version_id": str(output_version.id), "layer": target.value}
        finally:
            directory.cleanup()

    raise ValueError(f"Unsupported pipeline step type: {step.step_type}")
