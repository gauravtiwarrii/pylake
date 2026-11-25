import hashlib
import tempfile
from pathlib import Path
from uuid import UUID

import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.v1.workspaces import membership, require_role
from app.core.db import get_db
from app.models.entities import (
    Dataset,
    DatasetVersion,
    LakehouseLayer,
    LakehouseTable,
    LakehouseVersionStatus,
    StorageObject,
    TransformationRecord,
    TransformationStatus,
    User,
    WorkspaceRole,
)
from app.schemas.lakehouse import (
    DatasetVersionResponse,
    LakehouseTableResponse,
    PromoteRequest,
    TransformRequest,
)
from app.services.lakehouse import (
    checksum_file,
    copy_source_to_temp,
    frame_schema,
    normalize_frame,
    quality_summary,
    read_source,
    write_parquet,
)
from app.storage.factory import get_storage
from app.core.audit import record_audit

router = APIRouter(prefix="/workspaces", tags=["lakehouse"])


def scoped_table(db: Session, workspace_id: UUID, table_id: UUID) -> LakehouseTable:
    table = db.query(LakehouseTable).filter(
        LakehouseTable.id == table_id,
        LakehouseTable.workspace_id == workspace_id,
    ).first()
    if not table:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lakehouse table not found")
    return table


def scoped_dataset(db: Session, table: LakehouseTable) -> Dataset:
    dataset = db.query(Dataset).join(DatasetVersion).filter(
        Dataset.id == DatasetVersion.dataset_id,
        DatasetVersion.lakehouse_table_id == table.id,
    ).first()
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return dataset


def next_version(db: Session, dataset_id: UUID) -> int:
    maximum = db.query(func.max(DatasetVersion.version_number)).filter(DatasetVersion.dataset_id == dataset_id).scalar()
    return int(maximum or 0) + 1


@router.get("/{workspace_id}/lakehouse/tables", response_model=list[LakehouseTableResponse])
def list_tables(
    workspace_id: UUID,
    layer: str | None = Query(default=None),
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[LakehouseTable]:
    membership(db, workspace_id, user.id)
    query = db.query(LakehouseTable).filter(LakehouseTable.workspace_id == workspace_id)
    if layer:
        try:
            query = query.filter(LakehouseTable.current_layer == LakehouseLayer(layer.upper()))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid lakehouse layer")
    if search:
        query = query.filter(LakehouseTable.name.ilike(f"%{search}%"))
    return query.order_by(LakehouseTable.updated_at.desc()).all()


@router.get("/{workspace_id}/lakehouse/tables/{table_id}", response_model=LakehouseTableResponse)
def get_table(
    workspace_id: UUID,
    table_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LakehouseTable:
    membership(db, workspace_id, user.id)
    return scoped_table(db, workspace_id, table_id)


@router.get("/{workspace_id}/lakehouse/tables/{table_id}/versions", response_model=list[DatasetVersionResponse])
def version_history(
    workspace_id: UUID,
    table_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DatasetVersion]:
    membership(db, workspace_id, user.id)
    table = scoped_table(db, workspace_id, table_id)
    return db.query(DatasetVersion).filter(
        DatasetVersion.lakehouse_table_id == table.id
    ).order_by(DatasetVersion.created_at.asc()).all()


@router.get("/{workspace_id}/lakehouse/tables/{table_id}/versions/{version_id}", response_model=DatasetVersionResponse)
def get_version(
    workspace_id: UUID,
    table_id: UUID,
    version_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatasetVersion:
    membership(db, workspace_id, user.id)
    table = scoped_table(db, workspace_id, table_id)
    version = db.query(DatasetVersion).filter(
        DatasetVersion.id == version_id,
        DatasetVersion.lakehouse_table_id == table.id,
    ).first()
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset version not found")
    return version


@router.post("/{workspace_id}/lakehouse/tables/{table_id}/promote", response_model=DatasetVersionResponse)
def promote_table(
    workspace_id: UUID,
    table_id: UUID,
    payload: PromoteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatasetVersion:
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    table = scoped_table(db, workspace_id, table_id)
    dataset = scoped_dataset(db, table)
    storage = get_storage()

    if payload.source_version_id:
        source = db.query(DatasetVersion).filter(
            DatasetVersion.id == payload.source_version_id,
            DatasetVersion.lakehouse_table_id == table.id,
            DatasetVersion.status == LakehouseVersionStatus.COMPLETED,
        ).first()
    else:
        source = db.query(DatasetVersion).filter(
            DatasetVersion.lakehouse_table_id == table.id,
            DatasetVersion.status == LakehouseVersionStatus.COMPLETED,
        ).order_by(DatasetVersion.version_number.desc()).first()
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source version not found")

    target = LakehouseLayer(payload.target_layer)
    rank = {"BRONZE": 1, "SILVER": 2, "GOLD": 3}
    if target == LakehouseLayer.BRONZE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bronze is the immutable source layer")
    if rank[target.value] < rank[source.layer.value]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Promotion cannot move data backward")

    temp_dir, source_path = copy_source_to_temp(storage, source.storage_key, f".{source.file_format}")
    output: Path | None = None
    try:
        if target == LakehouseLayer.SILVER:
            frame = normalize_frame(read_source(source_path, source.file_format))
        else:
            frame = pl.read_parquet(source_path) if source.file_format == "parquet" else normalize_frame(read_source(source_path, source.file_format))

        for column in payload.partition_columns:
            if column not in frame.columns:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown partition column: {column}")
        if payload.partition_columns:
            for column in payload.partition_columns:
                if frame[column].n_unique() > max(100, frame.height // 10):
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Partition column would create too many partitions")

        output_dir = tempfile.TemporaryDirectory(prefix="pylake-output-")
        output = Path(output_dir.name) / "data.parquet"
        write_parquet(frame, output)
        checksum = checksum_file(output)
        number = next_version(db, dataset.id)
        key = f"workspaces/{workspace_id}/{target.value.lower()}/{dataset.id}/versions/{number}/data/data.parquet"
        with output.open("rb") as source_file:
            storage.upload(key, source_file, "application/vnd.apache.parquet")
        size = output.stat().st_size
        schema = frame_schema(frame)
        if payload.partition_columns:
            schema["partition_columns"] = payload.partition_columns
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
        record_audit(db, workspace_id, user.id, "DATASET_VERSION_PROMOTED", "dataset_version", version.id, {"target_layer": target.value})
        db.commit()
        db.refresh(version)
        output_dir.cleanup()
        return version
    finally:
        temp_dir.cleanup()


@router.post("/{workspace_id}/lakehouse/tables/{table_id}/transform", response_model=DatasetVersionResponse)
def transform_table(
    workspace_id: UUID,
    table_id: UUID,
    payload: TransformRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatasetVersion:
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    table = scoped_table(db, workspace_id, table_id)
    dataset = scoped_dataset(db, table)
    storage = get_storage()

    if payload.source_version_id:
        source = db.query(DatasetVersion).filter(
            DatasetVersion.id == payload.source_version_id,
            DatasetVersion.lakehouse_table_id == table.id,
            DatasetVersion.status == LakehouseVersionStatus.COMPLETED,
        ).first()
    else:
        source = db.query(DatasetVersion).filter(
            DatasetVersion.lakehouse_table_id == table.id,
            DatasetVersion.status == LakehouseVersionStatus.COMPLETED,
        ).order_by(DatasetVersion.version_number.desc()).first()
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source version not found")

    record = TransformationRecord(
        dataset_id=dataset.id,
        source_version_id=source.id,
        transformation_type=payload.transformation_type,
        configuration_json=payload.configuration,
        created_by=user.id,
        execution_status=TransformationStatus.PENDING,
    )
    db.add(record)
    db.flush()

    temp_dir, source_path = copy_source_to_temp(storage, source.storage_key, f".{source.file_format}")
    try:
        frame = read_source(source_path, source.file_format)
        frame = normalize_frame(frame)
        operation = payload.transformation_type
        config = payload.configuration

        if operation == "rename":
            mapping = config.get("mapping")
            if not isinstance(mapping, dict):
                raise ValueError("Rename mapping is required")
            for old, new in mapping.items():
                if old not in frame.columns:
                    raise ValueError(f"Unknown column: {old}")
                if not isinstance(new, str) or not new:
                    raise ValueError("New column names must be non-empty strings")
            frame = frame.rename(mapping)
        elif operation == "drop":
            columns = config.get("columns")
            if not isinstance(columns, list):
                raise ValueError("Drop columns must be a list")
            unknown = set(columns) - set(frame.columns)
            if unknown:
                raise ValueError(f"Unknown columns: {', '.join(sorted(unknown))}")
            frame = frame.drop(columns)
        elif operation == "cast":
            casts = config.get("columns")
            if not isinstance(casts, dict):
                raise ValueError("Cast columns must be an object")
            allowed = {"string": pl.String, "int": pl.Int64, "float": pl.Float64, "boolean": pl.Boolean, "date": pl.Date, "datetime": pl.Datetime("us")}
            expressions = []
            for column, type_name in casts.items():
                if column not in frame.columns:
                    raise ValueError(f"Unknown column: {column}")
                if type_name not in allowed:
                    raise ValueError(f"Unsupported cast type: {type_name}")
                expressions.append(pl.col(column).cast(allowed[type_name], strict=False))
            frame = frame.with_columns(expressions)
        elif operation == "deduplicate":
            columns = config.get("columns")
            frame = frame.unique(subset=columns if isinstance(columns, list) else None)
        elif operation == "filter":
            expression = config.get("expression")
            if not isinstance(expression, dict):
                raise ValueError("Filter expression is required")
            column = expression.get("column")
            operator = expression.get("operator")
            value = expression.get("value")
            if column not in frame.columns or operator not in {"eq", "neq", "gt", "gte", "lt", "lte", "contains"}:
                raise ValueError("Invalid filter expression")
            series = pl.col(column)
            operations = {"eq": series == value, "neq": series != value, "gt": series > value, "gte": series >= value, "lt": series < value, "lte": series <= value, "contains": series.cast(pl.String).str.contains(str(value))}
            frame = frame.filter(operations[operator])
        elif operation == "fill_null":
            columns = config.get("columns")
            value = config.get("value")
            if not isinstance(columns, list) or not all(column in frame.columns for column in columns):
                raise ValueError("Invalid fill-null columns")
            frame = frame.with_columns([pl.col(column).fill_null(value) for column in columns])
        elif operation == "normalize_names":
            mapping = {column: column.strip().lower().replace(" ", "_").replace("-", "_") for column in frame.columns}
            frame = frame.rename(mapping)
        elif operation == "calculated":
            name = config.get("name")
            source_column = config.get("source_column")
            operator = config.get("operator")
            operand = config.get("operand")
            if not isinstance(name, str) or not name or source_column not in frame.columns:
                raise ValueError("Invalid calculated-column configuration")
            if operator not in {"add", "subtract", "multiply", "divide"} or not isinstance(operand, (int, float)):
                raise ValueError("Unsupported calculated-column operation")
            expressions = {"add": pl.col(source_column) + operand, "subtract": pl.col(source_column) - operand, "multiply": pl.col(source_column) * operand, "divide": pl.col(source_column) / operand}
            frame = frame.with_columns(expressions[operator].alias(name))
        elif operation == "select":
            columns = config.get("columns")
            if not isinstance(columns, list) or not all(column in frame.columns for column in columns):
                raise ValueError("Invalid select columns")
            frame = frame.select(columns)
        elif operation == "sort":
            columns = config.get("columns")
            descending = bool(config.get("descending", False))
            if not isinstance(columns, list) or not all(column in frame.columns for column in columns):
                raise ValueError("Invalid sort columns")
            frame = frame.sort(columns, descending=descending)

        target = LakehouseLayer(payload.target_layer)
        output_dir = tempfile.TemporaryDirectory(prefix="pylake-transform-")
        output = Path(output_dir.name) / "data.parquet"
        write_parquet(frame, output)
        checksum = checksum_file(output)
        number = next_version(db, dataset.id)
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
        record_audit(db, workspace_id, user.id, "DATASET_TRANSFORMED", "dataset_version", version.id, {"target_layer": target.value})
        db.commit()
        db.refresh(version)
        output_dir.cleanup()
        return version
    except Exception as error:
        record.execution_status = TransformationStatus.FAILED
        record.error_message = str(error)[:1000]
        db.commit()
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Transformation failed") from error
    finally:
        temp_dir.cleanup()


@router.get("/{workspace_id}/lakehouse/tables/{table_id}/quality")
def table_quality(
    workspace_id: UUID,
    table_id: UUID,
    version_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    membership(db, workspace_id, user.id)
    table = scoped_table(db, workspace_id, table_id)
    if version_id:
        version = db.query(DatasetVersion).filter(DatasetVersion.id == version_id, DatasetVersion.lakehouse_table_id == table.id).first()
    else:
        version = db.query(DatasetVersion).filter(DatasetVersion.lakehouse_table_id == table.id).order_by(DatasetVersion.version_number.desc()).first()
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset version not found")
    storage = get_storage()
    temp_dir, path = copy_source_to_temp(storage, version.storage_key, f".{version.file_format}")
    try:
        frame = read_source(path, version.file_format)
        return {"version_id": str(version.id), "version_number": version.version_number, **quality_summary(frame)}
    finally:
        temp_dir.cleanup()


@router.get("/{workspace_id}/lakehouse/storage/usage")
def storage_usage(
    workspace_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    membership(db, workspace_id, user.id)
    rows = db.query(StorageObject.layer, func.sum(StorageObject.file_size_bytes).label("bytes"), func.count(StorageObject.id).label("objects")).filter(
        StorageObject.workspace_id == workspace_id
    ).group_by(StorageObject.layer).all()
    by_layer = {row.layer.value: {"bytes": int(row.bytes or 0), "objects": int(row.objects)} for row in rows}
    total_bytes = sum(item["bytes"] for item in by_layer.values())
    total_objects = sum(item["objects"] for item in by_layer.values())
    return {"total_bytes": total_bytes, "total_objects": total_objects, "by_layer": by_layer}
