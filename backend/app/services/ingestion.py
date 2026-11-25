import csv
import logging
import re
import tempfile
from pathlib import Path
from typing import Any, BinaryIO

import polars as pl
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

logger = logging.getLogger("pylake.ingestion")

SUPPORTED = {
    ".csv": ("csv", "text/csv"),
    ".json": ("json", "application/json"),
    ".parquet": ("parquet", "application/vnd.apache.parquet"),
    ".xlsx": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
}


def sanitize_filename(filename: str) -> str:
    filename = filename.strip().replace("\x00", "")
    filename = re.sub(r"[^\w.\- ()]", "_", Path(filename).name)
    filename = filename[:255].strip(" .")
    return filename or "dataset"


def detect_format(filename: str, mime_type: str, signature: bytes) -> tuple[str, str]:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError("Unsupported file format")

    format_name, detected_mime = SUPPORTED[suffix]
    if format_name == "parquet" and not signature.startswith(b"PAR1"):
        raise ValueError("Invalid Parquet file")
    if format_name == "parquet" and len(signature) >= 8 and not signature.endswith(b"PAR1"):
        raise ValueError("Invalid Parquet file")
    if format_name == "xlsx" and not (signature.startswith(b"PK\x03\x04") or signature.startswith(b"PK\x05\x06")):
        raise ValueError("Invalid XLSX file")
    if format_name == "json":
        text = signature.decode("utf-8", errors="ignore").lstrip()
        if not text:
            raise ValueError("Empty JSON file")
    if format_name == "csv":
        if not signature:
            raise ValueError("Empty CSV file")
    return format_name, detected_mime


def detect_delimiter(header: bytes) -> str:
    text = header.decode("utf-8-sig", errors="replace")
    try:
        return csv.Sniffer().sniff(text, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def schema_for_frame(frame: pl.DataFrame) -> dict[str, Any]:
    columns = [
        {
            "name": name,
            "type": str(dtype),
            "nullable": bool(frame[name].null_count() > 0),
        }
        for name, dtype in frame.schema.items()
    ]
    return {
        "format": "parquet" if not hasattr(frame, "_df") else "dataframe",
        "columns": columns,
        "row_count": frame.height,
        "column_count": frame.width,
    }


def inspect_csv(path: Path) -> dict[str, Any]:
    with path.open("rb") as source:
        header = source.read(8192)
    if not header.strip():
        raise ValueError("Empty CSV file")
    delimiter = detect_delimiter(header)
    try:
        frame = pl.read_csv(path, separator=delimiter, infer_schema_length=100)
    except Exception as error:
        raise ValueError("Malformed CSV file") from error
    if frame.width == 0:
        raise ValueError("CSV file has no columns")
    schema = schema_for_frame(frame)
    schema["format"] = "csv"
    schema["delimiter"] = delimiter
    return schema


def inspect_json(path: Path) -> dict[str, Any]:
    if not path.read_bytes()[:1].strip():
        raise ValueError("Empty JSON file")
    try:
        try:
            frame = pl.read_json(path)
        except Exception:
            frame = pl.read_ndjson(path)
    except Exception as error:
        raise ValueError("Malformed JSON file") from error
    if frame.width == 0:
        raise ValueError("JSON file has no columns")
    schema = schema_for_frame(frame)
    schema["format"] = "json"
    return schema


def inspect_parquet(path: Path) -> dict[str, Any]:
    try:
        frame = pl.read_parquet(path)
    except Exception as error:
        raise ValueError("Malformed Parquet file") from error
    if frame.width == 0:
        raise ValueError("Parquet file has no columns")
    schema = schema_for_frame(frame)
    schema["format"] = "parquet"
    return schema


def inspect_xlsx(path: Path) -> dict[str, Any]:
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except (InvalidFileException, OSError, ValueError) as error:
        raise ValueError("Malformed XLSX file") from error

    sheets = []
    first_columns = []
    row_count = 0
    try:
        for sheet in workbook.worksheets:
            rows = sheet.iter_rows(values_only=True)
            try:
                headers = [str(value) if value is not None else f"column_{index + 1}" for index, value in enumerate(next(rows))]
            except StopIteration:
                headers = []
            values = list(rows)
            sheets.append({
                "name": sheet.title,
                "row_count": len(values) + (1 if headers else 0),
                "column_count": len(headers),
            })
            if not first_columns and headers:
                first_columns = headers
                row_count = len(values)
    finally:
        workbook.close()

    if not first_columns:
        raise ValueError("XLSX file has no readable worksheet columns")
    columns = [{"name": name, "type": "unknown", "nullable": True} for name in first_columns]
    return {
        "format": "xlsx",
        "columns": columns,
        "row_count": row_count,
        "column_count": len(first_columns),
        "sheets": sheets,
    }


def inspect_file(path: Path, format_name: str) -> dict[str, Any]:
    inspectors = {
        "csv": inspect_csv,
        "json": inspect_json,
        "parquet": inspect_parquet,
        "xlsx": inspect_xlsx,
    }
    return inspectors[format_name](path)


def preview_file(path: Path, format_name: str, limit: int = 100) -> dict[str, Any]:
    limit = max(1, min(limit, 100))
    if format_name == "xlsx":
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.worksheets[0]
            rows = sheet.iter_rows(values_only=True)
            try:
                headers = [str(value) if value is not None else f"column_{index + 1}" for index, value in enumerate(next(rows))]
            except StopIteration:
                headers = []
            preview_rows = []
            for values in list(rows)[:limit]:
                preview_rows.append({header: value for header, value in zip(headers, values)})
            columns = [{"name": name, "type": "unknown", "nullable": True} for name in headers]
            return {"columns": columns, "rows": preview_rows, "row_count": sheet.max_row, "returned_rows": len(preview_rows)}
        finally:
            workbook.close()

    frame = {
        "csv": lambda: pl.read_csv(path, separator=detect_delimiter(path.read_bytes()[:8192]), infer_schema_length=100),
        "json": lambda: pl.read_json(path) if path.read_bytes().lstrip().startswith(b"[") else pl.read_ndjson(path),
        "parquet": lambda: pl.read_parquet(path),
    }[format_name]()
    frame = frame.head(limit)
    rows = [
        {name: normalize_value(value) for name, value in row.items()}
        for row in frame.to_dicts()
    ]
    columns = [{"name": name, "type": str(dtype), "nullable": frame[name].null_count() > 0} for name, dtype in frame.schema.items()]
    return {"columns": columns, "rows": rows, "row_count": frame.height, "returned_rows": len(rows)}


def normalize_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {key: normalize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_value(item) for item in value]
    return value
