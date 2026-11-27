from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Any
from uuid import UUID

import sqlglot
from sqlglot import exp
from sqlalchemy.orm import Session

from app.engines.catalog_resolver import logical_name, resolve_catalog
from app.engines.query_validator import SQLValidationError, validate_read_only_sql
from app.models.entities import CatalogAsset, CatalogColumn, DatasetVersion, LakehouseTable, LakehouseVersionStatus


def _column_match(value: str, columns: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float, list[dict[str, Any]]]:
    target = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    ranked = []
    for column in columns:
        name = str(column.get("name", ""))
        normalized = re.sub(r"[_-]+", " ", name.casefold())
        ratio = SequenceMatcher(None, target, normalized).ratio()
        if target == normalized or target == name.casefold():
            ratio = 1.0
        ranked.append((ratio, column))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    top = ranked[0] if ranked else (0, None)
    tied = [col for score, col in ranked if top[0] - score < .08]
    return top[1] if top[0] >= .55 and len(tied) == 1 else None, top[0], [col for _, col in ranked[:5]]


def _pick_asset(db: Session, workspace_id: UUID, question: str, dataset_id: UUID | None, table_id: UUID | None) -> tuple[CatalogAsset | None, LakehouseTable | None, DatasetVersion | None]:
    query = db.query(CatalogAsset).filter(CatalogAsset.workspace_id == workspace_id, CatalogAsset.asset_type == "TABLE")
    if table_id:
        query = query.filter(CatalogAsset.lakehouse_table_id == table_id)
    assets = query.all()
    if not assets and dataset_id:
        return None, None, None
    if dataset_id:
        source = db.query(CatalogAsset).filter(CatalogAsset.workspace_id == workspace_id, CatalogAsset.dataset_id == dataset_id).first()
        linked = db.query(LakehouseTable).join(DatasetVersion, DatasetVersion.lakehouse_table_id == LakehouseTable.id).filter(
            LakehouseTable.workspace_id == workspace_id, DatasetVersion.dataset_id == dataset_id,
            DatasetVersion.status == LakehouseVersionStatus.COMPLETED,
        ).order_by(DatasetVersion.version_number.desc()).first()
        if linked:
            asset = db.query(CatalogAsset).filter(CatalogAsset.workspace_id == workspace_id, CatalogAsset.lakehouse_table_id == linked.id).first()
            assets = [asset] if asset else []
        elif source:
            return None, None, None
    lowered = question.casefold()
    matches = [asset for asset in assets if asset and asset.name.casefold() in lowered]
    asset = max(matches, key=lambda item: len(item.name), default=None)
    if asset is None and len(assets) == 1:
        asset = assets[0]
    if asset is None:
        return None, None, None
    table = db.query(LakehouseTable).filter(LakehouseTable.id == asset.lakehouse_table_id, LakehouseTable.workspace_id == workspace_id).first()
    if not table:
        return asset, None, None
    version = db.query(DatasetVersion).filter(DatasetVersion.lakehouse_table_id == table.id,
        DatasetVersion.status == LakehouseVersionStatus.COMPLETED,
        DatasetVersion.file_format == "parquet").order_by(DatasetVersion.version_number.desc()).first()
    return asset, table, version


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _templates(question: str, columns: list[dict[str, Any]], table_name: str) -> tuple[str | None, list[dict[str, Any]], str | None]:
    q = question.casefold()
    from_clause = _quote(logical_name(table_name))
    row_count = re.search(r"\bhow many rows\b", q)
    if row_count:
        return f"SELECT COUNT(*) AS row_count FROM {from_clause}", [], "Count all rows in the selected table."
    top = re.search(r"\b(top|highest|lowest|most|least)\s*(\d+)?\s+(.+?)\s+(?:by|per)\s+(.+?)(?:\?|$)", q)
    if top:
        metric, _, metric_candidates = _column_match(top.group(3), columns)
        dimension, _, dimension_candidates = _column_match(top.group(4), columns)
        if not metric or not dimension:
            return None, metric_candidates + dimension_candidates, "I could not map the requested metric and grouping to one unambiguous column each."
        n = min(200, max(1, int(top.group(2) or 10)))
        direction = "ASC" if top.group(1) in {"lowest", "least"} else "DESC"
        sql = f"SELECT {_quote(dimension['name'])} AS {_quote(dimension['name'])}, SUM(TRY_CAST({_quote(metric['name'])} AS DOUBLE)) AS {_quote(metric['name'])} FROM {from_clause} GROUP BY 1 ORDER BY 2 {direction} LIMIT {n}"
        return sql, [metric, dimension], f"Ranked groups by the sum of {metric['name']}."
    aggregate = re.search(r"\b(total|sum|average|avg|mean|count)\s+(?:of\s+)?(.+?)(?:\s+(?:by|per)\s+(.+?))?(?:\?|$)", q)
    if aggregate:
        method, metric_text, dimension_text = aggregate.groups()
        metric, _, candidates = _column_match(metric_text, columns)
        if not metric:
            return None, candidates, "I could not confidently map the requested measure to one column."
        op = "COUNT" if method == "count" else "AVG" if method in {"average", "avg", "mean"} else "SUM"
        expression = f"{op}(TRY_CAST({_quote(metric['name'])} AS DOUBLE))"
        if dimension_text:
            dimension, _, other = _column_match(dimension_text, columns)
            if not dimension:
                return None, candidates + other, "I could not confidently map the requested grouping to one column."
            sql = f"SELECT {_quote(dimension['name'])}, {expression} AS value FROM {from_clause} GROUP BY 1 ORDER BY 2 DESC"
            return sql, [metric, dimension], f"Computed {method} of {metric['name']} grouped by {dimension['name']}."
        return f"SELECT {expression} AS value FROM {from_clause}", [metric], f"Computed {method} of {metric['name']}."
    trend = re.search(r"\btrend\s+(?:of\s+)?(.+?)\s+by\s+(.+?)(?:\?|$)", q)
    if trend:
        metric, _, metric_candidates = _column_match(trend.group(1), columns)
        date_col, _, date_candidates = _column_match(trend.group(2), columns)
        if not metric or not date_col:
            return None, metric_candidates + date_candidates, "I could not confidently map the trend measure and date column."
        sql = f"SELECT {_quote(date_col['name'])}, SUM(TRY_CAST({_quote(metric['name'])} AS DOUBLE)) AS {_quote(metric['name'])} FROM {from_clause} GROUP BY 1 ORDER BY 1"
        return sql, [metric, date_col], f"Computed a sum of {metric['name']} by {date_col['name']}."
    return None, columns[:10], None


def build_template_sql(question: str, columns: list[dict[str, Any]], table_name: str) -> tuple[str | None, list[dict[str, Any]], str | None]:
    return _templates(question, columns, table_name)


def validate_and_limit_sql(sql: str, workspace_id: UUID, db: Session, max_rows: int) -> tuple[str, dict[str, DatasetVersion], list[str], str | None]:
    tables, columns = validate_read_only_sql(sql)
    resolved = resolve_catalog(db, workspace_id, tables)
    try:
        parsed = sqlglot.parse_one(sql, dialect="duckdb")
        original_limit = parsed.args.get("limit")
        clamped = original_limit is None
        if original_limit is not None:
            try:
                clamped = int(original_limit.expression.this) > max_rows
            except (TypeError, ValueError):
                clamped = True
        count_sql = None
        if clamped:
            unbounded = parsed.copy()
            unbounded.set("limit", None)
            count_sql = f"SELECT COUNT(*) AS ask_total FROM ({unbounded.sql(dialect='duckdb')}) AS ask_count"
        if clamped:
            parsed.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
        sql = parsed.sql(dialect="duckdb")
    except Exception as error:
        raise SQLValidationError("Could not safely enforce the result row limit") from error
    validate_read_only_sql(sql)
    if count_sql:
        count_tables, _ = validate_read_only_sql(count_sql)
        resolve_catalog(db, workspace_id, count_tables)
    return sql, resolved, columns, count_sql
