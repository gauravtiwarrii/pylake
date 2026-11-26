import json
import re
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.engines.catalog_resolver import resolve_catalog
from app.engines.query_validator import SQLValidationError, validate_read_only_sql
from app.models.entities import Dataset, DatasetVersion, LakehouseTable, LakehouseVersionStatus
from app.schemas.lakehouse import TransformRequest
from app.schemas.pipelines import PipelineCreate
from app.services.pipeline_graph import PipelineGraphError, validate_pipeline_graph


class InvalidAIDraft(ValueError):
    pass


def parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise InvalidAIDraft("The AI response was not valid structured data") from error
    if not isinstance(value, dict):
        raise InvalidAIDraft("The AI response was not a structured object")
    return value


def _dataset_columns(db: Session, workspace_id: UUID, dataset_id: UUID) -> set[str]:
    dataset = db.query(Dataset).filter(
        Dataset.id == dataset_id,
        Dataset.workspace_id == workspace_id,
    ).first()
    if not dataset:
        raise InvalidAIDraft("The selected dataset is not available in this workspace")
    schema = dataset.schema_json if isinstance(dataset.schema_json, dict) else {}
    return {
        str(column.get("name"))
        for column in schema.get("columns", [])
        if isinstance(column, dict) and column.get("name")
    }


def _table_columns(db: Session, workspace_id: UUID, table_name: str) -> set[str]:
    table = db.query(LakehouseTable).filter(
        LakehouseTable.workspace_id == workspace_id,
        LakehouseTable.name == table_name,
    ).first()
    if not table:
        raise InvalidAIDraft("The selected table is not available in this workspace")
    version = db.query(DatasetVersion).filter(
        DatasetVersion.lakehouse_table_id == table.id,
        DatasetVersion.status == LakehouseVersionStatus.COMPLETED,
    ).order_by(DatasetVersion.version_number.desc()).first()
    schema = version.schema_json if version else {}
    if not isinstance(schema, dict) or not schema.get("columns"):
        raise InvalidAIDraft("The selected table has no available schema")
    return {
        str(column.get("name"))
        for column in (schema or {}).get("columns", [])
        if isinstance(column, dict) and column.get("name")
    }


def _validate_columns(columns: Any, available: set[str], label: str) -> None:
    if not isinstance(columns, list) or not columns or not all(isinstance(item, str) for item in columns):
        raise InvalidAIDraft(f"{label} must be a non-empty list of column names")
    if set(columns) - available:
        raise InvalidAIDraft(f"{label} includes a column that is not in the selected asset")


def validate_transformation_draft(
    db: Session,
    workspace_id: UUID,
    raw: dict[str, Any],
    dataset_id: UUID | None,
    table_id: UUID | None,
) -> TransformRequest:
    try:
        payload = TransformRequest.model_validate(raw)
    except ValidationError as error:
        raise InvalidAIDraft("The transformation draft does not match a supported operation") from error

    if payload.target_layer == "BRONZE":
        raise InvalidAIDraft("Transformations cannot target the immutable Bronze layer")
    if table_id:
        table = db.query(LakehouseTable).filter(
            LakehouseTable.id == table_id,
            LakehouseTable.workspace_id == workspace_id,
        ).first()
        if not table:
            raise InvalidAIDraft("The selected table is not available in this workspace")
        columns = _table_columns(db, workspace_id, table.name)
    elif dataset_id:
        columns = _dataset_columns(db, workspace_id, dataset_id)
    else:
        raise InvalidAIDraft("A workspace dataset or table is required")

    operation = payload.transformation_type
    config = payload.configuration
    if operation in {"drop", "select", "sort"}:
        _validate_columns(config.get("columns"), columns, "columns")
    elif operation == "deduplicate" and config.get("columns") is not None:
        _validate_columns(config.get("columns"), columns, "columns")
    elif operation == "rename":
        mapping = config.get("mapping")
        if not isinstance(mapping, dict) or not mapping:
            raise InvalidAIDraft("Rename requires a non-empty mapping")
        targets = list(mapping.values())
        if (
            set(mapping) - columns
            or not all(isinstance(value, str) and value.strip() for value in targets)
            or len(set(targets)) != len(targets)
        ):
            raise InvalidAIDraft("Rename mapping contains an invalid column")
    elif operation == "cast":
        casts = config.get("columns")
        allowed_types = {"string", "int", "float", "boolean", "date", "datetime"}
        if (
            not isinstance(casts, dict)
            or not casts
            or set(casts) - columns
            or not all(isinstance(value, str) and value in allowed_types for value in casts.values())
        ):
            raise InvalidAIDraft("Cast settings contain an invalid column or type")
    elif operation == "filter":
        expression = config.get("expression")
        if not isinstance(expression, dict) or expression.get("column") not in columns:
            raise InvalidAIDraft("Filter settings contain an invalid column")
        if expression.get("operator") not in {"eq", "neq", "gt", "gte", "lt", "lte", "contains"}:
            raise InvalidAIDraft("Filter operation is not supported")
        if not isinstance(expression.get("value"), (str, int, float, bool, type(None))):
            raise InvalidAIDraft("Filter value must be a scalar")
    elif operation == "fill_null":
        _validate_columns(config.get("columns"), columns, "columns")
        if not isinstance(config.get("value"), (str, int, float, bool, type(None))):
            raise InvalidAIDraft("Fill-null value must be a scalar")
    elif operation == "calculated":
        if config.get("source_column") not in columns or not isinstance(config.get("name"), str) or not config["name"].strip():
            raise InvalidAIDraft("Calculated column settings contain an invalid column or name")
        if config.get("operator") not in {"add", "subtract", "multiply", "divide"}:
            raise InvalidAIDraft("Calculated column operation is not supported")
        if isinstance(config.get("operand"), bool) or not isinstance(config.get("operand"), (int, float)):
            raise InvalidAIDraft("Calculated column operand must be numeric")
    elif operation == "normalize_names":
        pass
    return payload


def validate_pipeline_draft(
    db: Session,
    workspace_id: UUID,
    raw: dict[str, Any],
) -> PipelineCreate:
    try:
        draft = PipelineCreate.model_validate(raw)
        if len(draft.steps) > 20:
            raise InvalidAIDraft("Pipeline drafts are limited to 20 steps")
        ordered = validate_pipeline_graph([
            {
                "step_key": step.step_key,
                "step_type": step.step_type,
                "dependencies": step.dependencies,
                "execution_order": step.execution_order,
                "name": step.name,
                "configuration": step.configuration,
            }
            for step in draft.steps
        ])
    except (ValidationError, PipelineGraphError) as error:
        raise InvalidAIDraft("The pipeline draft failed validation") from error

    for step in ordered:
        config = step.get("configuration") or {}
        step_type = step["step_type"]
        if step_type == "SOURCE_DATASET":
            try:
                dataset_id = UUID(str(config.get("dataset_id")))
            except (TypeError, ValueError, AttributeError) as error:
                raise InvalidAIDraft("Pipeline source references an invalid dataset") from error
            _dataset_columns(db, workspace_id, dataset_id)
        elif step_type in {"TRANSFORM", "DATA_QUALITY", "MATERIALIZE"}:
            table_name = config.get("table_name")
            if not isinstance(table_name, str) or not table_name.strip():
                raise InvalidAIDraft("Pipeline step requires a table name")
            columns = _table_columns(db, workspace_id, table_name)
            if step_type == "TRANSFORM":
                operation = config.get("operation")
                if not isinstance(operation, str) or operation not in {"deduplicate", "drop", "select", "sort", "fill_null"}:
                    raise InvalidAIDraft("Pipeline transform operation is not supported")
                if operation in {"drop", "select", "sort"}:
                    _validate_columns(config.get("columns"), columns, "columns")
                elif operation == "deduplicate" and config.get("columns") is not None:
                    _validate_columns(config.get("columns"), columns, "columns")
                elif operation == "fill_null":
                    _validate_columns(config.get("columns"), columns, "columns")
                    if not isinstance(config.get("value"), (str, int, float, bool, type(None))):
                        raise InvalidAIDraft("Pipeline fill-null value must be a scalar")
            if step_type == "MATERIALIZE":
                target_layer = config.get("target_layer", "GOLD")
                if not isinstance(target_layer, str) or target_layer not in {"SILVER", "GOLD"}:
                    raise InvalidAIDraft("Pipeline materialization must target Silver or Gold")
            if step_type == "DATA_QUALITY":
                for key in ("max_null_rows", "max_duplicate_rows"):
                    value = config.get(key)
                    if value is not None and (type(value) is not int or value < 0):
                        raise InvalidAIDraft("Pipeline data-quality thresholds must be non-negative integers")
        elif step_type == "SQL_QUERY":
            sql = config.get("sql")
            if not isinstance(sql, str):
                raise InvalidAIDraft("SQL pipeline step requires SQL text")
            try:
                table_names, _ = validate_read_only_sql(sql)
                resolve_catalog(db, workspace_id, table_names)
            except (SQLValidationError, KeyError) as error:
                raise InvalidAIDraft("Pipeline SQL did not pass workspace read-only validation") from error

    draft.status = "DRAFT"
    return draft
