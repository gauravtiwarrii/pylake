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
from app.models.entities import CatalogAsset, DatasetVersion, LakehouseTable, LakehouseVersionStatus


def _column_match(value: str, columns: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float, list[dict[str, Any]]]:
    target = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    exact = [
        column for column in columns
        if re.sub(r"[^a-z0-9]+", " ", str(column.get("name", "")).casefold()).strip() == target
    ]
    if len(exact) == 1:
        return exact[0], 1.0, exact
    if len(exact) > 1:
        return None, 1.0, exact[:5]
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


def _is_numeric_column(column: dict[str, Any]) -> bool:
    data_type = str(column.get("type", column.get("data_type", ""))).strip().casefold()
    return bool(re.match(r"^(?:u?int|float|double|decimal|numeric|number|real|bigint|smallint|long|short|byte)", data_type))


def _numeric_candidates(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [column for column in columns if _is_numeric_column(column)]


def _match_confidence(query: str, column: dict[str, Any]) -> str:
    return "high" if query.strip().casefold() == str(column.get("name", "")).strip().casefold() else "medium"


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


def _templates(question: str, columns: list[dict[str, Any]], table_name: str) -> tuple[str | None, list[dict[str, Any]], str | None, str]:
    q = question.casefold()
    from_clause = _quote(logical_name(table_name))
    row_count = re.search(r"\bhow many rows\b", q)
    if row_count:
        return f"SELECT COUNT(*) AS row_count FROM {from_clause}", [], "Count all rows in the selected table.", "high"

    common = re.search(r"\bmost\s+common\s+(.+?)(?:\?|$)", q)
    if common:
        dimension, _, candidates = _column_match(common.group(1), columns)
        if not dimension:
            return None, candidates, "I could not map the requested category to one unambiguous column.", "low"
        n_match = re.search(r"\btop\s+(\d+)\b", q)
        n = min(200, max(1, int(n_match.group(1)))) if n_match else 10
        name = _quote(str(dimension["name"]))
        sql = f"SELECT {name} AS {name}, COUNT(*) AS count FROM {from_clause} GROUP BY {name} ORDER BY count DESC LIMIT {n}"
        confidence = _match_confidence(common.group(1), dimension)
        return sql, [dimension], f"Top {n} most common {dimension['name']} values by count.", confidence

    rank = re.search(r"\b(top|highest|largest|bottom|lowest|smallest)\s+(?:(\d+)\s+)?(.+?)\s+(?:by|per)\s+(.+?)(?:\?|$)", q)
    if rank:
        operation, count_text, first_text, second_text = rank.groups()
        first, _, first_candidates = _column_match(first_text, columns)
        second, _, second_candidates = _column_match(second_text, columns)
        if not first or not second:
            return None, first_candidates + second_candidates, "I could not map the requested metric and grouping to one unambiguous column each.", "low"

        explicit_n = count_text is not None
        if explicit_n:
            dimension, metric = first, second
            dimension_text, metric_text = first_text, second_text
        elif _is_numeric_column(first) and not _is_numeric_column(second):
            metric, dimension = first, second
            metric_text, dimension_text = first_text, second_text
        elif _is_numeric_column(second) and not _is_numeric_column(first):
            dimension, metric = first, second
            dimension_text, metric_text = first_text, second_text
        elif operation in {"top", "bottom"}:
            dimension, metric = first, second
            dimension_text, metric_text = first_text, second_text
        else:
            metric, dimension = first, second
            metric_text, dimension_text = first_text, second_text

        if not _is_numeric_column(metric):
            numeric = _numeric_candidates(columns)
            suggestion = ", ".join(str(column["name"]) for column in numeric[:5])
            summary = f"{metric['name']} is not a numeric metric. Choose a numeric column{': ' + suggestion if suggestion else ''}."
            return None, numeric, summary, "low"

        n = min(200, max(1, int(count_text or 10)))
        direction = "ASC" if operation in {"bottom", "lowest", "smallest"} else "DESC"
        dimension_name = _quote(str(dimension["name"]))
        metric_name = _quote(str(metric["name"]))
        # Preserve the established metric alias for natural "highest metric by
        # dimension" questions; explicit numbered top-N asks use total_<metric>.
        metric_alias = str(metric["name"]) if not explicit_n and metric is first else f"total_{metric['name']}"
        total_name = _quote(metric_alias)
        sql = (f"SELECT {dimension_name} AS {dimension_name}, "
               f"SUM(TRY_CAST({metric_name} AS DOUBLE)) AS {total_name} FROM {from_clause} "
               f"GROUP BY {dimension_name} ORDER BY {total_name} {direction} LIMIT {n}")
        confidence = "high" if (
            _match_confidence(dimension_text, dimension) == "high"
            and _match_confidence(metric_text, metric) == "high"
        ) else "medium"
        title = "Lowest" if direction == "ASC" else "Top"
        summary = f"{title} {n} {dimension['name']} by total {metric['name']}."
        return sql, [metric, dimension], summary, confidence

    aggregate = re.search(r"\b(total|sum|average|avg|mean|count)\s+(?:of\s+)?(.+?)(?:\s+(?:by|per)\s+(.+?))?(?:\?|$)", q)
    if aggregate:
        method, metric_text, dimension_text = aggregate.groups()
        metric, _, candidates = _column_match(metric_text, columns)
        if not metric:
            return None, candidates, "I could not confidently map the requested measure to one column.", "low"
        if method != "count" and not _is_numeric_column(metric):
            numeric = _numeric_candidates(columns)
            return None, numeric, f"{metric['name']} is not a numeric metric. Choose a numeric column.", "low"
        expression = f"COUNT({_quote(metric['name'])})" if method == "count" else f"{'AVG' if method in {'average', 'avg', 'mean'} else 'SUM'}(TRY_CAST({_quote(metric['name'])} AS DOUBLE))"
        confidence = _match_confidence(metric_text, metric)
        if dimension_text:
            dimension, _, other = _column_match(dimension_text, columns)
            if not dimension:
                return None, candidates + other, "I could not confidently map the requested grouping to one column.", "low"
            sql = f"SELECT {_quote(dimension['name'])}, {expression} AS value FROM {from_clause} GROUP BY 1 ORDER BY 2 DESC"
            confidence = "high" if confidence == "high" and _match_confidence(dimension_text, dimension) == "high" else "medium"
            return sql, [metric, dimension], f"Computed {method} of {metric['name']} grouped by {dimension['name']}.", confidence
        return f"SELECT {expression} AS value FROM {from_clause}", [metric], f"Computed {method} of {metric['name']}.", confidence
    trend = re.search(r"\btrend\s+(?:of\s+)?(.+?)\s+by\s+(.+?)(?:\?|$)", q)
    if trend:
        metric, _, metric_candidates = _column_match(trend.group(1), columns)
        date_col, _, date_candidates = _column_match(trend.group(2), columns)
        if not metric or not date_col:
            return None, metric_candidates + date_candidates, "I could not confidently map the trend measure and date column.", "low"
        if not _is_numeric_column(metric):
            return None, _numeric_candidates(columns), f"{metric['name']} is not a numeric metric. Choose a numeric column.", "low"
        sql = f"SELECT {_quote(date_col['name'])}, SUM(TRY_CAST({_quote(metric['name'])} AS DOUBLE)) AS {_quote(metric['name'])} FROM {from_clause} GROUP BY 1 ORDER BY 1"
        confidence = "high" if (
            _match_confidence(trend.group(1), metric) == "high"
            and _match_confidence(trend.group(2), date_col) == "high"
        ) else "medium"
        return sql, [metric, date_col], f"Computed a sum of {metric['name']} by {date_col['name']}.", confidence
    return None, columns[:10], None, "low"


def build_template_sql(question: str, columns: list[dict[str, Any]], table_name: str) -> tuple[str | None, list[dict[str, Any]], str | None, str]:
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
