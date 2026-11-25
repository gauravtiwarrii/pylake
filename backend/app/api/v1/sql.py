import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.v1.workspaces import membership, require_role
from app.core.db import get_db
from app.engines.duckdb_engine import DuckDBExecutionError
from app.engines.query_executor import execute_workspace_query
from app.engines.query_validator import SQLValidationError
from app.models.entities import (
    DatasetVersion,
    LakehouseTable,
    LakehouseVersionStatus,
    QueryExecutionStatus,
    QueryHistory,
    SavedQuery,
    User,
    WorkspaceRole,
)
from app.schemas.sql import (
    QueryHistoryResponse,
    SQLColumn,
    SQLExecuteRequest,
    SQLExecuteResponse,
    SavedQueryCreate,
    SavedQueryResponse,
    SavedQueryUpdate,
)
from app.storage.factory import get_storage
from app.services.catalog import ensure_table_asset
from app.services.lineage import record_lineage
from app.engines.query_validator import validate_read_only_sql
from app.engines.catalog_resolver import resolve_catalog

router = APIRouter(prefix="/workspaces", tags=["sql"])


def safe_error(error: Exception) -> str:
    message = str(error).strip().replace("\n", " ")
    return message[:1000] or "SQL execution failed"


@router.post("/{workspace_id}/sql/execute", response_model=SQLExecuteResponse)
def execute_sql(
    workspace_id: UUID,
    payload: SQLExecuteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SQLExecuteResponse:
    membership(db, workspace_id, user.id)
    started = time.perf_counter()
    history = QueryHistory(
        workspace_id=workspace_id,
        user_id=user.id,
        query_name=payload.query_name,
        sql_text=payload.sql,
        execution_status=QueryExecutionStatus.RUNNING,
    )
    db.add(history)
    db.flush()

    try:
        result = execute_workspace_query(
            db=db,
            storage=get_storage(),
            workspace_id=workspace_id,
            sql=payload.sql,
            limit=payload.limit,
        )
        duration = result["duration_ms"]
        history.execution_status = QueryExecutionStatus.SUCCESS
        history.execution_duration_ms = duration
        history.rows_returned = result["returned_rows"]
        history.error_message = None
        db.commit()
        db.refresh(history)
        table_names, _ = validate_read_only_sql(payload.sql)
        resolved = resolve_catalog(db, workspace_id, table_names)
        for logical_name, version in resolved.items():
            table = db.query(LakehouseTable).join(DatasetVersion).filter(
                DatasetVersion.id == version.id,
                LakehouseTable.id == version.lakehouse_table_id,
            ).first()
            if table:
                asset = ensure_table_asset(db, workspace_id, table)
                record_lineage(
                    db,
                    workspace_id,
                    "QUERY",
                    "DATASET_VERSION",
                    str(version.id),
                    "SQL_QUERY",
                    str(history.id),
                    source_asset_id=asset.id,
                    execution_status="SUCCESS",
                    execution_id=str(history.id),
                    metadata={"table": logical_name, "version": version.version_number},
                )
        db.commit()
        return SQLExecuteResponse(
            id=history.id,
            status="SUCCESS",
            duration_ms=duration,
            columns=[SQLColumn(**column) for column in result["columns"]],
            rows=result["rows"],
            returned_rows=result["returned_rows"],
            total_rows_available=result["total_rows_available"],
            truncated=result["truncated"],
            error=None,
        )
    except (SQLValidationError, DuckDBExecutionError) as error:
        duration = int((time.perf_counter() - started) * 1000)
        history.execution_status = QueryExecutionStatus.FAILED
        history.execution_duration_ms = duration
        history.rows_returned = 0
        history.error_message = safe_error(error)
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=safe_error(error))
    except Exception as error:
        duration = int((time.perf_counter() - started) * 1000)
        history.execution_status = QueryExecutionStatus.FAILED
        history.execution_duration_ms = duration
        history.rows_returned = 0
        history.error_message = "SQL execution failed"
        db.commit()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="SQL execution failed") from error


@router.get("/{workspace_id}/sql/history", response_model=list[QueryHistoryResponse])
def list_history(
    workspace_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[QueryHistory]:
    membership(db, workspace_id, user.id)
    return db.query(QueryHistory).filter(
        QueryHistory.workspace_id == workspace_id,
        QueryHistory.user_id == user.id,
    ).order_by(QueryHistory.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()


@router.get("/{workspace_id}/sql/history/{query_id}", response_model=QueryHistoryResponse)
def get_history(
    workspace_id: UUID,
    query_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> QueryHistory:
    membership(db, workspace_id, user.id)
    item = db.query(QueryHistory).filter(
        QueryHistory.id == query_id,
        QueryHistory.workspace_id == workspace_id,
        QueryHistory.user_id == user.id,
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query history not found")
    return item


@router.delete("/{workspace_id}/sql/history/{query_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_history(
    workspace_id: UUID,
    query_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    membership(db, workspace_id, user.id)
    item = db.query(QueryHistory).filter(
        QueryHistory.id == query_id,
        QueryHistory.workspace_id == workspace_id,
        QueryHistory.user_id == user.id,
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query history not found")
    db.delete(item)
    db.commit()


@router.get("/{workspace_id}/sql/catalog")
def sql_catalog(
    workspace_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    membership(db, workspace_id, user.id)
    tables = db.query(LakehouseTable).filter(LakehouseTable.workspace_id == workspace_id).all()
    items = []
    for table in tables:
        version = db.query(DatasetVersion).filter(
            DatasetVersion.lakehouse_table_id == table.id,
            DatasetVersion.status == LakehouseVersionStatus.COMPLETED,
            DatasetVersion.file_format == "parquet",
        ).order_by(DatasetVersion.version_number.desc()).first()
        if not version:
            continue
        items.append({
            "name": table.name.lower().replace("-", "_").replace(" ", "_"),
            "display_name": table.name,
            "layer": version.layer.value,
            "version": version.version_number,
            "row_count": version.row_count,
            "column_count": version.column_count,
            "columns": version.schema_json.get("columns", []) if version.schema_json else [],
        })
    return {"items": items}


@router.get("/{workspace_id}/sql/catalog/{table_name}/schema")
def sql_catalog_schema(
    workspace_id: UUID,
    table_name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    membership(db, workspace_id, user.id)
    table = db.query(LakehouseTable).filter(
        LakehouseTable.workspace_id == workspace_id,
        LakehouseTable.name.ilike(table_name),
    ).first()
    if not table:
        normalized = table_name.lower().replace("-", "_").replace(" ", "_")
        table = db.query(LakehouseTable).filter(
            LakehouseTable.workspace_id == workspace_id,
        ).all()
        table = next((item for item in table if item.name.lower().replace("-", "_").replace(" ", "_") == normalized), None)
    if not table:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")
    version = db.query(DatasetVersion).filter(
        DatasetVersion.lakehouse_table_id == table.id,
        DatasetVersion.status == LakehouseVersionStatus.COMPLETED,
        DatasetVersion.file_format == "parquet",
    ).order_by(DatasetVersion.version_number.desc()).first()
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No queryable version found")
    return {
        "name": table_name,
        "layer": version.layer.value,
        "version": version.version_number,
        "columns": version.schema_json.get("columns", []) if version.schema_json else [],
    }


@router.get("/{workspace_id}/sql/saved", response_model=list[SavedQueryResponse])
def list_saved(
    workspace_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SavedQuery]:
    membership(db, workspace_id, user.id)
    return db.query(SavedQuery).filter(
        SavedQuery.workspace_id == workspace_id,
        SavedQuery.user_id == user.id,
    ).order_by(SavedQuery.updated_at.desc()).all()


@router.post("/{workspace_id}/sql/saved", response_model=SavedQueryResponse, status_code=status.HTTP_201_CREATED)
def create_saved(
    workspace_id: UUID,
    payload: SavedQueryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SavedQuery:
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    if db.query(SavedQuery).filter(SavedQuery.workspace_id == workspace_id, SavedQuery.name == payload.name).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A saved query with this name already exists")
    item = SavedQuery(
        workspace_id=workspace_id,
        user_id=user.id,
        name=payload.name.strip(),
        description=payload.description,
        sql_text=payload.sql_text,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{workspace_id}/sql/saved/{saved_query_id}", response_model=SavedQueryResponse)
def update_saved(
    workspace_id: UUID,
    saved_query_id: UUID,
    payload: SavedQueryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SavedQuery:
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    item = db.query(SavedQuery).filter(
        SavedQuery.id == saved_query_id,
        SavedQuery.workspace_id == workspace_id,
        SavedQuery.user_id == user.id,
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved query not found")
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and db.query(SavedQuery).filter(
        SavedQuery.workspace_id == workspace_id,
        SavedQuery.name == changes["name"],
        SavedQuery.id != item.id,
    ).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A saved query with this name already exists")
    for key, value in changes.items():
        setattr(item, key, value.strip() if isinstance(value, str) and key in {"name", "description"} else value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{workspace_id}/sql/saved/{saved_query_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved(
    workspace_id: UUID,
    saved_query_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    require_role(db, workspace_id, user, WorkspaceRole.EDITOR)
    item = db.query(SavedQuery).filter(
        SavedQuery.id == saved_query_id,
        SavedQuery.workspace_id == workspace_id,
        SavedQuery.user_id == user.id,
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved query not found")
    db.delete(item)
    db.commit()
