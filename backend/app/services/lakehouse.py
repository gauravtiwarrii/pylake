import hashlib
import logging
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

import polars as pl

from app.core.config import get_settings
from app.models.entities import (
    Dataset,
    DatasetVersion,
    LakehouseLayer,
    LakehouseTable,
    LakehouseVersionStatus,
    StorageObject,
)
from app.storage.base import StorageInterface

logger = logging.getLogger("pylake.lakehouse")


def checksum_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_frame(frame: pl.DataFrame) -> pl.DataFrame:
    for column in frame.columns:
        if frame[column].dtype == pl.Datetime:
            frame = frame.with_columns(pl.col(column).cast(pl.Datetime("us")))
    return frame


def read_source(path: Path, file_format: str) -> pl.DataFrame:
    if file_format == "csv":
        return pl.read_csv(path, infer_schema_length=100)
    if file_format == "json":
        try:
            return pl.read_json(path)
        except Exception:
            return pl.read_ndjson(path)
    if file_format == "parquet":
        return pl.read_parquet(path)
    if file_format == "xlsx":
        import openpyxl

        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.worksheets[0]
            rows = list(sheet.iter_rows(values_only=True))
        finally:
            workbook.close()
        if not rows:
            return pl.DataFrame()
        headers = [str(value) if value is not None else f"column_{index + 1}" for index, value in enumerate(rows[0])]
        return pl.DataFrame([dict(zip(headers, row)) for row in rows[1:]], strict=False)
    raise ValueError(f"Unsupported source format: {file_format}")


def frame_schema(frame: pl.DataFrame) -> dict[str, Any]:
    return {
        "format": "parquet",
        "columns": [
            {"name": name, "type": str(dtype), "nullable": bool(frame[name].null_count() > 0)}
            for name, dtype in frame.schema.items()
        ],
        "row_count": frame.height,
        "column_count": frame.width,
    }


def copy_source_to_temp(storage: StorageInterface, key: str, suffix: str = "") -> tuple[tempfile.TemporaryDirectory, Path]:
    directory = tempfile.TemporaryDirectory(prefix="pylake-lakehouse-")
    path = Path(directory.name) / f"source{suffix}"
    with storage.download(key) as source:
        with path.open("wb") as target:
            while chunk := source.read(1024 * 1024):
                target.write(chunk)
    return directory, path


def write_parquet(frame: pl.DataFrame, path: Path) -> None:
    settings = get_settings()
    frame.write_parquet(path, compression=settings.parquet_compression)


def ensure_bronze_version(
    db,
    storage: StorageInterface,
    dataset: Dataset,
    user_id: UUID,
) -> DatasetVersion:
    table = db.query(LakehouseTable).filter(
        LakehouseTable.workspace_id == dataset.workspace_id,
        LakehouseTable.name == dataset.name,
    ).first()
    if not table:
        table = LakehouseTable(
            workspace_id=dataset.workspace_id,
            name=dataset.name[:200],
            description=dataset.description,
            current_layer=LakehouseLayer.BRONZE,
        )
        db.add(table)
        db.flush()

    existing = db.query(DatasetVersion).filter(
        DatasetVersion.dataset_id == dataset.id,
        DatasetVersion.layer == LakehouseLayer.BRONZE,
    ).first()
    if existing:
        return existing

    key = f"workspaces/{dataset.workspace_id}/bronze/{dataset.id}/versions/1/data/{dataset.original_filename}"
    if not storage.exists(key):
        with storage.download(dataset.storage_key) as source:
            storage.upload(key, source, dataset.mime_type)
    size = storage.get_metadata(key)["size"]
    # Metadata is already in Dataset.schema_json for the ingested source.
    version = DatasetVersion(
        dataset_id=dataset.id,
        lakehouse_table_id=table.id,
        version_number=1,
        layer=LakehouseLayer.BRONZE,
        storage_key=key,
        schema_json=dataset.schema_json,
        row_count=dataset.row_count,
        column_count=dataset.column_count,
        file_size_bytes=size,
        file_format=dataset.file_format,
        created_by=user_id,
        status=LakehouseVersionStatus.COMPLETED,
    )
    db.add(version)
    db.flush()
    db.add(StorageObject(
        workspace_id=dataset.workspace_id,
        dataset_id=dataset.id,
        version_id=version.id,
        layer=LakehouseLayer.BRONZE,
        storage_key=key,
        file_size_bytes=size,
    ))
    db.commit()
    return version


def quality_summary(frame: pl.DataFrame) -> dict[str, Any]:
    duplicate_count = max(frame.height - frame.unique().height, 0)
    null_counts = {name: int(frame[name].null_count()) for name in frame.columns}
    empty_columns = [name for name, count in null_counts.items() if frame.height > 0 and count == frame.height]
    return {
        "row_count": frame.height,
        "column_count": frame.width,
        "duplicate_rows": duplicate_count,
        "null_counts": null_counts,
        "empty_columns": empty_columns,
        "type_consistency": "consistent",
    }
