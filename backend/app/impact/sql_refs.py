"""SQLGlot-based reference extraction for stored workspace SQL."""
from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from app.engines.query_validator import SQLValidationError, validate_read_only_sql


def extract_sql_refs(sql: str) -> dict[str, Any]:
    """Return tables and column references, or a safe parse/validation error."""
    try:
        tables, _ = validate_read_only_sql(sql)
        parsed = sqlglot.parse_one(sql, dialect="duckdb")
    except (SQLValidationError, sqlglot.errors.ParseError, ValueError):
        return {"valid": False, "tables": [], "columns": [], "error": "Stored SQL could not be parsed as a read-only query"}

    aliases: dict[str, str] = {}
    for table in parsed.find_all(exp.Table):
        table_name = table.name
        aliases[(table.alias or table_name).casefold()] = table_name
    columns = []
    for column in parsed.find_all(exp.Column):
        item = {"name": column.name, "table": aliases.get((column.table or "").casefold()) if column.table else None}
        if item not in columns:
            columns.append(item)
    return {"valid": True, "tables": sorted(set(tables), key=str.casefold), "columns": columns, "error": None}


def rewrite_column(sql: str, old_name: str, new_name: str) -> str | None:
    """Draft a validated identifier rename; never return unvalidated SQL."""
    try:
        parsed = sqlglot.parse_one(sql, dialect="duckdb")
        for column in parsed.find_all(exp.Column):
            if column.name.casefold() == old_name.casefold():
                column.set("this", exp.to_identifier(new_name, quoted=True))
        rewritten = parsed.sql(dialect="duckdb")
        validate_read_only_sql(rewritten)
        return rewritten
    except Exception:
        return None


def rewrite_table(sql: str, old_name: str, new_name: str) -> str | None:
    try:
        parsed = sqlglot.parse_one(sql, dialect="duckdb")
        for table in parsed.find_all(exp.Table):
            if table.name.casefold() == old_name.casefold():
                table.set("this", exp.to_identifier(new_name, quoted=True))
        rewritten = parsed.sql(dialect="duckdb")
        validate_read_only_sql(rewritten)
        return rewritten
    except Exception:
        return None
