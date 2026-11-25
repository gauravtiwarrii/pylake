import logging
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb

from app.core.config import get_settings
from app.storage.base import StorageInterface

logger = logging.getLogger("pylake.sql")


class DuckDBExecutionError(RuntimeError):
    pass


def copy_parquet(storage: StorageInterface, key: str) -> tuple[tempfile.TemporaryDirectory, Path]:
    directory = tempfile.TemporaryDirectory(prefix="pylake-sql-")
    path = Path(directory.name) / "data.parquet"
    with storage.download(key) as source:
        with path.open("wb") as target:
            while chunk := source.read(1024 * 1024):
                target.write(chunk)
    return directory, path


@contextmanager
def isolated_connection():
    connection = duckdb.connect(database=":memory:")
    try:
        settings = get_settings()
        connection.execute("SET enable_http_metadata_cache=false")
        connection.execute("SET enable_object_cache=false")
        connection.execute("SET max_memory='512MB'")
        connection.execute("SET preserve_insertion_order=false")
        connection.execute(f"SET threads={1}")
        yield connection
    finally:
        connection.close()


def execute_sql(
    sql: str,
    registered_tables: dict[str, tuple[Path, str]],
) -> dict[str, Any]:
    settings = get_settings()
    directories: list[tempfile.TemporaryDirectory] = []
    try:
        with isolated_connection() as connection:
            for logical_name, (path, _) in registered_tables.items():
                escaped_name = logical_name.replace('"', '""')
                escaped_path = str(path).replace("'", "''")
                connection.execute(
                    f'CREATE TEMPORARY VIEW "{escaped_name}" AS SELECT * FROM read_parquet(?)',
                    [escaped_path],
                )
            settings = get_settings()
            timer = threading.Timer(
                settings.sql_query_timeout_seconds,
                connection.interrupt,
            )
            timer.start()
            try:
                result = connection.execute(sql)
            finally:
                timer.cancel()
            arrow = result.fetch_arrow_table()
            names = [field.name for field in arrow.schema]
            types = [str(field.type) for field in arrow.schema]
            rows = arrow.slice(0, settings.sql_max_returned_rows).to_pylist()

            serialized_rows: list[dict[str, Any]] = []
            estimated_size = 0
            truncated = len(rows) < arrow.num_rows
            for row in rows:
                serialized_row = {
                    key: serialize_value(value)
                    for key, value in row.items()
                }
                estimated_size += len(str(serialized_row).encode("utf-8"))
                if estimated_size > settings.sql_max_result_bytes:
                    truncated = True
                    break
                serialized_rows.append(serialized_row)

            return {
                "columns": [{"name": name, "type": column_type} for name, column_type in zip(names, types)],
                "rows": serialized_rows,
                "returned_rows": len(serialized_rows),
                "total_rows_available": arrow.num_rows,
                "truncated": truncated or len(serialized_rows) < arrow.num_rows,
            }
    except duckdb.Error as error:
        raise DuckDBExecutionError(str(error)) from error
    finally:
        for directory in directories:
            directory.cleanup()


def serialize_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if hasattr(value, "as_py"):
        return value.as_py()
    if isinstance(value, dict):
        return {key: serialize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_value(item) for item in value]
    return value.item() if hasattr(value, "item") else value
