"""Bounded, workspace-scoped dependency graph built from recorded evidence."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.impact.sql_refs import extract_sql_refs
from app.models.entities import (
    CatalogAsset, CatalogColumn, Dataset, DatasetVersion, LakehouseTable, LineageEdge,
    Pipeline, PipelineStep, QueryExecutionStatus, QueryHistory, SavedQuery,
)
from app.engines.catalog_resolver import logical_name

MAX_NODES = 500


def _node(node_id: str, kind: str, name: str, **extra: Any) -> dict[str, Any]:
    return {"id": node_id, "type": kind, "name": name, **extra}


def build_graph(db: Session, workspace_id: UUID, asset_id: UUID | None = None,
                depth: int = 5, max_nodes: int = MAX_NODES) -> dict[str, Any]:
    depth = min(10, max(1, depth))
    max_nodes = min(MAX_NODES, max(1, max_nodes))
    assets = db.query(CatalogAsset).filter(CatalogAsset.workspace_id == workspace_id).all()
    assets_by_id = {asset.id: asset for asset in assets}
    tables = db.query(LakehouseTable).filter(LakehouseTable.workspace_id == workspace_id).all()
    tables_by_name = {logical_name(table.name): table for table in tables}
    table_assets = {asset.lakehouse_table_id: asset for asset in assets if asset.lakehouse_table_id}
    datasets = db.query(Dataset).filter(Dataset.workspace_id == workspace_id).all()
    datasets_by_id = {dataset.id: dataset for dataset in datasets}
    if asset_id is not None and asset_id not in assets_by_id:
        # API permits LakehouseTable IDs as an alias for their catalog asset.
        matching = table_assets.get(asset_id)
        if matching is None:
            raise LookupError("Asset not found in workspace")
        asset_id = matching.id

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    unknown: list[str] = []
    truncated = False

    def add_node(node: dict[str, Any]) -> bool:
        nonlocal truncated
        if node["id"] in nodes:
            return True
        if len(nodes) >= max_nodes:
            truncated = True
            return False
        nodes[node["id"]] = node
        return True

    def add_edge(source: str, target: str, evidence_type: str, evidence_id: Any, detected: str,
                 confidence: str, **extra: Any) -> None:
        if source in nodes and target in nodes:
            edges.append({"source": source, "target": target, "evidence": {"record_type": evidence_type,
                "id": str(evidence_id), "detected_by": detected}, "confidence": confidence, **extra})

    for asset in assets:
        if asset_id is None or asset.id == asset_id:
            add_node(_node(f"asset:{asset.id}", "asset", asset.name, asset_id=str(asset.id), layer=asset.layer,
                           asset_type=asset.asset_type))
    if asset_id is not None and f"asset:{asset_id}" not in nodes:
        raise LookupError("Asset not found in workspace")

    # Dataset/version nodes are linked only through their actual foreign keys.
    for dataset in datasets:
        add_node(_node(f"dataset:{dataset.id}", "dataset", dataset.name, dataset_id=str(dataset.id)))
        dataset_asset = next((item for item in assets if item.dataset_id == dataset.id), None)
        if dataset_asset:
            add_node(_node(f"asset:{dataset_asset.id}", "asset", dataset_asset.name, asset_id=str(dataset_asset.id),
                           layer=dataset_asset.layer, asset_type=dataset_asset.asset_type))
            add_edge(f"asset:{dataset_asset.id}", f"dataset:{dataset.id}", "Dataset", dataset.id,
                     "catalog asset dataset foreign key", "RECORDED")
    versions = db.query(DatasetVersion).join(Dataset, Dataset.id == DatasetVersion.dataset_id).filter(
        Dataset.workspace_id == workspace_id).all()
    for version in versions:
        version_id = f"version:{version.id}"
        add_node(_node(version_id, "dataset_version", f"Version {version.version_number}",
                       version_id=str(version.id), dataset_id=str(version.dataset_id),
                       table_id=str(version.lakehouse_table_id) if version.lakehouse_table_id else None,
                       layer=version.layer.value, status=version.status.value))
        if version.lakehouse_table_id and version.lakehouse_table_id in table_assets:
            source_id = f"asset:{table_assets[version.lakehouse_table_id].id}"
            add_edge(source_id, version_id, "DatasetVersion", version.id,
                     "dataset version lakehouse_table_id", "RECORDED")
        elif version.dataset_id:
            dataset_asset = next((item for item in assets if item.dataset_id == version.dataset_id), None)
            if dataset_asset:
                add_edge(f"asset:{dataset_asset.id}", version_id, "DatasetVersion", version.id,
                         "dataset version dataset_id", "RECORDED")
        add_edge(version_id, f"dataset:{version.dataset_id}", "DatasetVersion", version.id,
                 "dataset version dataset_id", "RECORDED")

    # Explicit LineageEdge records are the only RECORDED relationships.
    lineage = db.query(LineageEdge).filter(LineageEdge.workspace_id == workspace_id).all()
    for edge in lineage:
        src_asset = assets_by_id.get(edge.source_asset_id)
        dst_asset = assets_by_id.get(edge.target_asset_id)
        if src_asset and dst_asset:
            source, target = f"asset:{src_asset.id}", f"asset:{dst_asset.id}"
            if add_node(_node(source, "asset", src_asset.name, asset_id=str(src_asset.id), layer=src_asset.layer,
                              asset_type=src_asset.asset_type)) and add_node(_node(target, "asset", dst_asset.name,
                              asset_id=str(dst_asset.id), layer=dst_asset.layer, asset_type=dst_asset.asset_type)):
                add_edge(source, target, "LineageEdge", edge.id, "stored lineage edge", "RECORDED",
                         relation_type=edge.relation_type)

    # Add catalog columns as nodes, linked to their owning asset as recorded schema.
    columns = db.query(CatalogColumn).join(CatalogAsset, CatalogAsset.id == CatalogColumn.asset_id).filter(
        CatalogAsset.workspace_id == workspace_id).all()
    columns_by_asset: dict[UUID, list[CatalogColumn]] = {}
    for column in columns:
        columns_by_asset.setdefault(column.asset_id, []).append(column)
        asset = assets_by_id.get(column.asset_id)
        if asset and add_node(_node(f"column:{column.id}", "column", column.name, column_id=str(column.id),
                                    asset_id=str(asset.id), data_type=column.data_type)):
            add_node(_node(f"asset:{asset.id}", "asset", asset.name, asset_id=str(asset.id), layer=asset.layer,
                           asset_type=asset.asset_type))
            add_edge(f"asset:{asset.id}", f"column:{column.id}", "CatalogColumn", column.id,
                     "catalog schema", "RECORDED")

    pipelines = db.query(Pipeline).filter(Pipeline.workspace_id == workspace_id).all()
    pipeline_by_id = {pipeline.id: pipeline for pipeline in pipelines}
    steps = db.query(PipelineStep).join(Pipeline, Pipeline.id == PipelineStep.pipeline_id).filter(
        Pipeline.workspace_id == workspace_id).all()
    for pipeline in pipelines:
        add_node(_node(f"pipeline:{pipeline.id}", "pipeline", pipeline.name, pipeline_id=str(pipeline.id)))
    for step in steps:
        pipeline = pipeline_by_id[step.pipeline_id]
        step_id = f"step:{step.id}"
        add_node(_node(step_id, "pipeline_step", step.name, step_id=str(step.id), pipeline_id=str(pipeline.id),
                       step_type=step.step_type))
        add_edge(f"pipeline:{pipeline.id}", step_id, "PipelineStep", step.id,
                 "step belongs to pipeline", "RECORDED")
        config = step.configuration_json or {}
        referenced_names: set[str] = set()
        if step.step_type == "SQL_QUERY" and isinstance(config.get("sql"), str):
            refs = extract_sql_refs(config["sql"])
            if not refs["valid"]:
                unknown.append(f"Pipeline step {step.name}: stored SQL could not be analyzed")
            referenced_names.update(logical_name(name) for name in refs["tables"])
            normalized_ref_names = {name.casefold() for name in refs["tables"]}
            for ref in refs["columns"]:
                if ref["name"]:
                    for asset in assets:
                        for column in columns_by_asset.get(asset.id, []):
                            if column.name.casefold() == ref["name"].casefold() and asset.name.casefold() in normalized_ref_names:
                                add_edge(f"column:{column.id}", step_id, "PipelineStep", step.id,
                                         f"SQLGlot column reference: {ref['name']}", "PARSED",
                                         column=column.name)
        else:
            for key in ("table_name", "source_table", "target_table"):
                value = config.get(key)
                if isinstance(value, str):
                    referenced_names.add(logical_name(value))
            for key in ("columns", "column", "column_name"):
                value = config.get(key)
                values = value if isinstance(value, list) else [value]
                for name in values:
                    if isinstance(name, str):
                        for asset in assets:
                            for column in columns_by_asset.get(asset.id, []):
                                if column.name.casefold() == name.casefold():
                                    add_edge(f"asset:{asset.id}", step_id, "PipelineStep", step.id,
                                             f"configuration field {key} references {name}", "PARSED",
                                             column=name)
        for name in referenced_names:
            table = tables_by_name.get(name)
            asset = table_assets.get(table.id) if table else None
            if asset:
                add_node(_node(f"asset:{asset.id}", "asset", asset.name, asset_id=str(asset.id),
                               layer=asset.layer, asset_type=asset.asset_type))
                add_edge(f"asset:{asset.id}", step_id, "PipelineStep", step.id,
                         "SQLGlot table reference" if step.step_type == "SQL_QUERY" else "step configuration table reference",
                         "PARSED")
            else:
                unknown.append(f"Pipeline step {step.name}: referenced table '{name}' is not in this workspace catalog")

    # Saved and observed SQL use is parsed, never inferred from query text matching alone.
    query_records: list[tuple[str, str, str, Any]] = []
    for saved in db.query(SavedQuery).filter(SavedQuery.workspace_id == workspace_id).all():
        query_records.append((f"saved_query:{saved.id}", saved.name, saved.sql_text, saved.id))
    recent = db.query(QueryHistory).filter(QueryHistory.workspace_id == workspace_id,
        QueryHistory.execution_status == QueryExecutionStatus.SUCCESS).order_by(QueryHistory.created_at.desc()).limit(200).all()
    for item in recent:
        query_records.append((f"query:{item.id}", item.query_name or "Observed query", item.sql_text, item.id))
    for node_id, name, sql, record_id in query_records:
        is_history = node_id.startswith("query:")
        add_node(_node(node_id, "observed_query" if is_history else "saved_query", name,
                       record_id=str(record_id), observed=is_history))
        refs = extract_sql_refs(sql)
        if not refs["valid"]:
            unknown.append(f"{name}: stored SQL could not be analyzed")
            continue
        referenced_assets: set[UUID] = set()
        for ref_name in refs["tables"]:
            table = tables_by_name.get(logical_name(ref_name))
            asset = table_assets.get(table.id) if table else None
            if asset:
                referenced_assets.add(asset.id)
                add_node(_node(f"asset:{asset.id}", "asset", asset.name, asset_id=str(asset.id),
                               layer=asset.layer, asset_type=asset.asset_type))
                add_edge(f"asset:{asset.id}", node_id, "QueryHistory" if is_history else "SavedQuery", record_id,
                         "SQLGlot table reference", "PARSED", observed=is_history)
            else:
                unknown.append(f"{name}: referenced table '{ref_name}' is not in this workspace catalog")
        for ref in refs["columns"]:
            for asset_key in referenced_assets:
                for column in columns_by_asset.get(asset_key, []):
                    if ref["name"].casefold() == column.name.casefold():
                        add_edge(f"column:{column.id}", node_id, "QueryHistory" if is_history else "SavedQuery",
                                 record_id, "SQLGlot column reference", "PARSED", observed=is_history,
                                 column=column.name)

    if asset_id is not None:
        root = f"asset:{asset_id}"
        reachable = {root}
        frontier = {root}
        kept_edges = []
        for _ in range(depth):
            new_frontier = set()
            for edge in edges:
                if edge["source"] in frontier and edge["target"] not in reachable:
                    new_frontier.add(edge["target"])
                    kept_edges.append(edge)
            reachable.update(new_frontier)
            frontier = new_frontier
            if not frontier:
                break
        # Keep connected discovered dependencies only, and avoid unrelated workspace nodes.
        nodes = {key: value for key, value in nodes.items() if key in reachable}
        edges = kept_edges + [edge for edge in edges if edge["source"] in reachable and edge["target"] in reachable]
        if len(reachable) >= max_nodes:
            truncated = True

    return {"nodes": list(nodes.values()), "edges": edges, "depth": depth,
            "truncated": truncated, "uncovered": sorted(set(unknown))}
