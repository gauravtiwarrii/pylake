import io
import tempfile
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.v1.datasets as dataset_api
import app.api.v1.lakehouse as lakehouse_api
import app.api.v1.catalog as catalog_api
import app.api.v1.sql as sql_api
import app.services.pipeline_engine as pipeline_engine
from app.core.db import Base, get_db
from app.main import app
from app.models.entities import PipelineRun
from app.storage.local import LocalFileStorage


@pytest.fixture()
def environment(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_db():
        with TestingSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    temporary = tempfile.TemporaryDirectory(prefix="pylake-m8-")
    storage = LocalFileStorage(temporary.name)
    monkeypatch.setattr(dataset_api, "get_storage", lambda: storage)
    monkeypatch.setattr(lakehouse_api, "get_storage", lambda: storage)
    monkeypatch.setattr(catalog_api, "get_storage", lambda: storage)
    monkeypatch.setattr(sql_api, "get_storage", lambda: storage)
    monkeypatch.setattr(pipeline_engine, "get_storage", lambda: storage)
    monkeypatch.setattr(pipeline_engine, "SessionLocal", TestingSession)

    with TestClient(app) as client:
        yield client, storage
    app.dependency_overrides.clear()
    temporary.cleanup()
    Base.metadata.drop_all(bind=engine)


def login_workspace(client: TestClient, email: str, slug: str):
    client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "a-secure-password",
        "full_name": "Catalog User",
    })
    client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "a-secure-password",
    })
    headers = {"X-CSRF-Token": client.cookies["pylake_csrf"]}
    workspace = client.post("/api/v1/workspaces", json={"name": "Catalog", "slug": slug}, headers=headers)
    assert workspace.status_code == 201
    return workspace.json()["id"], headers


def upload_and_promote(client: TestClient, workspace_id: str, headers: dict[str, str]):
    upload = client.post(
        f"/api/v1/workspaces/{workspace_id}/datasets/upload",
        files={"file": ("customers.csv", b"id,name,score\n1,Ada,10\n2,Lin,20\n3,Sam,20\n", "text/csv")},
        data={"name": "customers"},
        headers=headers,
    )
    assert upload.status_code == 201
    table = client.get(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables",
        headers=headers,
    ).json()[0]
    promoted = client.post(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables/{table['id']}/promote",
        json={"target_layer": "SILVER"},
        headers=headers,
    )
    assert promoted.status_code == 200
    return table


def test_catalog_discovery_profile_documentation_and_lineage(environment):
    client, _ = environment
    workspace_id, headers = login_workspace(client, "catalog8@example.com", "catalog-8")
    table = upload_and_promote(client, workspace_id, headers)

    catalog = client.get(
        f"/api/v1/workspaces/{workspace_id}/catalog",
        headers=headers,
    )
    assert catalog.status_code == 200
    items = catalog.json()["items"]
    assert len(items) >= 2
    names = {item["name"] for item in items}
    assert "customers" in names

    table_asset = next(item for item in items if item["asset_type"] == "TABLE")
    updated = client.patch(
        f"/api/v1/workspaces/{workspace_id}/catalog/{table_asset['id']}",
        json={"description": "Customer analytics table", "tags": ["customer", "analytics"]},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "Customer analytics table"

    schema = client.get(
        f"/api/v1/workspaces/{workspace_id}/catalog/{table_asset['id']}/schema",
        headers=headers,
    )
    assert schema.status_code == 200
    assert len(schema.json()["columns"]) == 3

    column_name = schema.json()["columns"][0]["name"]
    documented = client.patch(
        f"/api/v1/workspaces/{workspace_id}/catalog/{table_asset['id']}/columns/{column_name}",
        json={"description": "Customer identifier", "business_name": "Customer ID", "glossary_term": "customer_id"},
        headers=headers,
    )
    assert documented.status_code == 200
    assert documented.json()["business_name"] == "Customer ID"

    profile = client.get(
        f"/api/v1/workspaces/{workspace_id}/catalog/{table_asset['id']}/profile",
        headers=headers,
    )
    assert profile.status_code == 200
    assert profile.json()["row_count"] == 3
    assert profile.json()["column_count"] == 3

    lineage = client.get(
        f"/api/v1/workspaces/{workspace_id}/catalog/{table_asset['id']}/lineage?direction=both",
        headers=headers,
    )
    assert lineage.status_code == 200
    assert len(lineage.json()["nodes"]) >= 1
    assert len(lineage.json()["edges"]) >= 1

    impact = client.get(
        f"/api/v1/workspaces/{workspace_id}/catalog/{table_asset['id']}/impact",
        headers=headers,
    )
    assert impact.status_code == 200
    assert impact.json()["coverage"] == "RECORDED_DEPENDENCIES"


def test_catalog_search_filter_pagination_and_cross_workspace(environment):
    client, _ = environment
    workspace_id, headers = login_workspace(client, "catalog-owner8@example.com", "catalog-owner")
    upload_and_promote(client, workspace_id, headers)

    search = client.get(
        f"/api/v1/workspaces/{workspace_id}/catalog?search=customer&layer=SILVER&page=1&page_size=10",
        headers=headers,
    )
    assert search.status_code == 200
    assert search.json()["total"] >= 1

    client.post("/api/v1/auth/logout", headers=headers)
    other_id, other_headers = login_workspace(client, "catalog-other8@example.com", "catalog-other")
    catalog = client.get(
        f"/api/v1/workspaces/{workspace_id}/catalog",
        headers=other_headers,
    )
    assert catalog.status_code == 404


def test_upload_pipeline_worker_gold_materialization_and_sql(environment):
    client, _ = environment
    workspace_id, headers = login_workspace(client, "pipeline-e2e@example.com", "pipeline-e2e")
    upload = client.post(
        f"/api/v1/workspaces/{workspace_id}/datasets/upload",
        files={"file": ("customers.csv", b"id,name,score\n1,Ada,10\n2,Lin,20\n", "text/csv")},
        data={"name": "customers"},
        headers=headers,
    )
    assert upload.status_code == 201
    dataset_id = upload.json()["id"]

    tables = client.get(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables",
        headers=headers,
    ).json()
    table = next(item for item in tables if item["name"] == "customers")
    promoted = client.post(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables/{table['id']}/promote",
        json={"target_layer": "SILVER"},
        headers=headers,
    )
    assert promoted.status_code == 200

    pipeline = client.post(
        f"/api/v1/workspaces/{workspace_id}/pipelines",
        json={
            "name": "Customer Gold materialization",
            "steps": [
                {
                    "step_key": "source",
                    "name": "Validate source",
                    "step_type": "SOURCE_DATASET",
                    "configuration": {"dataset_id": dataset_id},
                    "execution_order": 1,
                },
                {
                    "step_key": "materialize",
                    "name": "Create Gold version",
                    "step_type": "MATERIALIZE",
                    "configuration": {"table_name": "customers", "target_layer": "GOLD"},
                    "dependencies": ["source"],
                    "execution_order": 2,
                },
            ],
        },
        headers=headers,
    )
    assert pipeline.status_code == 201, pipeline.text
    pipeline_id = pipeline.json()["id"]

    accepted = client.post(
        f"/api/v1/workspaces/{workspace_id}/pipelines/{pipeline_id}/runs",
        headers=headers,
    )
    assert accepted.status_code == 202
    run_id = accepted.json()["id"]
    with pipeline_engine.SessionLocal() as db:
        db.get(PipelineRun, UUID(run_id)).max_retries = 0
        db.commit()
    claimed = pipeline_engine.claim_next_job("integration-test-worker")
    assert str(claimed.id) == run_id
    pipeline_engine.execute_pipeline_run(claimed.id)

    run = client.get(
        f"/api/v1/workspaces/{workspace_id}/pipelines/runs/{run_id}",
        headers=headers,
    )
    logs = client.get(
        f"/api/v1/workspaces/{workspace_id}/pipelines/runs/{run_id}/logs",
        headers=headers,
    )
    assert logs.status_code == 200
    assert run.status_code == 200
    step_results = [(item["status"], item.get("error_message")) for item in logs.json()["steps"]]
    assert run.json()["status"] == "SUCCEEDED", step_results
    assert all(step_run["status"] == "SUCCEEDED" for step_run in logs.json()["steps"])

    result = client.post(
        f"/api/v1/workspaces/{workspace_id}/sql/execute",
        json={"sql": "SELECT COUNT(*) AS row_count FROM customers"},
        headers=headers,
    )
    assert result.status_code == 200, result.text
    assert result.json()["rows"][0]["row_count"] == 2
