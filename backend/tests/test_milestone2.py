import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db
from app.main import app


@pytest.fixture()
def client():
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
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def register(client: TestClient, email: str, name: str = "Test User"):
    return client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "a-secure-password",
        "full_name": name,
    })


def login(client: TestClient, email: str):
    return client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "a-secure-password",
    })


def csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("pylake_csrf")
    return {"X-CSRF-Token": token} if token else {}


def test_registration_duplicate_and_login_logout(client: TestClient):
    created = register(client, "owner@example.com")
    assert created.status_code == 201
    assert "hashed_password" not in created.json()

    duplicate = register(client, "owner@example.com")
    assert duplicate.status_code == 409

    assert login(client, "missing@example.com").status_code == 401
    assert login(client, "owner@example.com").status_code == 200
    assert client.cookies.get("pylake_session")
    assert client.cookies.get("pylake_csrf")

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "owner@example.com"

    logout = client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    assert logout.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_cross_user_access_and_workspace_ownership(client: TestClient):
    register(client, "owner@example.com")
    assert login(client, "owner@example.com").status_code == 200
    headers = csrf_headers(client)

    created = client.post("/api/v1/workspaces", json={
        "name": "Analytics",
        "slug": "analytics",
        "description": "Production analytics",
    }, headers=headers)
    assert created.status_code == 201
    workspace_id = created.json()["id"]

    assert len(client.get("/api/v1/workspaces").json()) == 1
    assert client.get(f"/api/v1/workspaces/{workspace_id}", headers=headers).status_code == 200

    client.post("/api/v1/auth/logout", headers=headers)
    register(client, "other@example.com")
    login(client, "other@example.com")
    assert client.get(f"/api/v1/workspaces/{workspace_id}", headers=csrf_headers(client)).status_code == 404

    assert client.delete(f"/api/v1/workspaces/{workspace_id}", headers=csrf_headers(client)).status_code == 404


def test_viewer_editor_admin_permissions_and_owner_deletion(client: TestClient):
    register(client, "owner@example.com")
    login(client, "owner@example.com")
    owner_headers = csrf_headers(client)
    workspace = client.post("/api/v1/workspaces", json={"name": "Team", "slug": "team"}, headers=owner_headers)
    workspace_id = workspace.json()["id"]

    for email, role in [
        ("viewer@example.com", "VIEWER"),
        ("editor@example.com", "EDITOR"),
        ("admin@example.com", "ADMIN"),
    ]:
        register(client, email)

    for email, role in [
        ("viewer@example.com", "VIEWER"),
        ("editor@example.com", "EDITOR"),
        ("admin@example.com", "ADMIN"),
    ]:
        response = client.post(
            f"/api/v1/workspaces/{workspace_id}/members",
            json={"email": email, "role": role},
            headers=owner_headers,
        )
        assert response.status_code == 201

    client.post("/api/v1/auth/logout", headers=owner_headers)

    login(client, "viewer@example.com")
    viewer_headers = csrf_headers(client)
    assert client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        json={"name": "Changed"},
        headers=viewer_headers,
    ).status_code == 403
    client.post("/api/v1/auth/logout", headers=viewer_headers)

    login(client, "editor@example.com")
    editor_headers = csrf_headers(client)
    assert client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        json={"name": "Changed"},
        headers=editor_headers,
    ).status_code == 403
    client.post("/api/v1/auth/logout", headers=editor_headers)

    login(client, "admin@example.com")
    admin_headers = csrf_headers(client)
    assert client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        json={"name": "Admin change"},
        headers=admin_headers,
    ).status_code == 200
    client.post("/api/v1/auth/logout", headers=admin_headers)

    login(client, "owner@example.com")
    owner_headers = csrf_headers(client)
    assert client.delete(f"/api/v1/workspaces/{workspace_id}", headers=owner_headers).status_code == 204


def test_unauthenticated_access(client: TestClient):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/workspaces").status_code == 401
    assert client.post("/api/v1/workspaces", json={"name": "X", "slug": "x"}).status_code == 401


def test_csrf_rejects_missing_or_invalid_token(client: TestClient):
    register(client, "csrf@example.com")
    login(client, "csrf@example.com")

    missing = client.post("/api/v1/workspaces", json={"name": "X", "slug": "x"})
    assert missing.status_code == 403

    invalid = client.post(
        "/api/v1/workspaces",
        json={"name": "X", "slug": "x"},
        headers={"X-CSRF-Token": "invalid-token"},
    )
    assert invalid.status_code == 403
