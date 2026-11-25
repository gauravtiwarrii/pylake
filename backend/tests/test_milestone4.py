import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.v1.datasets as dataset_api
import app.api.v1.lakehouse as lakehouse_api
from app.core.db import Base, get_db
from app.main import app
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
    temporary = tempfile.TemporaryDirectory(prefix="pylake-m4-")
    storage = LocalFileStorage(temporary.name)
    monkeypatch.setattr(dataset_api, "get_storage", lambda: storage)
    monkeypatch.setattr(lakehouse_api, "get_storage", lambda: storage)

    with TestClient(app) as client:
        yield client, storage
    app.dependency_overrides.clear()
    temporary.cleanup()
    Base.metadata.drop_all(bind=engine)


def login_owner(client: TestClient, email: str, slug: str = "lakehouse"):
    client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "a-secure-password",
        "full_name": "Lakehouse User",
    })
    client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "a-secure-password",
    })
    headers = {"X-CSRF-Token": client.cookies["pylake_csrf"]}
    response = client.post("/api/v1/workspaces", json={"name": "Lakehouse", "slug": slug}, headers=headers)
    assert response.status_code == 201
    return response.json()["id"], headers


def upload_csv(client: TestClient, workspace_id: str, headers: dict[str, str]):
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/datasets/upload",
        files={"file": ("customers.csv", b"id,name,score\n1,Ada,10\n2,Lin,20\n2,Lin,20\n", "text/csv")},
        data={"name": "customers"},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


def test_bronze_version_csv_promotion_quality_and_usage(environment):
    client, storage = environment
    workspace_id, headers = login_owner(client, "bronze4@example.com")
    dataset = upload_csv(client, workspace_id, headers)

    tables = client.get(f"/api/v1/workspaces/{workspace_id}/lakehouse/tables", headers=headers)
    assert tables.status_code == 200
    assert len(tables.json()) == 1
    table = tables.json()[0]
    assert table["current_layer"] == "BRONZE"

    versions = client.get(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables/{table['id']}/versions",
        headers=headers,
    )
    assert versions.status_code == 200
    assert len(versions.json()) == 1
    assert versions.json()[0]["layer"] == "BRONZE"
    assert versions.json()[0]["row_count"] == 3

    promoted = client.post(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables/{table['id']}/promote",
        json={"target_layer": "SILVER", "partition_columns": ["name"]},
        headers=headers,
    )
    assert promoted.status_code == 200
    silver = promoted.json()
    assert silver["layer"] == "SILVER"
    assert silver["file_format"] == "parquet"
    assert silver["schema_json"]["partition_columns"] == ["name"]

    quality = client.get(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables/{table['id']}/quality",
        headers=headers,
    )
    assert quality.status_code == 200
    assert quality.json()["row_count"] == 3
    assert quality.json()["duplicate_rows"] == 1

    usage = client.get(f"/api/v1/workspaces/{workspace_id}/lakehouse/storage/usage", headers=headers)
    assert usage.status_code == 200
    assert usage.json()["total_objects"] >= 2
    assert usage.json()["total_bytes"] > 0


def test_transform_creates_version_and_preserves_source(environment):
    client, _ = environment
    workspace_id, headers = login_owner(client, "transform4@example.com", "transform")
    upload_csv(client, workspace_id, headers)
    table = client.get(f"/api/v1/workspaces/{workspace_id}/lakehouse/tables", headers=headers).json()[0]

    bronze = client.get(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables/{table['id']}/versions",
        headers=headers,
    ).json()[0]

    transformed = client.post(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables/{table['id']}/transform",
        json={
            "source_version_id": bronze["id"],
            "transformation_type": "deduplicate",
            "configuration": {},
            "target_layer": "SILVER",
        },
        headers=headers,
    )
    assert transformed.status_code == 200
    assert transformed.json()["row_count"] == 2
    assert transformed.json()["version_number"] == 2

    history = client.get(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables/{table['id']}/versions",
        headers=headers,
    )
    assert history.status_code == 200
    assert [item["version_number"] for item in history.json()] == [1, 2]

    bronze_again = client.get(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables/{table['id']}/versions/{bronze['id']}",
        headers=headers,
    )
    assert bronze_again.status_code == 200
    assert bronze_again.json()["row_count"] == 3


def test_rollback_by_source_version_and_viewer_permissions(environment):
    client, _ = environment
    workspace_id, owner_headers = login_owner(client, "owner4@example.com", "rbac")
    upload_csv(client, workspace_id, owner_headers)
    table = client.get(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables",
        headers=owner_headers,
    ).json()[0]

    silver = client.post(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables/{table['id']}/promote",
        json={"target_layer": "SILVER"},
        headers=owner_headers,
    )
    assert silver.status_code == 200
    bronze_id = client.get(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables/{table['id']}/versions",
        headers=owner_headers,
    ).json()[0]["id"]

    rollback = client.post(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables/{table['id']}/promote",
        json={"target_layer": "GOLD", "source_version_id": bronze_id},
        headers=owner_headers,
    )
    assert rollback.status_code == 200
    assert rollback.json()["version_number"] == 3

    client.post("/api/v1/auth/register", json={
        "email": "viewer4@example.com",
        "password": "a-secure-password",
        "full_name": "Viewer",
    })
    client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        json={"email": "viewer4@example.com", "role": "VIEWER"},
        headers=owner_headers,
    )
    client.post("/api/v1/auth/logout", headers=owner_headers)
    client.post("/api/v1/auth/login", json={"email": "viewer4@example.com", "password": "a-secure-password"})
    viewer_headers = {"X-CSRF-Token": client.cookies["pylake_csrf"]}

    assert client.get(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables",
        headers=viewer_headers,
    ).status_code == 200
    assert client.post(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables/{table['id']}/transform",
        json={"transformation_type": "deduplicate", "configuration": {}},
        headers=viewer_headers,
    ).status_code == 403


def test_cross_workspace_lakehouse_access(environment):
    client, _ = environment
    workspace_id, headers = login_owner(client, "isolated4@example.com", "isolated")
    upload_csv(client, workspace_id, headers)
    table_id = client.get(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables",
        headers=headers,
    ).json()[0]["id"]

    client.post("/api/v1/auth/logout", headers=headers)
    other_id, other_headers = login_owner(client, "other4@example.com", "other")
    assert client.get(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables/{table_id}",
        headers=other_headers,
    ).status_code == 404
