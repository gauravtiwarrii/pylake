from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.context import redacted_text
from app.ask.citations import citation, unique_citations
from app.models.entities import (
    CatalogAsset, CatalogColumn, CatalogProfile, Dataset, DatasetVersion, LakehouseTable,
    LineageEdge, Pipeline, PipelineRun, QueryHistory, QueryExecutionStatus,
    RunStatus, TrustSnapshot, LakehouseVersionStatus,
)


def _asset_match(db: Session, workspace_id: UUID, question: str) -> CatalogAsset | None:
    assets = db.query(CatalogAsset).filter(CatalogAsset.workspace_id == workspace_id).all()
    lowered = question.casefold()
    exact = [asset for asset in assets if asset.name.casefold() in lowered]
    if exact:
        return max(exact, key=lambda asset: len(asset.name))
    words = set(re.findall(r"[\w-]+", lowered))
    scored = []
    for asset in assets:
        name_words = set(re.findall(r"[\w-]+", asset.name.casefold()))
        overlap = len(words & name_words) / max(1, len(name_words))
        ratio = SequenceMatcher(None, asset.name.casefold(), lowered).ratio()
        score = max(overlap, ratio)
        if score >= .55:
            scored.append((score, asset))
    return max(scored, default=(0, None), key=lambda item: item[0])[1]


def _result(summary: str, rows: list[dict[str, Any]], citations: list[dict[str, str]], limitations: list[str] | None = None) -> dict[str, Any]:
    return {"answer_type": "metadata", "summary": summary, "table_rows": rows,
            "citations": unique_citations(citations), "limitations": limitations or [], "confidence": "high"}


def answer_metadata(db: Session, workspace_id: UUID, user_id: UUID, question: str) -> dict[str, Any] | None:
    q = question.casefold()
    if any(term in q for term in ("missing value", "missing values", "null", "nulls", "incomplete")):
        assets = db.query(CatalogAsset).filter(CatalogAsset.workspace_id == workspace_id).all()
        rows, cites = [], []
        for asset in assets:
            cites.append(citation("table" if asset.lakehouse_table_id else "dataset", asset.id, asset.name))
            snap = db.query(TrustSnapshot).filter(TrustSnapshot.workspace_id == workspace_id, TrustSnapshot.asset_id == asset.id).order_by(TrustSnapshot.computed_at.desc()).first()
            metric = snap.metrics_json.get("completeness", {}) if snap else {}
            if metric.get("status") == "MEASURED":
                by_column = metric.get("value", {}).get("column_null_percent", {})
                rows.extend({"asset": asset.name, "column": name, "null_percent": value} for name, value in by_column.items() if value > 0)
                cites.append(citation("snapshot", snap.id, f"Latest trust snapshot for {asset.name}"))
            elif not snap:
                profile = db.query(CatalogProfile).filter(CatalogProfile.asset_id == asset.id).first()
                statistics = (profile.statistics_json or {}).get("statistics", {}) if profile else {}
                for name, stats in statistics.items():
                    null_percent = stats.get("null_percentage")
                    if isinstance(null_percent, (int, float)) and null_percent > 0:
                        rows.append({"asset": asset.name, "column": name, "null_percent": null_percent})
                if profile:
                    cites.append(citation("snapshot", profile.id, f"Catalog profile for {asset.name}"))
        rows.sort(key=lambda row: row["null_percent"], reverse=True)
        return _result(f"Found {len(rows)} measured columns with missing values.", rows[:100], cites,
                       ["Assets without trust or catalog profile measurements cannot be assessed for missing values."] if not rows else [])
    if "trust" in q and any(word in q for word in ("lowest", "worst", "least", "score")):
        assets = db.query(CatalogAsset).filter(CatalogAsset.workspace_id == workspace_id).all()
        rows, cites = [], []
        for asset in assets:
            cites.append(citation("table" if asset.lakehouse_table_id else "dataset", asset.id, asset.name))
            snap = db.query(TrustSnapshot).filter(TrustSnapshot.workspace_id == workspace_id, TrustSnapshot.asset_id == asset.id).order_by(TrustSnapshot.computed_at.desc()).first()
            if snap:
                rows.append({"asset": asset.name, "overall_score": snap.overall_score, "computed_at": snap.computed_at.isoformat()})
                cites.append(citation("snapshot", snap.id, f"Trust snapshot for {asset.name}"))
        rows.sort(key=lambda row: row["overall_score"] if row["overall_score"] is not None else 101)
        return _result("Assets ordered by their latest measured trust score.", rows[:20], cites,
                       ["Assets without snapshots or with an unmeasured overall score are omitted."])
    if "pipeline" in q and any(word in q for word in ("fail", "failed", "error", "recent")):
        runs = db.query(PipelineRun, Pipeline.name).join(Pipeline, Pipeline.id == PipelineRun.pipeline_id).filter(
            PipelineRun.workspace_id == workspace_id, PipelineRun.status == RunStatus.FAILED
        ).order_by(PipelineRun.created_at.desc()).limit(20).all()
        rows = [{"pipeline": name, "status": run.status.value, "created_at": run.created_at.isoformat(), "last_error": redacted_text(run.error_message, 500)} for run, name in runs]
        cites = [citation("pipeline", run.pipeline_id, name) for run, name in runs]
        cites.extend(citation("pipeline", run.id, f"Failed run for {name}") for run, name in runs)
        return _result(f"Found {len(rows)} failed pipeline runs.", rows, cites)
    if "query" in q and any(word in q for word in ("fail", "failed", "error", "recent")):
        runs = db.query(QueryHistory).filter(QueryHistory.workspace_id == workspace_id,
            QueryHistory.user_id == user_id, QueryHistory.execution_status == QueryExecutionStatus.FAILED
        ).order_by(QueryHistory.created_at.desc()).limit(20).all()
        rows = [{"query": row.query_name or "Untitled query", "created_at": row.created_at.isoformat(), "error": redacted_text(row.error_message, 500)} for row in runs]
        return _result(f"Found {len(rows)} failed queries in your history.", rows, [citation("query", row.id, row.query_name or "Failed query") for row in runs])
    if any(word in q for word in ("lineage", "upstream", "downstream")):
        asset = _asset_match(db, workspace_id, question)
        if not asset:
            return None
        edges = db.query(LineageEdge).filter(LineageEdge.workspace_id == workspace_id,
            (LineageEdge.source_asset_id == asset.id) | (LineageEdge.target_asset_id == asset.id)
        ).order_by(LineageEdge.created_at.desc()).limit(50).all()
        rows = [{"source": edge.source_id, "relation": edge.relation_type,
                 "target": edge.target_id, "created_at": edge.created_at.isoformat()} for edge in edges]
        cites = [citation("dataset" if edge.source_type == "DATASET" else "table", edge.source_asset_id or edge.id, rows[i]["source"]) for i, edge in enumerate(edges)]
        cites.extend(citation("dataset" if edge.target_type == "DATASET" else "table", edge.target_asset_id or edge.id, rows[i]["target"]) for i, edge in enumerate(edges))
        cites.append(citation("table" if asset.lakehouse_table_id else "dataset", asset.id, asset.name))
        return _result(f"Lineage for {asset.name} includes {len(rows)} recorded relationship(s).", rows, cites)
    if any(word in q for word in ("schema", "columns", "column")) and ("what" in q or "which" in q or "schema" in q or "columns" in q):
        asset = _asset_match(db, workspace_id, question)
        if not asset:
            return None
        columns = db.query(CatalogColumn).filter(CatalogColumn.asset_id == asset.id).order_by(CatalogColumn.name).all()
        rows = [{"column": column.name, "type": column.data_type, "description": column.description} for column in columns]
        cites = [citation("table" if asset.lakehouse_table_id else "dataset", asset.id, asset.name)]
        cites.extend(citation("column", col.id, asset.name, col.name) for col in columns)
        if not rows:
            return {"answer_type": "clarification", "summary": f"No catalog column records are available for {asset.name} yet.", "table_rows": [], "citations": cites, "limitations": ["Refresh the catalog schema to answer this question."], "confidence": "low"}
        return _result(f"{asset.name} has {len(rows)} cataloged columns.", rows, cites)
    if "gold" in q and any(word in q for word in ("latest", "newest", "recent")) or "latest version" in q or "latest versions" in q:
        tables = db.query(LakehouseTable).filter(LakehouseTable.workspace_id == workspace_id).all()
        rows, cites = [], []
        for table in tables:
            version = db.query(DatasetVersion).filter(DatasetVersion.lakehouse_table_id == table.id,
                DatasetVersion.status == LakehouseVersionStatus.COMPLETED).order_by(DatasetVersion.version_number.desc()).first()
            if version and ("gold" not in q or version.layer.value == "GOLD"):
                rows.append({"table": table.name, "layer": version.layer.value, "version": version.version_number, "created_at": version.created_at.isoformat(), "rows": version.row_count})
                cites.append(citation("table", table.id, table.name)); cites.append(citation("dataset", version.id, f"{table.name} version {version.version_number}"))
        rows.sort(key=lambda row: row["created_at"], reverse=True)
        return _result(f"Found {len(rows)} latest completed table version(s).", rows, cites)
    if "storage" in q and "layer" in q:
        versions = db.query(DatasetVersion, LakehouseTable).join(LakehouseTable, LakehouseTable.id == DatasetVersion.lakehouse_table_id).filter(
            LakehouseTable.workspace_id == workspace_id, DatasetVersion.status == LakehouseVersionStatus.COMPLETED).all()
        grouped: dict[str, dict[str, Any]] = {}
        for version, table in versions:
            group = grouped.setdefault(version.layer.value, {"layer": version.layer.value, "size_bytes": 0, "objects": 0})
            group["size_bytes"] += version.file_size_bytes; group["objects"] += 1
        cites = [citation("dataset", version.id, f"{table.name} version {version.version_number}") for version, table in versions]
        rows = sorted(grouped.values(), key=lambda row: row["size_bytes"], reverse=True)
        return _result("Recorded Parquet storage usage grouped by lakehouse layer.", rows, cites)
    if "largest" in q or "storage" in q:
        datasets = db.query(Dataset).filter(Dataset.workspace_id == workspace_id).order_by(Dataset.file_size_bytes.desc()).limit(20).all()
        rows = [{"dataset": dataset.name, "size_bytes": dataset.file_size_bytes, "rows": dataset.row_count} for dataset in datasets]
        return _result("Largest uploaded datasets by recorded file size.", rows, [citation("dataset", row.id, row.name) for row in datasets])
    return None
