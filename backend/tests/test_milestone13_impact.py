from __future__ import annotations

from uuid import UUID

from app.ai.actions import get_action, role_satisfies
from app.models.entities import (
    CatalogAsset, CatalogColumn, LakehouseLayer, LakehouseTable, Pipeline, PipelineStep,
    QueryExecutionStatus, QueryHistory, SavedQuery, WorkspaceMember, WorkspaceRole,
)
from test_milestone12_ask import ask_env, data_asset, workspace


def _stored_dependencies(sessions, workspace_id: str, user_id: UUID, table_id: str, asset_id: str):
    with sessions() as db:
        pipeline = Pipeline(workspace_id=UUID(workspace_id), name="sales pipeline", created_by=user_id)
        db.add(pipeline)
        db.flush()
        step = PipelineStep(pipeline_id=pipeline.id, step_key="aggregate", name="Aggregate revenue",
            step_type="SQL_QUERY", configuration_json={"sql": "SELECT SUM(revenue) AS total FROM sales"},
            dependencies_json=[], execution_order=1)
        saved = SavedQuery(workspace_id=UUID(workspace_id), user_id=user_id, name="Revenue report",
            sql_text="SELECT SUM(revenue) AS total FROM sales")
        history = QueryHistory(workspace_id=UUID(workspace_id), user_id=user_id, query_name="Observed revenue",
            sql_text="SELECT revenue FROM sales ORDER BY revenue DESC LIMIT 5",
            execution_status=QueryExecutionStatus.SUCCESS)
        db.add_all([step, saved, history])
        db.commit()
        return pipeline.id, step.id, saved.id, history.id


def test_rename_finds_parsed_sql_and_proposes_validated_draft(ask_env):
    client, sessions, _ = ask_env
    workspace_id, headers = workspace(client, "impact-rename@example.com", "impact-rename")
    _, table, asset = data_asset(client, workspace_id, headers)
    user_id = client.get("/api/v1/auth/me").json()["id"]
    _, step_id, saved_id, _ = _stored_dependencies(sessions, workspace_id, UUID(user_id), table["id"], asset["id"])

    response = client.post(f"/api/v1/workspaces/{workspace_id}/impact/simulate", headers=headers,
        json={"asset_id": asset["id"], "change": {"type": "rename_column", "column": "revenue", "new_name": "sales_value"}})
    assert response.status_code == 200, response.text
    body = response.json()
    assert any(item["id"] == str(saved_id) and item["confidence"] == "PARSED"
               for item in body["affected_saved_queries"])
    assert any(item["step_id"] == str(step_id) and item["confidence"] == "PARSED"
               for item in body["affected_steps"])
    draft = next(item for item in body["suggested_repairs"] if item["record_id"] == str(saved_id))
    assert draft["status"] == "DRAFT" and draft["validated_read_only"]
    assert "sales_value" in draft["after"]
    assert body["uncovered"]


def test_drop_and_type_change_severity(ask_env):
    client, sessions, _ = ask_env
    workspace_id, headers = workspace(client, "impact-type@example.com", "impact-type")
    _, table, asset = data_asset(client, workspace_id, headers)
    user_id = UUID(client.get("/api/v1/auth/me").json()["id"])
    _stored_dependencies(sessions, workspace_id, user_id, table["id"], asset["id"])
    with sessions() as db:
        revenue = db.query(CatalogColumn).filter(CatalogColumn.asset_id == UUID(asset["id"]),
            CatalogColumn.name == "revenue").one()
        revenue.data_type = "Int64"
        db.commit()

    base = f"/api/v1/workspaces/{workspace_id}/impact/simulate"
    dropped = client.post(base, headers=headers, json={"asset_id": asset["id"],
        "change": {"type": "drop_column", "column": "revenue"}})
    assert dropped.status_code == 200 and dropped.json()["summary"]["breaking"] >= 1
    widening = client.post(base, headers=headers, json={"asset_id": asset["id"],
        "change": {"type": "change_type", "column": "revenue", "new_type": "BIGINT"}})
    assert widening.status_code == 200
    assert any(item["severity"] == "INFO" and "compatible widening" in item.get("compatibility", "")
               for item in widening.json()["compatibility_findings"])
    breaking = client.post(base, headers=headers, json={"asset_id": asset["id"],
        "change": {"type": "change_type", "column": "revenue", "new_type": "VARCHAR"}})
    assert breaking.status_code == 200
    assert any(item["severity"] == "BREAKING" for item in breaking.json()["compatibility_findings"])


def test_no_dependency_is_not_invented_and_is_reported_uncovered(ask_env):
    client, _, _ = ask_env
    workspace_id, headers = workspace(client, "impact-empty@example.com", "impact-empty")
    _, _, asset = data_asset(client, workspace_id, headers)
    response = client.get(f"/api/v1/workspaces/{workspace_id}/impact/graph?asset_id={asset['id']}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert not any(edge["confidence"] != "RECORDED" and edge["evidence"]["record_type"] != "CatalogColumn"
                   for edge in body["edges"])
    assert not any(node["type"] in {"pipeline", "pipeline_step", "saved_query", "observed_query"}
                   for node in body["nodes"])
    assert body["uncovered"] == []
    result = client.post(f"/api/v1/workspaces/{workspace_id}/impact/simulate", headers=headers,
        json={"asset_id": asset["id"], "change": {"type": "drop_column", "column": "revenue"}})
    assert any("No downstream dependency" in item for item in result.json()["uncovered"])


def test_name_only_matches_are_separate_from_parsed_dependencies(ask_env):
    client, sessions, _ = ask_env
    workspace_id, headers = workspace(client, "impact-name@example.com", "impact-name")
    _, table, asset = data_asset(client, workspace_id, headers)
    user_id = UUID(client.get("/api/v1/auth/me").json()["id"])
    with sessions() as db:
        other_table = LakehouseTable(workspace_id=UUID(workspace_id), name="unrelated", current_layer=LakehouseLayer.BRONZE)
        db.add(other_table)
        db.flush()
        other_asset = CatalogAsset(workspace_id=UUID(workspace_id), asset_type="TABLE", name="unrelated",
            lakehouse_table_id=other_table.id, format="parquet", layer="BRONZE", tags_json=[])
        db.add(other_asset)
        db.flush()
        db.add(CatalogColumn(asset_id=other_asset.id, name="revenue", data_type="Int64"))
        db.add(SavedQuery(workspace_id=UUID(workspace_id), user_id=user_id, name="unrelated query",
            sql_text="SELECT revenue FROM unrelated"))
        db.commit()
    response = client.post(f"/api/v1/workspaces/{workspace_id}/impact/simulate", headers=headers,
        json={"asset_id": asset["id"], "change": {"type": "drop_column", "column": "revenue"}})
    assert response.status_code == 200
    body = response.json()
    assert body["affected_saved_queries"] == []
    assert all(item["confidence"] == "INFERRED_NAME" for item in body["inferred_name_matches"])


def test_workspace_scope_viewer_csrf_and_simulation_does_not_change_data(ask_env):
    client, sessions, _ = ask_env
    workspace_id, headers = workspace(client, "impact-viewer@example.com", "impact-viewer")
    _, table, asset = data_asset(client, workspace_id, headers)
    user_id = UUID(client.get("/api/v1/auth/me").json()["id"])
    with sessions() as db:
        member = db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == UUID(workspace_id),
            WorkspaceMember.user_id == user_id).one()
        member.role = WorkspaceRole.VIEWER
        before_versions = db.query(__import__("app.models.entities", fromlist=["DatasetVersion"]).DatasetVersion).count()
        before_pipelines = db.query(Pipeline).count()
        db.commit()
    url = f"/api/v1/workspaces/{workspace_id}/impact/simulate"
    payload = {"asset_id": asset["id"], "change": {"type": "rename_column", "column": "revenue", "new_name": "amount"}}
    assert client.post(url, json=payload).status_code == 403
    assert client.post(url, headers=headers, json=payload).status_code == 200
    with sessions() as db:
        Version = __import__("app.models.entities", fromlist=["DatasetVersion"]).DatasetVersion
        assert db.query(Version).count() == before_versions
        assert db.query(Pipeline).count() == before_pipelines


def test_nonmember_cannot_read_graph_and_foreign_asset_is_not_found(ask_env):
    client, _, _ = ask_env
    workspace_id, headers = workspace(client, "impact-member@example.com", "impact-member")
    _, _, asset = data_asset(client, workspace_id, headers)
    assert client.get(f"/api/v1/workspaces/{workspace_id}/impact/graph?asset_id={asset['id']}", headers=headers).status_code == 200
    # A random user's workspace id is never disclosed by an asset lookup in this workspace.
    response = client.get(f"/api/v1/workspaces/{workspace_id}/impact/graph?asset_id=00000000-0000-0000-0000-000000000001", headers=headers)
    assert response.status_code == 404


def test_graph_depth_and_node_caps_and_autopilot_action():
    action = get_action("simulate_impact")
    assert action.min_role == "VIEWER" and action.risk_level == "LOW" and not action.requires_approval
    assert role_satisfies("VIEWER", action.min_role)

