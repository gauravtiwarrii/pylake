import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.v1.datasets as dataset_api
import app.api.v1.lakehouse as lakehouse_api
import app.api.v1.sql as sql_api
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
    temporary = tempfile.TemporaryDirectory(prefix="pylake-m5-")
    storage = LocalFileStorage(temporary.name)
    monkeypatch.setattr(dataset_api, "get_storage", lambda: storage)
    monkeypatch.setattr(lakehouse_api, "get_storage", lambda: storage)
    monkeypatch.setattr(sql_api, "get_storage", lambda: storage)

    with TestClient(app) as client:
        yield client, storage
    app.dependency_overrides.clear()
    temporary.cleanup()
    Base.metadata.drop_all(bind=engine)


def login_workspace(client: TestClient, email: str, slug: str):
    client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "a-secure-password",
        "full_name": "SQL User",
    })
    client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "a-secure-password",
    })
    headers = {"X-CSRF-Token": client.cookies["pylake_csrf"]}
    workspace = client.post("/api/v1/workspaces", json={"name": "SQL", "slug": slug}, headers=headers)
    assert workspace.status_code == 201
    return workspace.json()["id"], headers


def upload_and_promote(client: TestClient, workspace_id: str, headers: dict[str, str], filename: str, name: str, csv: bytes):
    upload = client.post(
        f"/api/v1/workspaces/{workspace_id}/datasets/upload",
        files={"file": (filename, csv, "text/csv")},
        data={"name": name},
        headers=headers,
    )
    assert upload.status_code == 201
    tables = client.get(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables",
        headers=headers,
    ).json()
    table = next(item for item in tables if item["name"] == name)
    promoted = client.post(
        f"/api/v1/workspaces/{workspace_id}/lakehouse/tables/{table['id']}/promote",
        json={"target_layer": "SILVER"},
        headers=headers,
    )
    assert promoted.status_code == 200
    return table


def test_select_where_group_order_aggregation_cte_and_history(environment):
    client, _ = environment
    workspace_id, headers = login_workspace(client, "sql5@example.com", "sql-select")
    upload_and_promote(
        client,
        workspace_id,
        headers,
        "customers.csv",
        "customers",
        b"id,name,score\n1,Ada,10\n2,Lin,20\n3,Sam,20\n",
    )

    result = client.post(
        f"/api/v1/workspaces/{workspace_id}/sql/execute",
        json={"sql": "SELECT score, COUNT(*) AS total FROM customers WHERE score >= 20 GROUP BY score ORDER BY score", "query_name": "scores"},
        headers=headers,
    )
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "SUCCESS"
    assert result.json()["returned_rows"] == 1
    assert result.json()["rows"][0]["total"] == 2
    assert result.json()["duration_ms"] >= 0

    cte = client.post(
        f"/api/v1/workspaces/{workspace_id}/sql/execute",
        json={"sql": "WITH ranked AS (SELECT name, score FROM customers) SELECT name FROM ranked WHERE score >= 20"},
        headers=headers,
    )
    assert cte.status_code == 200
    assert cte.json()["returned_rows"] == 2

    history = client.get(f"/api/v1/workspaces/{workspace_id}/sql/history", headers=headers)
    assert history.status_code == 200
    assert len(history.json()) == 2


def test_join_window_subquery_and_catalog(environment):
    client, _ = environment
    workspace_id, headers = login_workspace(client, "join5@example.com", "sql-join")
    upload_and_promote(
        client,
        workspace_id,
        headers,
        "customers.csv",
        "customers",
        b"id,name\n1,Ada\n2,Lin\n",
    )
    upload_and_promote(
        client,
        workspace_id,
        headers,
        "orders.csv",
        "orders",
        b"id,customer_id,total\n10,1,25\n11,1,50\n12,2,30\n",
    )

    catalog = client.get(f"/api/v1/workspaces/{workspace_id}/sql/catalog", headers=headers)
    assert catalog.status_code == 200
    names = {item["name"] for item in catalog.json()["items"]}
    assert {"customers", "orders"} <= names

    result = client.post(
        f"/api/v1/workspaces/{workspace_id}/sql/execute",
        json={"sql": "SELECT c.name, o.total, SUM(o.total) OVER (PARTITION BY c.name) AS running_total FROM customers c JOIN orders o ON c.id = o.customer_id ORDER BY c.name"},
        headers=headers,
    )
    assert result.status_code == 200, result.text
    assert result.json()["returned_rows"] == 3

    subquery = client.post(
        f"/api/v1/workspaces/{workspace_id}/sql/execute",
        json={"sql": "SELECT name FROM customers WHERE id IN (SELECT customer_id FROM orders)"},
        headers=headers,
    )
    assert subquery.status_code == 200
    assert subquery.json()["returned_rows"] == 2


@pytest.mark.parametrize("sql", [
    "INSERT INTO customers VALUES (1)",
    "UPDATE customers SET name = 'X'",
    "DELETE FROM customers",
    "DROP TABLE customers",
    "ALTER TABLE customers ADD COLUMN x INTEGER",
    "COPY customers TO 'output.csv'",
    "ATTACH 'database.db' AS db",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM customers; SELECT * FROM customers",
])
def test_read_only_rejections(environment, sql):
    client, _ = environment
    workspace_id, headers = login_workspace(client, f"secure5-{abs(hash(sql))}@example.com", f"secure-{abs(hash(sql))}")
    upload_and_promote(
        client,
        workspace_id,
        headers,
        "customers.csv",
        "customers",
        b"id,name\n1,Ada\n",
    )
    result = client.post(
        f"/api/v1/workspaces/{workspace_id}/sql/execute",
        json={"sql": sql},
        headers=headers,
    )
    assert result.status_code == 400


def test_missing_table_saved_query_history_and_cross_workspace(environment):
    client, _ = environment
    workspace_id, headers = login_workspace(client, "saved5@example.com", "saved-sql")

    missing = client.post(
        f"/api/v1/workspaces/{workspace_id}/sql/execute",
        json={"sql": "SELECT * FROM missing_table"},
        headers=headers,
    )
    assert missing.status_code == 400

    saved = client.post(
        f"/api/v1/workspaces/{workspace_id}/sql/saved",
        json={"name": "All customers", "description": "Customer query", "sql_text": "SELECT 1 AS value"},
        headers=headers,
    )
    assert saved.status_code == 201
    saved_id = saved.json()["id"]

    reopened = client.get(f"/api/v1/workspaces/{workspace_id}/sql/saved", headers=headers)
    assert reopened.status_code == 200
    assert reopened.json()[0]["name"] == "All customers"

    updated = client.patch(
        f"/api/v1/workspaces/{workspace_id}/sql/saved/{saved_id}",
        json={"name": "Customer value", "sql_text": "SELECT 2 AS value"},
        headers=headers,
    )
    assert updated.status_code == 200

    deleted = client.delete(
        f"/api/v1/workspaces/{workspace_id}/sql/saved/{saved_id}",
        headers=headers,
    )
    assert deleted.status_code == 204

    client.post("/api/v1/auth/logout", headers=headers)
    other_id, other_headers = login_workspace(client, "other5@example.com", "other-sql")
    catalog = client.get(
        f"/api/v1/workspaces/{workspace_id}/sql/catalog",
        headers=other_headers,
    )
    assert catalog.status_code == 404
