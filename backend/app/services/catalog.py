import tempfile
from pathlib import Path
from uuid import UUID

import polars as pl

from app.models.entities import (
    CatalogAsset,
    CatalogColumn,
    CatalogProfile,
    CatalogSchemaHistory,
    Dataset,
    DatasetVersion,
    LakehouseTable,
    LakehouseVersionStatus,
)
from app.services.lakehouse import copy_source_to_temp, read_source
from app.storage.base import StorageInterface


def ensure_dataset_asset(db, workspace_id: UUID, dataset: Dataset) -> CatalogAsset:
    asset = db.query(CatalogAsset).filter(
        CatalogAsset.workspace_id == workspace_id,
        CatalogAsset.asset_type == "DATASET",
        CatalogAsset.dataset_id == dataset.id,
    ).first()
    if not asset:
        asset = CatalogAsset(
            workspace_id=workspace_id,
            asset_type="DATASET",
            name=dataset.name,
            description=dataset.description,
            owner_id=dataset.uploaded_by,
            tags_json=[],
            dataset_id=dataset.id,
            format=dataset.file_format,
            layer="BRONZE",
        )
        db.add(asset)
        db.flush()
    else:
        asset.name = dataset.name
        asset.description = dataset.description
        asset.format = dataset.file_format
        asset.layer = "BRONZE"
    sync_columns(db, asset, dataset.schema_json)
    db.commit()
    return asset


def ensure_table_asset(db, workspace_id: UUID, table: LakehouseTable) -> CatalogAsset:
    asset = db.query(CatalogAsset).filter(
        CatalogAsset.workspace_id == workspace_id,
        CatalogAsset.asset_type == "TABLE",
        CatalogAsset.lakehouse_table_id == table.id,
    ).first()
    if not asset:
        asset = CatalogAsset(
            workspace_id=workspace_id,
            asset_type="TABLE",
            name=table.name,
            description=table.description,
            tags_json=[],
            lakehouse_table_id=table.id,
            format="parquet",
            layer=table.current_layer.value,
        )
        db.add(asset)
        db.flush()
    else:
        asset.name = table.name
        asset.description = table.description
        asset.format = "parquet"
        asset.layer = table.current_layer.value

    version = db.query(DatasetVersion).filter(
        DatasetVersion.lakehouse_table_id == table.id,
        DatasetVersion.status == LakehouseVersionStatus.COMPLETED,
    ).order_by(DatasetVersion.version_number.desc()).first()
    if version:
        sync_columns(db, asset, version.schema_json)
        history = db.query(CatalogSchemaHistory).filter(
            CatalogSchemaHistory.asset_id == asset.id,
            CatalogSchemaHistory.version_id == version.id,
        ).first()
        if not history:
            db.add(CatalogSchemaHistory(
                asset_id=asset.id,
                version_id=version.id,
                schema_json=version.schema_json or {},
            ))
    db.commit()
    return asset


def sync_columns(db, asset: CatalogAsset, schema_json: dict | None) -> None:
    if not schema_json:
        return
    for column in schema_json.get("columns", []):
        name = str(column.get("name", "")).strip()
        if not name:
            continue
        item = db.query(CatalogColumn).filter(
            CatalogColumn.asset_id == asset.id,
            CatalogColumn.name == name,
        ).first()
        if not item:
            db.add(CatalogColumn(
                asset_id=asset.id,
                name=name,
                data_type=column.get("type"),
            ))
        else:
            item.data_type = column.get("type")


def profile_asset(db, storage: StorageInterface, asset: CatalogAsset) -> dict:
    frame: pl.DataFrame | None = None
    version: DatasetVersion | None = None
    temp_dir: tempfile.TemporaryDirectory | None = None
    try:
        if asset.asset_type == "TABLE" and asset.lakehouse_table_id:
            version = db.query(DatasetVersion).filter(
                DatasetVersion.lakehouse_table_id == asset.lakehouse_table_id,
                DatasetVersion.status == LakehouseVersionStatus.COMPLETED,
            ).order_by(DatasetVersion.version_number.desc()).first()
            if version:
                temp_dir, path = copy_source_to_temp(storage, version.storage_key, ".parquet")
                frame = pl.read_parquet(path).head(10000)
        elif asset.asset_type == "DATASET" and asset.dataset_id:
            dataset = db.query(Dataset).filter(Dataset.id == asset.dataset_id).first()
            if dataset:
                temp_dir, path = copy_source_to_temp(storage, dataset.storage_key, f".{dataset.file_format}")
                frame = read_source(path, dataset.file_format).head(10000)
        if frame is None:
            return {
                "row_count": None,
                "column_count": None,
                "statistics": {},
                "uncomputed": ["asset source is unavailable"],
            }

        statistics = {}
        for name in frame.columns:
            values = frame[name]
            dtype = str(values.dtype)
            item = {
                "data_type": dtype,
                "null_count": int(values.null_count()),
                "null_percentage": round(values.null_count() * 100 / frame.height, 4) if frame.height else 0,
                "distinct_count": int(values.n_unique()),
            }
            if dtype.startswith("Int") or dtype.startswith("Float") or dtype.startswith("Decimal"):
                item["minimum"] = values.min()
                item["maximum"] = values.max()
                item["mean"] = values.mean()
            statistics[name] = item
        result = {
            "row_count": version.row_count if version else (dataset.row_count if "dataset" in locals() and dataset else frame.height),
            "column_count": version.column_count if version else (dataset.column_count if "dataset" in locals() and dataset else frame.width),
            "statistics": statistics,
            "sample_rows": frame.height,
            "uncomputed": [],
        }

        profile = db.query(CatalogProfile).filter(CatalogProfile.asset_id == asset.id).first()
        if not profile:
            profile = CatalogProfile(asset_id=asset.id)
            db.add(profile)
        profile.version_id = version.id if version else None
        profile.row_count = frame.height
        profile.column_count = frame.width
        profile.statistics_json = result
        db.commit()
        return result
    finally:
        if temp_dir:
            temp_dir.cleanup()
