from uuid import UUID
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.v1.workspaces import membership, require_role
from app.core.db import get_db
from app.models.entities import (
    CatalogAsset,
    CatalogColumn,
    CatalogProfile,
    CatalogSchemaHistory,
    Dataset,
    DatasetVersion,
    LakehouseTable,
    LineageEdge,
    User,
    WorkspaceRole,
)
from app.schemas.catalog import (
    CatalogAssetResponse,
    CatalogAssetUpdate,
    CatalogColumnResponse,
    CatalogColumnUpdate,
    CatalogListResponse,
)
from app.services.catalog import ensure_dataset_asset, ensure_table_asset, profile_asset
from app.storage.factory import get_storage

router = APIRouter(prefix="/workspaces", tags=["catalog"])
logger = logging.getLogger("pylake.catalog")


def scoped_asset(db: Session, workspace_id: UUID, asset_id: UUID) -> CatalogAsset:
    asset = db.query(CatalogAsset).filter(
        CatalogAsset.id == asset_id,
        CatalogAsset.workspace_id == workspace_id,
    ).first()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Catalog asset not found")
    return asset


def sync_catalog(db: Session, workspace_id: UUID) -> list[CatalogAsset]:
    datasets = db.query(Dataset).filter(Dataset.workspace_id == workspace_id).all()
    tables = db.query(LakehouseTable).filter(LakehouseTable.workspace_id == workspace_id).all()
    for dataset in datasets:
        ensure_dataset_asset(db, workspace_id, dataset)
    for table in tables:
        ensure_table_asset(db, workspace_id, table)
    return db.query(CatalogAsset).filter(CatalogAsset.workspace_id == workspace_id).all()


@router.get("/{workspace_id}/catalog", response_model=CatalogListResponse)
def list_catalog(
    workspace_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    search: str | None = Query(default=None, max_length=200),
    layer: str | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    format: str | None = Query(default=None),
    owner_id: UUID | None = Query(default=None),
    tag: str | None = Query(default=None),
    sort: str = Query(default="updated"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CatalogListResponse:
    membership(db, workspace_id, user.id)
    sync_catalog(db, workspace_id)
    query = db.query(CatalogAsset).filter(CatalogAsset.workspace_id == workspace_id)
    if search:
        query = query.filter(or_(CatalogAsset.name.ilike(f"%{search}%"), CatalogAsset.description.ilike(f"%{search}%")))
    if layer:
        query = query.filter(CatalogAsset.layer == layer.upper())
    if asset_type:
        query = query.filter(CatalogAsset.asset_type == asset_type.upper())
    if format:
        query = query.filter(CatalogAsset.format == format.lower())
    if owner_id:
        query = query.filter(CatalogAsset.owner_id == owner_id)
    if tag:
        query = query.filter(CatalogAsset.tags_json.as_string().ilike(f"%{tag}%"))
    total = query.count()
    if sort == "name":
        query = query.order_by(CatalogAsset.name.asc())
    elif sort == "created":
        query = query.order_by(CatalogAsset.created_at.desc())
    else:
        query = query.order_by(CatalogAsset.updated_at.desc())
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return CatalogListResponse(items=[CatalogAssetResponse.model_validate(item) for item in items], total=total, page=page, page_size=page_size)


@router.get("/{workspace_id}/catalog/{asset_id}", response_model=CatalogAssetResponse)
def get_catalog_asset(
    workspace_id: UUID,
    asset_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CatalogAsset:
    membership(db, workspace_id, user.id)
    return scoped_asset(db, workspace_id, asset_id)


@router.patch("/{workspace_id}/catalog/{asset_id}", response_model=CatalogAssetResponse)
def update_catalog_asset(
    workspace_id: UUID,
    asset_id: UUID,
    payload: CatalogAssetUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CatalogAsset:
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    asset = scoped_asset(db, workspace_id, asset_id)
    changes = payload.model_dump(exclude_unset=True)
    if "description" in changes:
        asset.description = changes["description"]
    if "tags" in changes:
        tags = changes["tags"]
        if tags is not None:
            asset.tags_json = sorted(set(tag.strip()[:100] for tag in tags if tag.strip()))
    if "owner_id" in changes:
        if changes["owner_id"] is not None:
            owner = db.query(User).filter(User.id == changes["owner_id"]).first()
            if not owner:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Owner not found")
        asset.owner_id = changes["owner_id"]
    db.commit()
    db.refresh(asset)
    return asset


@router.patch("/{workspace_id}/catalog/{asset_id}/columns/{column_name}", response_model=CatalogColumnResponse)
def update_catalog_column(
    workspace_id: UUID,
    asset_id: UUID,
    column_name: str,
    payload: CatalogColumnUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CatalogColumn:
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    asset = scoped_asset(db, workspace_id, asset_id)
    column = db.query(CatalogColumn).filter(
        CatalogColumn.asset_id == asset.id,
        CatalogColumn.name == column_name,
    ).first()
    if not column:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Catalog column not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(column, key, value)
    db.commit()
    db.refresh(column)
    return column


@router.get("/{workspace_id}/catalog/{asset_id}/profile")
def catalog_profile(
    workspace_id: UUID,
    asset_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    membership(db, workspace_id, user.id)
    asset = scoped_asset(db, workspace_id, asset_id)
    try:
        return profile_asset(db, get_storage(), asset)
    except Exception as error:
        logger.exception("Catalog profile failed")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Metadata profiling could not complete") from error


@router.get("/{workspace_id}/catalog/{asset_id}/schema")
def catalog_schema(
    workspace_id: UUID,
    asset_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    membership(db, workspace_id, user.id)
    asset = scoped_asset(db, workspace_id, asset_id)
    columns = db.query(CatalogColumn).filter(CatalogColumn.asset_id == asset.id).order_by(CatalogColumn.name).all()
    history = db.query(CatalogSchemaHistory).filter(CatalogSchemaHistory.asset_id == asset.id).order_by(CatalogSchemaHistory.created_at.desc()).limit(100).all()
    return {
        "columns": [
            {
                "name": column.name,
                "data_type": column.data_type,
                "description": column.description,
                "business_name": column.business_name,
                "glossary_term": column.glossary_term,
            }
            for column in columns
        ],
        "history": [
            {"id": str(item.id), "version_id": str(item.version_id) if item.version_id else None, "schema": item.schema_json, "created_at": item.created_at}
            for item in history
        ],
    }


def lineage_neighbors(db: Session, workspace_id: UUID, asset_id: UUID, direction: str, limit: int = 100) -> dict:
    asset = db.query(CatalogAsset).filter(CatalogAsset.id == asset_id, CatalogAsset.workspace_id == workspace_id).first()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Catalog asset not found")
    nodes: dict[str, dict] = {
        str(asset.id): {"id": str(asset.id), "type": "ASSET", "name": asset.name, "layer": asset.layer, "asset_type": asset.asset_type}
    }
    edges: list[dict] = []
    current = {asset.id}
    visited = set(current)
    for _ in range(limit):
        found: set[UUID] = set()
        for current_id in current:
            if direction in {"upstream", "both"}:
                incoming = db.query(LineageEdge).filter(
                    LineageEdge.workspace_id == workspace_id,
                    LineageEdge.target_asset_id == current_id,
                ).limit(limit).all()
                for edge in incoming:
                    edges.append(lineage_edge_json(edge))
                    if edge.source_asset_id:
                        found.add(edge.source_asset_id)
                        nodes[str(edge.source_asset_id)] = lineage_asset_node(db, edge.source_asset_id)
            if direction in {"downstream", "both"}:
                outgoing = db.query(LineageEdge).filter(
                    LineageEdge.workspace_id == workspace_id,
                    LineageEdge.source_asset_id == current_id,
                ).limit(limit).all()
                for edge in outgoing:
                    edges.append(lineage_edge_json(edge))
                    if edge.target_asset_id:
                        found.add(edge.target_asset_id)
                        nodes[str(edge.target_asset_id)] = lineage_asset_node(db, edge.target_asset_id)
        found -= visited
        if not found:
            break
        visited |= found
        current = found
    unique_edges = {edge["id"]: edge for edge in edges}
    return {"root_asset_id": str(asset.id), "direction": direction, "nodes": list(nodes.values()), "edges": list(unique_edges.values()), "truncated": len(unique_edges) >= limit}


def lineage_asset_node(db: Session, asset_id: UUID) -> dict:
    asset = db.query(CatalogAsset).filter(CatalogAsset.id == asset_id).first()
    if not asset:
        return {"id": str(asset_id), "type": "ASSET", "name": "Deleted asset", "deleted": True}
    return {"id": str(asset.id), "type": "ASSET", "name": asset.name, "layer": asset.layer, "asset_type": asset.asset_type}


def lineage_edge_json(edge: LineageEdge) -> dict:
    return {
        "id": str(edge.id),
        "source_asset_id": str(edge.source_asset_id) if edge.source_asset_id else None,
        "target_asset_id": str(edge.target_asset_id) if edge.target_asset_id else None,
        "relation_type": edge.relation_type,
        "source_type": edge.source_type,
        "source_id": edge.source_id,
        "target_type": edge.target_type,
        "target_id": edge.target_id,
        "execution_status": edge.execution_status,
        "execution_id": edge.execution_id,
        "metadata": edge.metadata_json,
        "created_at": edge.created_at,
    }


@router.get("/{workspace_id}/catalog/{asset_id}/lineage")
def catalog_lineage(
    workspace_id: UUID,
    asset_id: UUID,
    direction: str = Query(default="both"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    membership(db, workspace_id, user.id)
    if direction not in {"upstream", "downstream", "both"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid lineage direction")
    return lineage_neighbors(db, workspace_id, asset_id, direction)


@router.get("/{workspace_id}/catalog/{asset_id}/impact")
def catalog_impact(
    workspace_id: UUID,
    asset_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    membership(db, workspace_id, user.id)
    graph = lineage_neighbors(db, workspace_id, asset_id, "downstream")
    downstream_assets = [
        node for node in graph["nodes"]
        if node["id"] != str(asset_id)
    ]
    pipelines = sorted({
        edge["target_id"]
        for edge in graph["edges"]
        if edge["target_type"] == "PIPELINE" or edge["source_type"] == "PIPELINE"
    })
    return {
        "asset_id": str(asset_id),
        "downstream_asset_count": len(downstream_assets),
        "downstream_assets": downstream_assets,
        "pipelines": pipelines,
        "coverage": "RECORDED_DEPENDENCIES",
        "unknown_dependencies": "Unknown assets and external dependencies are not included",
    }
