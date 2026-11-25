from uuid import UUID

from sqlalchemy.orm import Session

from app.models.entities import DatasetVersion, LakehouseLayer, LakehouseTable, LakehouseVersionStatus


def logical_name(table_name: str) -> str:
    return table_name.lower().replace("-", "_").replace(" ", "_")


def resolve_catalog(
    db: Session,
    workspace_id: UUID,
    table_names: list[str],
) -> dict[str, DatasetVersion]:
    workspace_tables = db.query(LakehouseTable).filter(
        LakehouseTable.workspace_id == workspace_id,
    ).all()
    by_name = {
        logical_name(table.name): table
        for table in workspace_tables
    }
    resolved: dict[str, DatasetVersion] = {}

    for reference in table_names:
        normalized = logical_name(reference)
        table = by_name.get(normalized)
        if not table:
            raise KeyError(f"Table '{reference}' is not available in this workspace")

        version = db.query(DatasetVersion).filter(
            DatasetVersion.lakehouse_table_id == table.id,
            DatasetVersion.status == LakehouseVersionStatus.COMPLETED,
            DatasetVersion.file_format == "parquet",
        ).order_by(DatasetVersion.version_number.desc()).first()
        if not version:
            raise KeyError(f"Table '{reference}' has no queryable Parquet version")
        resolved[normalized] = version
    return resolved
