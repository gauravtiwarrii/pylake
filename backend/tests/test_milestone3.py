import io
import tempfile
from pathlib import Path

import openpyxl
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.v1.datasets as dataset_api
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
    temporary = tempfile.TemporaryDirectory(prefix="pylake-tests-")
    storage = LocalFileStorage(temporary.name)
    monkeypatch.setattr(dataset_api, "get_storage", lambda: storage)

    with TestClient(app) as client:
        yield client, storage
    app.dependency_overrides.clear()
    temporary.cleanup()
    Base.metadata.drop_all(bind=engine)


def register_login(client: TestClient, email: str, role: str = "OWNER"):
    client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "a-secure-password",
        "full_name": "Dataset User",
    })
    client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "a-secure-password",
    })
    return {"X-CSRF-Token": client.cookies["pylake_csrf"]}


def create_workspace(client: TestClient, headers: dict[str, str], slug: str = "ingestion"):
    response = client.post(
        "/api/v1/workspaces",
        json={"name": "Ingestion", "slug": slug},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_csv_upload_preview_download_list_and_delete(environment):
    client, storage = environment
    headers = register_login(client, "csv@example.com")
    workspace_id = create_workspace(client, headers)

    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/datasets/upload",
        files={"file": ("sales.csv", b"id,name,amount\n1,Ada,12.5\n2,Lin,9.0\n", "text/csv")},
        data={"name": "Sales"},
        headers=headers,
    )
    assert response.status_code == 201
    dataset = response.json()
    assert dataset["ingestion_status"] == "COMPLETED"
    assert dataset["row_count"] == 2
    assert dataset["column_count"] == 3

    preview = client.get(
        f"/api/v1/workspaces/{workspace_id}/datasets/{dataset['id']}/preview",
        headers=headers,
    )
    assert preview.status_code == 200
    assert preview.json()["returned_rows"] == 2
    assert preview.json()["rows"][0]["name"] == "Ada"

    listing = client.get(f"/api/v1/workspaces/{workspace_id}/datasets?page=1&page_size=10", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["name"] == "Sales"

    download = client.get(
        f"/api/v1/workspaces/{workspace_id}/datasets/{dataset['id']}/download",
        headers=headers,
    )
    assert download.status_code == 200
    assert b"Ada" in download.content

    deleted = client.delete(
        f"/api/v1/workspaces/{workspace_id}/datasets/{dataset['id']}",
        headers=headers,
    )
    assert deleted.status_code == 204
    listing_after = client.get(
        f"/api/v1/workspaces/{workspace_id}/datasets",
        headers=headers,
    )
    assert listing_after.json()["total"] == 0


@pytest.mark.parametrize("suffix,content_type,body", [
    ("json", "application/json", b'[{"id":1,"name":"Ada"},{"id":2,"name":"Lin"}]'),
    ("csv", "text/csv", b"id,name\n1,Ada\n2,Lin\n"),
])
def test_json_and_csv_formats(environment, suffix, content_type, body):
    client, _ = environment
    headers = register_login(client, f"{suffix}@example.com")
    workspace_id = create_workspace(client, headers, slug=f"{suffix}-workspace")
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/datasets/upload",
        files={"file": (f"data.{suffix}", body, content_type)},
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["ingestion_status"] == "COMPLETED"
    assert response.json()["row_count"] == 2


def test_parquet_upload(environment):
    client, _ = environment
    headers = register_login(client, "parquet@example.com")
    workspace_id = create_workspace(client, headers, slug="parquet-workspace")
    table = pa.table({"id": [1, 2], "name": ["Ada", "Lin"]})
    buffer = io.BytesIO()
    pq.write_table(table, buffer)

    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/datasets/upload",
        files={"file": ("data.parquet", buffer.getvalue(), "application/octet-stream")},
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["file_format"] == "parquet"
    assert response.json()["row_count"] == 2


def test_xlsx_upload(environment):
    client, _ = environment
    headers = register_login(client, "xlsx@example.com")
    workspace_id = create_workspace(client, headers, slug="xlsx-workspace")
    buffer = io.BytesIO()
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["id", "name"])
    sheet.append([1, "Ada"])
    sheet.append([2, "Lin"])
    workbook.save(buffer)

    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/datasets/upload",
        files={"file": ("data.xlsx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["file_format"] == "xlsx"
    assert response.json()["row_count"] == 2
    assert "sheets" in response.json()["schema_json"]


def test_upload_rejections(environment, monkeypatch):
    client, _ = environment
    headers = register_login(client, "validation@example.com")
    workspace_id = create_workspace(client, headers)

    unsupported = client.post(
        f"/api/v1/workspaces/{workspace_id}/datasets/upload",
        files={"file": ("data.txt", b"hello", "text/plain")},
        headers=headers,
    )
    assert unsupported.status_code == 400

    empty = client.post(
        f"/api/v1/workspaces/{workspace_id}/datasets/upload",
        files={"file": ("data.csv", b"", "text/csv")},
        headers=headers,
    )
    assert empty.status_code == 400

    corrupt = client.post(
        f"/api/v1/workspaces/{workspace_id}/datasets/upload",
        files={"file": ("data.parquet", b"PAR1-not-a-parquet", "application/octet-stream")},
        headers=headers,
    )
    assert corrupt.status_code == 400

    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "max_upload_size_bytes", 4)
    oversized = client.post(
        f"/api/v1/workspaces/{workspace_id}/datasets/upload",
        files={"file": ("data.csv", b"1,2,3", "text/csv")},
        headers=headers,
    )
    assert oversized.status_code == 413


def test_viewer_rejection_cross_workspace_and_failed_state(environment):
    client, _ = environment
    owner_headers = register_login(client, "owner3@example.com")
    workspace_id = create_workspace(client, owner_headers)

    register_response = client.post("/api/v1/auth/register", json={
        "email": "viewer3@example.com",
        "password": "a-secure-password",
        "full_name": "Viewer",
    })
    assert register_response.status_code == 201

    member = client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        json={"email": "viewer3@example.com", "role": "VIEWER"},
        headers=owner_headers,
    )
    assert member.status_code == 201

    client.post("/api/v1/auth/logout", headers=owner_headers)
    client.post("/api/v1/auth/login", json={"email": "viewer3@example.com", "password": "a-secure-password"})
    viewer_headers = {"X-CSRF-Token": client.cookies["pylake_csrf"]}
    upload = client.post(
        f"/api/v1/workspaces/{workspace_id}/datasets/upload",
        files={"file": ("data.csv", b"id\n1\n", "text/csv")},
        headers=viewer_headers,
    )
    assert upload.status_code == 403

    client.post("/api/v1/auth/logout", headers=viewer_headers)
    register_login(client, "other3@example.com")
    other_headers = {"X-CSRF-Token": client.cookies["pylake_csrf"]}
    assert client.get(
        f"/api/v1/workspaces/{workspace_id}/datasets",
        headers=other_headers,
    ).status_code == 404
