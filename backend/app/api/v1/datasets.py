import logging
import re
import tempfile
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.v1.workspaces import membership, require_role
from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.db import get_db
from app.models.entities import Dataset, DatasetStatus, User, WorkspaceRole
from app.schemas.datasets import DatasetListResponse, DatasetResponse, PreviewResponse
from app.services.catalog import ensure_dataset_asset
from app.services import trust as trust_service
from app.services.ingestion import detect_format, inspect_file, preview_file, sanitize_filename
from app.services.lakehouse import ensure_bronze_version
from app.storage.factory import get_storage

logger = logging.getLogger("pylake.datasets")

router = APIRouter(prefix="/workspaces", tags=["datasets"])

# ---------------------------------------------------------------------------
# Pydantic schemas for the new direct-upload endpoints
# ---------------------------------------------------------------------------

_SAFE_NAME_RE = re.compile(r"[^\w.\- ()]")
_MAX_FILENAME_BYTES = 255


class UploadUrlRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=_MAX_FILENAME_BYTES)
    size_bytes: int = Field(..., gt=0)
    content_type: str = Field(..., min_length=1, max_length=200)


class UploadUrlResponse(BaseModel):
    dataset_id: UUID
    upload_url: str
    method: str = "PUT"
    headers: dict[str, str]
    expires_in: int


class UploadConfigResponse(BaseModel):
    direct_upload: bool
    max_upload_size_bytes: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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


def _run_ingestion(
    db: Session,
    storage,
    dataset: Dataset,
    workspace_id: UUID,
    user_id: UUID,
) -> None:
    """Download from storage, inspect, and update dataset status/schema in-place.

    Called by both the multipart and direct-upload paths.  ``dataset`` is
    already persisted with a valid ``storage_key`` and
    ``ingestion_status=PENDING`` (or VALIDATING) before this is called.

    On success the dataset is left with ``COMPLETED`` status.
    On failure the dataset is left with ``FAILED`` status and the caller
    should *not* re-raise (the error is recorded on the model).
    """
    temp_dir: tempfile.TemporaryDirectory | None = None
    try:
        dataset.ingestion_status = DatasetStatus.PROCESSING
        db.commit()

        temp_dir, temp_path = copy_object_to_temp(
            storage, dataset.storage_key, f".{dataset.file_format}"
        )
        schema = inspect_file(temp_path, dataset.file_format)
        dataset.schema_json = schema
        dataset.row_count = int(schema["row_count"])
        dataset.column_count = int(schema["column_count"])
        dataset.ingestion_status = DatasetStatus.COMPLETED
        dataset.ingestion_error = None
        db.commit()

        try:
            ensure_bronze_version(db, storage, dataset, user_id)
            asset = ensure_dataset_asset(db, workspace_id, dataset)
            trust_service.compute_trust_best_effort(db, storage, workspace_id, asset, "INGESTION", user_id)
        except Exception:
            logger.exception("Failed to create Bronze lakehouse version for dataset %s", dataset.id)

        db.refresh(dataset)
    except Exception as exc:
        logger.exception("Dataset %s ingestion failed", dataset.id)
        dataset.ingestion_status = DatasetStatus.FAILED
        dataset.ingestion_error = str(exc)[:1000] or "Ingestion failed"
        db.commit()
        if storage.exists(dataset.storage_key):
            storage.delete(dataset.storage_key)
        record_audit(db, workspace_id, user_id, "DATASET_DELETED", "dataset", dataset.id)
    finally:
        if temp_dir:
            temp_dir.cleanup()


def _validate_upload_params(
    filename: str,
    size_bytes: int,
    settings,
) -> tuple[str, str]:
    """Sanitize filename and validate extension + size.

    Returns ``(format_name, suffix)`` or raises HTTPException.
    """
    safe_name = sanitize_filename(filename)
    suffix = Path(safe_name).suffix.lower()
    allowed = {".csv", ".json", ".ndjson", ".parquet", ".xlsx"}
    if suffix not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file format. Allowed: CSV, JSON, NDJSON, Parquet, XLSX.",
        )
    if size_bytes > settings.max_upload_size_bytes:
        limit_mb = settings.max_upload_size_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds the {limit_mb} MB upload limit.",
        )
    return safe_name, suffix


# ---------------------------------------------------------------------------
# Existing multipart upload — unchanged behaviour
# ---------------------------------------------------------------------------

@router.post(
    "/{workspace_id}/datasets/upload",
    response_model=DatasetResponse,
    status_code=status.HTTP_201_CREATED,
)
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file format",
        )

    try:
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to inspect upload",
        ) from error
    if size <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty files are not allowed",
        )
    if size > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Upload exceeds the configured size limit",
        )

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
        _run_ingestion(db, storage, dataset, workspace_id, user.id)
    except Exception:
        # _run_ingestion handles its own exception recording; re-raise only if
        # the error occurred before _run_ingestion (e.g. the upload itself failed).
        logger.exception("Dataset %s upload phase failed", dataset.id)
        if dataset.ingestion_status not in {DatasetStatus.FAILED}:
            dataset.ingestion_status = DatasetStatus.FAILED
            dataset.ingestion_error = "Upload failed before ingestion"
            db.commit()
    finally:
        if temp_dir:
            temp_dir.cleanup()
    return dataset


# ---------------------------------------------------------------------------
# Direct-upload endpoints (presigned PUT)
# ---------------------------------------------------------------------------

@router.get(
    "/{workspace_id}/datasets/upload-config",
    response_model=UploadConfigResponse,
)
def upload_config(
    workspace_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UploadConfigResponse:
    """Return whether direct-to-storage upload is enabled and the size limit."""
    membership(db, workspace_id, user.id)
    settings = get_settings()
    return UploadConfigResponse(
        direct_upload=settings.direct_upload_enabled,
        max_upload_size_bytes=settings.max_upload_size_bytes,
    )


@router.post(
    "/{workspace_id}/datasets/upload-url",
    response_model=UploadUrlResponse,
    status_code=status.HTTP_201_CREATED,
)
def request_upload_url(
    workspace_id: UUID,
    payload: UploadUrlRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UploadUrlResponse:
    """Create a dataset record and return a presigned PUT URL for direct upload.

    The client must PUT the file to ``upload_url`` (without credentials or the
    CSRF header — it is a cross-origin presigned URL), then call
    ``POST .../datasets/{dataset_id}/upload-complete`` to trigger ingestion.
    """
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    settings = get_settings()

    if not settings.direct_upload_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Direct upload is not enabled on this server.",
        )

    safe_name, suffix = _validate_upload_params(
        payload.filename, payload.size_bytes, settings
    )

    # Map extension to format/mime — reuse detect_format with an empty signature
    # (we can't read the file here; signature checks happen at complete time).
    _FORMAT_MAP = {
        ".csv": ("csv", "text/csv"),
        ".json": ("json", "application/json"),
        ".ndjson": ("json", "application/json"),
        ".parquet": ("parquet", "application/vnd.apache.parquet"),
        ".xlsx": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    }
    format_name, mime_type = _FORMAT_MAP[suffix]

    # Server-generated, workspace-scoped object key — never accepted from the client.
    upload_uuid = uuid4()
    storage_key = f"workspaces/{workspace_id}/bronze/uploads/{upload_uuid}/{safe_name}"

    dataset = Dataset(
        workspace_id=workspace_id,
        uploaded_by=user.id,
        name=Path(safe_name).stem.strip()[:200],
        original_filename=safe_name,
        file_format=format_name,
        mime_type=mime_type,
        file_size_bytes=payload.size_bytes,
        storage_backend=settings.storage_backend.lower(),
        storage_key=storage_key,
        ingestion_status=DatasetStatus.PENDING,
    )
    db.add(dataset)
    db.flush()
    db.commit()
    record_audit(db, workspace_id, user.id, "DATASET_UPLOAD_URL_REQUESTED", "dataset", dataset.id)
    db.commit()
    db.refresh(dataset)

    storage = get_storage()
    try:
        upload_url = storage.generate_presigned_put(
            storage_key,
            content_type=mime_type,
            expires=settings.direct_upload_url_ttl_seconds,
        )
    except NotImplementedError:
        # Roll back the pending record so it doesn't litter the DB.
        db.delete(dataset)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Direct upload is not supported by the configured storage backend.",
        )
    except Exception:
        db.delete(dataset)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage is temporarily unavailable. Please try again.",
        )

    return UploadUrlResponse(
        dataset_id=dataset.id,
        upload_url=upload_url,
        method="PUT",
        headers={"Content-Type": mime_type},
        expires_in=settings.direct_upload_url_ttl_seconds,
    )


@router.post(
    "/{workspace_id}/datasets/{dataset_id}/upload-complete",
    response_model=DatasetResponse,
)
def upload_complete(
    workspace_id: UUID,
    dataset_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dataset:
    """Verify the uploaded object and run ingestion/schema detection.

    Call this after the client has successfully PUT the file to the presigned URL.
    """
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    settings = get_settings()

    dataset = get_dataset(db, workspace_id, dataset_id)

    if dataset.ingestion_status != DatasetStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dataset is not in a pending state. It may have already been processed or failed.",
        )

    storage = get_storage()

    # HEAD the object to confirm it was actually uploaded.
    try:
        meta = storage.head(dataset.storage_key)
    except FileNotFoundError:
        dataset.ingestion_status = DatasetStatus.FAILED
        dataset.ingestion_error = "Object not found in storage after upload."
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded object was not found in storage. The upload may have failed or the URL expired.",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage is temporarily unavailable. Please try again.",
        )

    actual_size = meta["size"]
    max_bytes = settings.max_upload_size_bytes

    # Guard against oversized objects that slipped past the client-side check.
    if actual_size > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        storage.delete(dataset.storage_key)
        dataset.ingestion_status = DatasetStatus.FAILED
        dataset.ingestion_error = f"Object size {actual_size} exceeds the {limit_mb} MB limit."
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Uploaded file exceeds the {limit_mb} MB limit.",
        )

    # Reject a size that differs by more than 1 % from what was declared (guards
    # against a client PUT-ing a different file than it declared).
    declared = dataset.file_size_bytes
    tolerance = max(1024, int(declared * 0.01))
    if abs(actual_size - declared) > tolerance:
        storage.delete(dataset.storage_key)
        dataset.ingestion_status = DatasetStatus.FAILED
        dataset.ingestion_error = (
            f"Actual size {actual_size} differs from declared size {declared}."
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file size does not match the declared size.",
        )

    # Update the stored size to the verified actual size.
    dataset.file_size_bytes = actual_size
    dataset.ingestion_status = DatasetStatus.VALIDATING
    db.commit()

    record_audit(db, workspace_id, user.id, "DATASET_UPLOADED", "dataset", dataset.id)
    db.commit()

    _run_ingestion(db, storage, dataset, workspace_id, user.id)
    db.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Remaining dataset endpoints — unchanged
# ---------------------------------------------------------------------------

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
    items = (
        query.order_by(Dataset.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return DatasetListResponse(
        items=[DatasetResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


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
    return dataset.schema_json or {
        "format": dataset.file_format,
        "columns": [],
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
    }


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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dataset is not ready for preview",
        )
    storage = get_storage()
    temp_dir, temp_path = copy_object_to_temp(
        storage, dataset.storage_key, f".{dataset.file_format}"
    )
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stored dataset not found",
        ) from error

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
        headers={
            "Content-Disposition": f'attachment; filename="{dataset.original_filename}"'
        },
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
