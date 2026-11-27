"""Read-only schema-change impact analysis over recorded and parsed evidence."""
from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlglot
from sqlglot import exp as sql_exp
from sqlalchemy.orm import Session

from app.engines.catalog_resolver import logical_name
from app.impact.graph import build_graph
from app.impact.sql_refs import extract_sql_refs, rewrite_column, rewrite_table
from app.models.entities import (
    CatalogAsset, CatalogColumn, DatasetVersion, LakehouseTable, Pipeline,
    PipelineStep, QueryExecutionStatus, QueryHistory, SavedQuery,
)
from app.engines.query_validator import validate_read_only_sql


SUPPORTED_CHANGES = {"rename_column", "drop_column", "change_type", "rename_table", "drop_table",
                     "change_transformation", "remove_pipeline_step"}


def _type_family(value: str | None) -> str:
    text = (value or "").casefold()
    if any(part in text for part in ("int", "long", "short", "bigint")):
        return "integer"
    if any(part in text for part in ("float", "double", "decimal", "numeric", "real")):
        return "numeric"
    if "char" in text or "string" in text or "text" in text or "varchar" in text:
        return "string"
    if "date" in text or "time" in text:
        return "date"
    return "other"


def _stored_queries(db: Session, workspace_id: UUID) -> list[tuple[str, str, str, str]]:
    result = [("saved_query", str(row.id), row.name, row.sql_text) for row in db.query(SavedQuery).filter(
        SavedQuery.workspace_id == workspace_id).all()]
    recent = db.query(QueryHistory).filter(QueryHistory.workspace_id == workspace_id,
        QueryHistory.execution_status == QueryExecutionStatus.SUCCESS).order_by(QueryHistory.created_at.desc()).limit(200).all()
    result.extend(("query_history", str(row.id), row.query_name or "Observed query", row.sql_text) for row in recent)
    return result


def simulate_change(db: Session, workspace_id: UUID, asset_id: UUID, change: dict[str, Any], depth: int = 5) -> dict[str, Any]:  # noqa: C901
    change_type = change.get("type")
    if change_type not in SUPPORTED_CHANGES:
        raise ValueError("Unsupported change type")
    asset = db.query(CatalogAsset).filter(CatalogAsset.id == asset_id,
        CatalogAsset.workspace_id == workspace_id).first()
    if not asset:
        table = db.query(LakehouseTable).filter(LakehouseTable.id == asset_id,
            LakehouseTable.workspace_id == workspace_id).first()
        if table:
            asset = db.query(CatalogAsset).filter(CatalogAsset.workspace_id == workspace_id,
                CatalogAsset.lakehouse_table_id == table.id).first()
    if not asset:
        raise LookupError("Asset not found in workspace")

    table = db.query(LakehouseTable).filter(LakehouseTable.id == asset.lakehouse_table_id,
        LakehouseTable.workspace_id == workspace_id).first() if asset.lakehouse_table_id else None
    old_column = change.get("column")
    new_name = change.get("new_name")
    if change_type in {"rename_column", "drop_column", "change_type"}:
        if not isinstance(old_column, str) or not old_column.strip():
            raise ValueError("A column name is required for this change")
        column = db.query(CatalogColumn).filter(CatalogColumn.asset_id == asset.id,
            CatalogColumn.name == old_column).first()
        if not column:
            raise LookupError("Column not found in workspace asset")
    else:
        column = None
    # Use a distinct name so the loop variable below does not shadow this ORM object.
    orm_step: PipelineStep | None = None
    if change_type in {"change_transformation", "remove_pipeline_step"}:
        step_id = change.get("step_id")
        if not step_id:
            raise ValueError(f"{change_type} requires step_id")
        orm_step = db.query(PipelineStep).join(Pipeline).filter(PipelineStep.id == step_id,
            Pipeline.workspace_id == workspace_id).first()
        if not orm_step:
            raise LookupError("Pipeline step not found in workspace")

    graph = build_graph(db, workspace_id, asset.id, depth=depth)
    root_node = f"asset:{asset.id}"
    downstream: list[dict[str, Any]] = []
    reachable = {root_node}
    frontier = {root_node}
    for level in range(1, depth + 1):
        following: set[str] = set()
        for edge in graph["edges"]:
            if edge["source"] in frontier and edge["target"] not in reachable:
                following.add(edge["target"])
                target_node = next((item for item in graph["nodes"] if item["id"] == edge["target"]), None)
                if target_node and target_node["type"] not in {"column", "dataset", "dataset_version"}:
                    downstream.append({**target_node, "depth": level, "evidence": edge["evidence"],
                        "confidence": edge["confidence"]})
        reachable.update(following)
        frontier = following
        if not frontier:
            break

    target_table = logical_name(table.name) if table else logical_name(asset.name)
    matched_queries: list[dict[str, Any]] = []
    inferred_queries: list[dict[str, Any]] = []
    recent_count = 0
    latest_query: str | None = None
    drafts: list[dict[str, Any]] = []
    compat: list[dict[str, Any]] = []
    for record_type, record_id, name, sql in _stored_queries(db, workspace_id):
        refs = extract_sql_refs(sql)
        if not refs["valid"]:
            continue
        mentions_table = any(logical_name(ref) == target_table for ref in refs["tables"])
        column_refs = [ref for ref in refs["columns"] if old_column and ref["name"].casefold() == old_column.casefold()]
        table_change = change_type in {"rename_table", "drop_table"}
        if mentions_table and (column_refs or table_change):
            severity = "BREAKING" if change_type in {"rename_column", "drop_column", "drop_table", "rename_table"} else "WARNING"
            item: dict[str, Any] = {
                "type": record_type, "id": record_id, "name": name, "severity": severity,
                "evidence": {"record_type": record_type, "id": record_id,
                             "detected_by": "SQLGlot table and column reference"},
                "confidence": "PARSED",
            }
            matched_queries.append(item)
            if record_type == "query_history":
                recent_count += 1
                latest_query = latest_query or record_id
            if change_type == "rename_column" and isinstance(new_name, str):
                rewritten = rewrite_column(sql, old_column, new_name)
                if rewritten:
                    try:
                        validate_read_only_sql(rewritten)
                        drafts.append({"type": "rewritten_sql", "record_id": record_id,
                                       "before": sql, "after": rewritten, "status": "DRAFT",
                                       "validated_read_only": True})
                    except Exception:
                        pass
            if change_type == "rename_table" and isinstance(new_name, str) and table:
                rewritten = rewrite_table(sql, table.name, new_name)
                if rewritten:
                    drafts.append({"type": "rewritten_sql", "record_id": record_id,
                                   "before": sql, "after": rewritten, "status": "DRAFT",
                                   "validated_read_only": True})
            if change_type == "change_type":
                source_type = column.data_type if column else None
                destination = change.get("new_type")
                family_before, family_after = _type_family(source_type), _type_family(destination)
                aggregate = False
                try:
                    parsed_sql = sqlglot.parse_one(sql, dialect="duckdb")
                    aggregate = any(
                        isinstance(fn, (sql_exp.Sum, sql_exp.Avg)) and any(
                            col.name.casefold() == old_column.casefold()
                            for col in fn.find_all(sql_exp.Column)
                        )
                        for fn in parsed_sql.find_all(sql_exp.Func)
                    )
                except Exception:
                    pass
                if family_before == "integer" and (family_after == "integer" or family_after == "numeric"):
                    severity, compatibility = "INFO", "compatible widening"
                elif aggregate and family_after == "string":
                    severity, compatibility = "BREAKING", "aggregation requires a numeric column"
                else:
                    severity, compatibility = "WARNING", "type change may affect stored SQL"
                item["severity"] = severity
                compat.append({**item, "compatibility": compatibility})
        elif old_column and column_refs:
            # Same column label without a table match is surfaced separately; never treated as a dependency.
            inferred_queries.append({"type": record_type, "id": record_id, "name": name,
                "severity": "WARNING", "evidence": {"record_type": record_type, "id": record_id,
                "detected_by": "column name match only"}, "confidence": "INFERRED_NAME"})

    affected_steps = [item for item in downstream if item["type"] == "pipeline_step"]
    if orm_step:
        orm_pipeline = db.query(Pipeline).filter(Pipeline.id == orm_step.pipeline_id,
            Pipeline.workspace_id == workspace_id).first()
        affected_steps.append({
            "id": f"step:{orm_step.id}", "type": "pipeline_step", "name": orm_step.name,
            "step_id": str(orm_step.id),
            "pipeline_id": str(orm_pipeline.id) if orm_pipeline else None,
            "step_type": orm_step.step_type, "depth": 1,
            "evidence": {"record_type": "PipelineStep", "id": str(orm_step.id),
                         "detected_by": "pipeline step record"},
            "confidence": "RECORDED",
        })

    affected_pipelines: dict[str, dict[str, Any]] = {}
    for step_dict in affected_steps:
        pipeline_id_str = step_dict.get("pipeline_id")
        if not pipeline_id_str:
            continue
        pipeline = db.query(Pipeline).filter(Pipeline.id == UUID(pipeline_id_str),
            Pipeline.workspace_id == workspace_id).first()
        if pipeline:
            step_node_id = f"step:{step_dict['step_id']}"
            affected_pipelines[str(pipeline.id)] = {
                "id": str(pipeline.id), "name": pipeline.name,
                "step_id": step_dict["step_id"], "step_name": step_dict["name"],
                "step_type": step_dict["step_type"],
                "severity": "BREAKING" if change_type in {"drop_column", "rename_column", "drop_table", "remove_pipeline_step"} else "WARNING",
                "evidence": next((edge["evidence"] for edge in graph["edges"] if edge["target"] == step_node_id), None),
                "confidence": next((edge["confidence"] for edge in graph["edges"] if edge["target"] == step_node_id), "PARSED"),
            }

    if change_type == "drop_column" and column:
        compat.append({"severity": "BREAKING", "compatibility": f"Dropping {old_column} removes a catalogued column",
                       "confidence": "RECORDED", "evidence": {"record_type": "CatalogColumn",
                       "id": str(column.id), "detected_by": "catalog schema record"}})
    elif change_type == "rename_column" and column:
        compat.append({"severity": "WARNING", "compatibility": f"Rename {old_column} to {new_name or '(unspecified)'} requires downstream updates",
                       "confidence": "RECORDED", "evidence": {"record_type": "CatalogColumn",
                       "id": str(column.id), "detected_by": "catalog schema record"}})
    elif change_type == "change_type" and column:
        old_type = column.data_type or "unknown"
        new_type = str(change.get("new_type") or "unknown")
        family_old, family_new = _type_family(old_type), _type_family(new_type)
        severity = "INFO" if family_old == "integer" and family_new in {"integer", "numeric"} else "WARNING"
        compat.append({"severity": severity, "compatibility": f"{old_type} to {new_type} type change",
                       "confidence": "RECORDED", "evidence": {"record_type": "CatalogColumn",
                       "id": str(column.id), "detected_by": "catalog schema record"}})

    impacts = [*matched_queries, *affected_pipelines.values(), *compat]
    direct = [item for item in impacts if item.get("confidence") == "RECORDED" or item in matched_queries]
    counts = {level: sum(1 for item in impacts if item.get("severity") == level)
              for level in ("BREAKING", "WARNING", "INFO")}
    current_version = db.query(DatasetVersion).filter(DatasetVersion.lakehouse_table_id == table.id).order_by(
        DatasetVersion.version_number.desc()).first() if table else None
    unknown = list(graph["uncovered"])
    unknown.append("External consumers, ad hoc SQL outside recent query history, and unrecorded dependencies are not covered.")
    if graph["truncated"]:
        unknown.append("Graph traversal reached its configured node/depth limit; additional dependencies may exist.")
    if not downstream and not matched_queries and not affected_pipelines:
        unknown.append("No downstream dependency was found in available lineage, pipeline config, saved SQL, or recent query history.")

    return {
        "asset_id": str(asset.id), "asset_name": asset.name, "change": change,
        "direct_impacts": direct, "downstream": downstream,
        "affected_pipelines": list(affected_pipelines.values()),
        "affected_steps": affected_steps,
        "affected_saved_queries": [item for item in matched_queries if item["type"] == "saved_query"],
        "recent_queries_using": {"count": recent_count, "latest_id": latest_query,
            "items": [item for item in matched_queries if item["type"] == "query_history"]},
        "inferred_name_matches": inferred_queries, "compatibility_findings": compat,
        "suggested_repairs": drafts, "uncovered": sorted(set(unknown)),
        "summary": {
            "breaking": counts["BREAKING"], "warning": counts["WARNING"], "info": counts["INFO"],
            "downstream_nodes": len(downstream), "truncated": graph["truncated"],
        },
        "schema_version_id": str(current_version.id) if current_version else None,
        "graph": graph,
    }
