import tempfile
import time
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.engines.catalog_resolver import resolve_catalog
from app.engines.duckdb_engine import copy_parquet, execute_sql
from app.engines.query_validator import SQLValidationError, validate_read_only_sql
from app.storage.base import StorageInterface


def execute_workspace_query(
    db: Session,
    storage: StorageInterface,
    workspace_id: UUID,
    sql: str,
    limit: int | None,
) -> dict:
    started = time.perf_counter()
    try:
        table_names, _ = validate_read_only_sql(sql)
        resolved = resolve_catalog(db, workspace_id, table_names)
    except SQLValidationError as error:
        raise
    except KeyError as error:
        raise SQLValidationError(str(error)) from error

    directories: list[tempfile.TemporaryDirectory] = []
    registered: dict[str, tuple[Path, str]] = {}
    try:
        from app.engines.catalog_resolver import logical_name

        for logical_name_value, version in resolved.items():
            directory, path = copy_parquet(storage, version.storage_key)
            directories.append(directory)
            registered[logical_name_value] = (path, version.file_format)

        if limit:
            sql = append_limit(sql, limit)
        result = execute_sql(sql, registered)
        result["duration_ms"] = int((time.perf_counter() - started) * 1000)
        return result
    finally:
        for directory in directories:
            directory.cleanup()


def append_limit(sql: str, limit: int) -> str:
    stripped = sql.rstrip().rstrip(";")
    import sqlglot
    parsed = sqlglot.parse_one(stripped, dialect="duckdb")
    if parsed.args.get("limit") is not None:
        return stripped
    return f"{stripped}\nLIMIT {limit}"
