import json
import re
from typing import Any
from uuid import UUID

import sqlglot
from sqlglot import exp
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import (
    Dataset,
    DatasetVersion,
    LakehouseTable,
    LakehouseVersionStatus,
    Pipeline,
    PipelineRun,
    PipelineStep,
    QueryHistory,
    Workspace,
)


class WorkspaceResourceNotFound(LookupError):
    pass


def _safe_label(value: str | None, limit: int = 120) -> str | None:
    if not value:
        return value
    return "".join(character for character in value if character.isprintable())[:limit]


def redact_sql_literals(sql: str) -> str:
    try:
        expression = sqlglot.parse_one(sql, dialect="duckdb")
        for node in list(expression.walk()):
            if isinstance(node, exp.Literal):
                node.replace(exp.Literal.string("[REDACTED]"))
            if getattr(node, "comments", None):
                node.comments = []
        return expression.sql(dialect="duckdb")
    except (sqlglot.errors.ParseError, ValueError):
        without_comments = re.sub(r"/\*.*?\*/|--[^\r\n]*", " ", sql, flags=re.DOTALL)
        without_quotes = re.sub(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"", "'[REDACTED]'", without_comments)
        return re.sub(r"\b\d+(?:\.\d+)?\b", "?", without_quotes)[:10000]


def redacted_text(value: str | None, limit: int = 500) -> str | None:
    if not value:
        return value
    cleaned = re.sub(r"(?i)\b(password|secret|token|api[_-]?key)\b\s*[:=]\s*\S+", r"\1=[REDACTED]", value)
    cleaned = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [REDACTED]", cleaned)
    cleaned = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[REDACTED_EMAIL]", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?i)\b[A-Z]:\\(?:[^\s\\]+\\)*[^\s\\]*", "[REDACTED_PATH]", cleaned)
    cleaned = re.sub(r"(?<![\w:])/(?:home|Users|tmp|var|etc|opt)/[^\s,;]+", "[REDACTED_PATH]", cleaned)
    return "".join(character for character in cleaned if character.isprintable())[:limit]


def _schema(schema_json: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(schema_json, dict):
        return []
    columns = schema_json.get("columns")
    if not isinstance(columns, list):
        return []
    safe_columns = []
    for column in columns[:40]:
        if not isinstance(column, dict):
            continue
        name = _safe_label(str(column.get("name", "")), 100)
        if not name:
            continue
        data_type = _safe_label(str(column.get("type", column.get("data_type", "unknown"))), 60)
        safe_columns.append({"name": name, "type": data_type or "unknown"})
    return safe_columns


def _fit_context(context: dict[str, Any], max_chars: int) -> dict[str, Any]:
    drop_order = ["recent_queries", "recent_pipelines", "datasets", "tables"]
    while len(json.dumps(context, ensure_ascii=True, separators=(",", ":"))) > max_chars:
        removed = False
        for key in drop_order:
            if context.get(key):
                context[key].pop()
                removed = True
                break
        if removed:
            continue
        for key in ("tables", "datasets"):
            for item in context.get(key, []):
                if item.get("columns"):
                    item["columns"].pop()
                    removed = True
                    break
            if removed:
                break
        if not removed and context.get("current_sql"):
            context["current_sql"] = context["current_sql"][: max(100, max_chars // 2)]
            removed = True
        if not removed:
            break
    return context


def build_workspace_context(
    db: Session,
    workspace_id: UUID,
    user_id: UUID,
    settings: Settings,
    *,
    dataset_id: UUID | None = None,
    table_id: UUID | None = None,
    pipeline_id: UUID | None = None,
    query_text: str | None = None,
) -> tuple[dict[str, Any], int]:
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise WorkspaceResourceNotFound("Workspace not found")

    context: dict[str, Any] = {
        "workspace": {"name": _safe_label(workspace.name, 120)},
        "datasets": [],
        "tables": [],
        "recent_queries": [],
        "recent_pipelines": [],
    }
    resource_count = 0

    if dataset_id:
        datasets = db.query(Dataset).filter(
            Dataset.id == dataset_id,
            Dataset.workspace_id == workspace_id,
        ).limit(1).all()
        if not datasets:
            raise WorkspaceResourceNotFound("Dataset not found in workspace")
    else:
        datasets = db.query(Dataset).filter(
            Dataset.workspace_id == workspace_id,
        ).order_by(Dataset.updated_at.desc()).limit(12).all()
    for dataset in datasets:
        context["datasets"].append({
            "id": str(dataset.id),
            "name": _safe_label(dataset.name, 120),
            "format": _safe_label(dataset.file_format, 20),
            "status": dataset.ingestion_status.value,
            "row_count": dataset.row_count,
            "column_count": dataset.column_count,
            "columns": _schema(dataset.schema_json),
        })
        resource_count += 1

    if table_id:
        tables = db.query(LakehouseTable).filter(
            LakehouseTable.id == table_id,
            LakehouseTable.workspace_id == workspace_id,
        ).limit(1).all()
        if not tables:
            raise WorkspaceResourceNotFound("Table not found in workspace")
    else:
        tables = db.query(LakehouseTable).filter(
            LakehouseTable.workspace_id == workspace_id,
        ).order_by(LakehouseTable.updated_at.desc()).limit(12).all()
    for table in tables:
        version = db.query(DatasetVersion).filter(
            DatasetVersion.lakehouse_table_id == table.id,
            DatasetVersion.status == LakehouseVersionStatus.COMPLETED,
        ).order_by(DatasetVersion.version_number.desc()).first()
        context["tables"].append({
            "id": str(table.id),
            "name": _safe_label(table.name, 120),
            "layer": table.current_layer.value,
            "version": version.version_number if version else None,
            "row_count": version.row_count if version else None,
            "column_count": version.column_count if version else None,
            "columns": _schema(version.schema_json if version else None),
        })
        resource_count += 1

    if pipeline_id:
        pipeline = db.query(Pipeline).filter(
            Pipeline.id == pipeline_id,
            Pipeline.workspace_id == workspace_id,
        ).first()
        if not pipeline:
            raise WorkspaceResourceNotFound("Pipeline not found in workspace")
        steps = db.query(PipelineStep).filter(
            PipelineStep.pipeline_id == pipeline.id,
        ).order_by(PipelineStep.execution_order).limit(30).all()
        latest_run = db.query(PipelineRun).filter(
            PipelineRun.pipeline_id == pipeline.id,
            PipelineRun.workspace_id == workspace_id,
        ).order_by(PipelineRun.created_at.desc()).first()
        context["recent_pipelines"].append({
            "name": _safe_label(pipeline.name, 120),
            "status": pipeline.status.value,
            "steps": [
                {"name": _safe_label(step.name, 100), "type": _safe_label(step.step_type, 50)}
                for step in steps
            ],
            "latest_run": latest_run.status.value if latest_run else None,
            "failure_class": _safe_label(latest_run.failure_class, 100) if latest_run else None,
        })
        resource_count += 1
    else:
        runs = db.query(PipelineRun, Pipeline.name).join(
            Pipeline,
            Pipeline.id == PipelineRun.pipeline_id,
        ).filter(
            PipelineRun.workspace_id == workspace_id,
        ).order_by(PipelineRun.created_at.desc()).limit(5).all()
        context["recent_pipelines"] = [
            {
                "name": _safe_label(name, 120),
                "status": run.status.value,
                "failure_class": _safe_label(run.failure_class, 100),
            }
            for run, name in runs
        ]
        resource_count += len(runs)

    if query_text:
        sql_limit = min(settings.ai_max_context_chars, settings.ai_max_input_chars // 3)
        context["current_sql"] = redact_sql_literals(query_text[:sql_limit])[:sql_limit]
        resource_count += 1
    else:
        history = db.query(QueryHistory).filter(
            QueryHistory.workspace_id == workspace_id,
            QueryHistory.user_id == user_id,
        ).order_by(QueryHistory.created_at.desc()).limit(5).all()
        context["recent_queries"] = [
            {
                "status": item.execution_status.value,
                "duration_ms": item.execution_duration_ms,
                "rows_returned": item.rows_returned,
                "has_error": bool(item.error_message),
            }
            for item in history
        ]
        resource_count += len(history)

    context_limit = min(
        settings.ai_max_context_chars,
        max(1000, settings.ai_max_input_chars // 3 - 1000),
    )
    return _fit_context(context, context_limit), resource_count
