import tempfile
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.v1.workspaces import membership, require_role
from app.core.config import get_settings
from app.core.db import get_db
from app.models.entities import Dataset, DatasetStatus, User, WorkspaceRole
from app.schemas.datasets import DatasetListResponse, DatasetResponse, PreviewResponse
from app.services.ingestion import detect_format, inspect_file, preview_file, sanitize_filename
from app.storage.factory import get_storage
from app.core.audit import record_audit
from app.services.catalog import ensure_dataset_asset
from app.services.lakehouse import ensure_bronze_version

router = APIRouter(prefix="/workspaces", tags=["datasets"])


def get_dataset(db: Session, workspace_id: UUID, dataset_id: UUID) -> Dataset:
    dataset = db.query(Dataset).filter(
        Dataset.id == dataset_id,
        Dataset.workspace_id == workspace_id,
    ).first()
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return dataset


def copy_object_to_temp(storage, key: str, suffix: str = "") -> tuple[tempfile.TemporaryDirectory, Path]:
    directory = tempfile.TemporaryDirectory(prefix="pylake-")
    path = Path(directory.name) / f"dataset{suffix}"
    with storage.download(key) as source:
        with path.open("wb") as target:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
    return directory, path


@router.post("/{workspace_id}/datasets/upload", response_model=DatasetResponse, status_code=status.HTTP_201_CREATED)
def upload_dataset(
    workspace_id: UUID,
    file: UploadFile = File(...),
    name: str | None = Form(default=None, max_length=200),
    description: str | None = Form(default=None, max_length=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dataset:
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    settings = get_settings()
    filename = sanitize_filename(file.filename or "dataset")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".csv", ".json", ".parquet", ".xlsx"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file format")

    try:
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to inspect upload") from error
    if size <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty files are not allowed")
    if size > settings.max_upload_size_bytes:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Upload exceeds the configured size limit")

    signature = file.file.read(8192)
    file.file.seek(0)
    file.file.seek(max(0, size - 4))
    tail_signature = file.file.read(4)
    file.file.seek(0)
    combined_signature = signature + tail_signature
    try:
        format_name, mime_type = detect_format(filename, file.content_type or "", combined_signature)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    dataset = Dataset(
        workspace_id=workspace_id,
        uploaded_by=user.id,
        name=(name or Path(filename).stem).strip()[:200],
        original_filename=filename,
        description=description.strip() if description else None,
        file_format=format_name,
        mime_type=mime_type,
        file_size_bytes=size,
        storage_backend=settings.storage_backend.lower(),
        storage_key="",
        ingestion_status=DatasetStatus.PENDING,
    )
    db.add(dataset)
    db.flush()
    dataset.storage_key = f"workspaces/{workspace_id}/datasets/{dataset.id}/{filename}"
    db.commit()
    record_audit(db, workspace_id, user.id, "DATASET_UPLOADED", "dataset", dataset.id)
    db.commit()
    db.refresh(dataset)

    storage = get_storage()
    temp_dir: tempfile.TemporaryDirectory | None = None
    try:
        dataset.ingestion_status = DatasetStatus.VALIDATING
        db.commit()
        storage.upload(dataset.storage_key, file.file, mime_type)

        dataset.ingestion_status = DatasetStatus.PROCESSING
        db.commit()
        temp_dir, temp_path = copy_object_to_temp(storage, dataset.storage_key, f".{format_name}")
        schema = inspect_file(temp_path, format_name)
        dataset.schema_json = schema
        dataset.row_count = int(schema["row_count"])
        dataset.column_count = int(schema["column_count"])
        dataset.ingestion_status = DatasetStatus.COMPLETED
        dataset.ingestion_error = None
        db.commit()
        try:
            ensure_bronze_version(db, storage, dataset, user.id)
            ensure_dataset_asset(db, workspace_id, dataset)
        except Exception:
            logging.getLogger("pylake.lakehouse").exception("Failed to create Bronze lakehouse version")
        db.refresh(dataset)
    except Exception as error:
        logger_message = f"Dataset {dataset.id} ingestion failed"
        import logging
        logging.getLogger("pylake.ingestion").exception(logger_message)
        dataset.ingestion_status = DatasetStatus.FAILED
        dataset.ingestion_error = str(error)[:1000] or "Ingestion failed"
        db.commit()
        if storage.exists(dataset.storage_key):
            storage.delete(dataset.storage_key)
        record_audit(db, workspace_id, user.id, "DATASET_DELETED", "dataset", dataset.id)
    finally:
        if temp_dir:
            temp_dir.cleanup()
    return dataset


@router.get("/{workspace_id}/datasets", response_model=DatasetListResponse)
def list_datasets(
    workspace_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    search: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatasetListResponse:
    membership(db, workspace_id, user.id)
    query = db.query(Dataset).filter(Dataset.workspace_id == workspace_id)
    if search:
        query = query.filter(Dataset.name.ilike(f"%{search}%"))
    total = query.count()
    items = query.order_by(Dataset.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return DatasetListResponse(items=[DatasetResponse.model_validate(item) for item in items], total=total, page=page, page_size=page_size)


@router.get("/{workspace_id}/datasets/{dataset_id}", response_model=DatasetResponse)
def get_dataset_metadata(
    workspace_id: UUID,
    dataset_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dataset:
    membership(db, workspace_id, user.id)
    return get_dataset(db, workspace_id, dataset_id)


@router.get("/{workspace_id}/datasets/{dataset_id}/status", response_model=DatasetResponse)
def get_dataset_status(
    workspace_id: UUID,
    dataset_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dataset:
    membership(db, workspace_id, user.id)
    return get_dataset(db, workspace_id, dataset_id)


@router.get("/{workspace_id}/datasets/{dataset_id}/schema")
def get_dataset_schema(
    workspace_id: UUID,
    dataset_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    membership(db, workspace_id, user.id)
    dataset = get_dataset(db, workspace_id, dataset_id)
    return dataset.schema_json or {"format": dataset.file_format, "columns": [], "row_count": dataset.row_count, "column_count": dataset.column_count}


@router.get("/{workspace_id}/datasets/{dataset_id}/preview", response_model=PreviewResponse)
def preview_dataset(
    workspace_id: UUID,
    dataset_id: UUID,
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    membership(db, workspace_id, user.id)
    dataset = get_dataset(db, workspace_id, dataset_id)
    if dataset.ingestion_status != DatasetStatus.COMPLETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Dataset is not ready for preview")
    storage = get_storage()
    temp_dir, temp_path = copy_object_to_temp(storage, dataset.storage_key, f".{dataset.file_format}")
    try:
        preview = preview_file(temp_path, dataset.file_format, limit)
        preview["row_count"] = dataset.row_count or preview["row_count"]
        return preview
    finally:
        temp_dir.cleanup()


@router.get("/{workspace_id}/datasets/{dataset_id}/download")
def download_dataset(
    workspace_id: UUID,
    dataset_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    membership(db, workspace_id, user.id)
    dataset = get_dataset(db, workspace_id, dataset_id)
    storage = get_storage()
    try:
        source = storage.download(dataset.storage_key)
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored dataset not found") from error

    def stream():
        try:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            source.close()

    return StreamingResponse(
        stream(),
        media_type=dataset.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{dataset.original_filename}"'},
    )


@router.delete("/{workspace_id}/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(
    workspace_id: UUID,
    dataset_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    dataset = get_dataset(db, workspace_id, dataset_id)
    storage = get_storage()
    if storage.exists(dataset.storage_key):
        storage.delete(dataset.storage_key)
    db.delete(dataset)
    db.commit()
