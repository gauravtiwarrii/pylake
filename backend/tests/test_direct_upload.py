"""Tests for the direct-to-storage upload flow (presigned PUT URLs).

All storage operations are monkeypatched — no network required.
"""
import io
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.v1.datasets as dataset_api
from app.core.config import get_settings
from app.core.db import Base, get_db
from app.main import app
from app.models.entities import DatasetStatus
from app.storage.local import LocalFileStorage

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SMALL_CSV = b"id,name,amount\n1,Ada,12.5\n2,Lin,9.0\n"
_PASSWORD = "a-secure-password"  # 16 chars — satisfies min_length=12


class FakeStorage:
    """In-memory storage that also records calls to generate_presigned_put / head."""

    def __init__(self):
        self._objects: dict[str, bytes] = {}
        self.presigned_calls: list[dict] = []

    def upload(self, key: str, source, content_type: str) -> None:
        self._objects[key] = source.read()

    def download(self, key: str):
        if key not in self._objects:
            raise FileNotFoundError(key)
        return io.BytesIO(self._objects[key])

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self._objects

    def get_metadata(self, key: str) -> dict:
        if key not in self._objects:
            raise FileNotFoundError(key)
        return {"size": len(self._objects[key]), "content_type": "application/octet-stream"}

    def head(self, key: str) -> dict:
        return self.get_metadata(key)

    def generate_presigned_put(self, key: str, content_type: str, expires: int) -> str:
        self.presigned_calls.append(
            {"key": key, "content_type": content_type, "expires": expires}
        )
        return f"https://fake-storage.example.com/{key}?presigned=1"

    def simulate_put(self, key: str, body: bytes) -> None:
        """Simulate the client having PUT the file to the presigned URL."""
        self._objects[key] = body


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

    storage = FakeStorage()
    monkeypatch.setattr(dataset_api, "get_storage", lambda: storage)

    # Enable direct upload for most tests.
    settings = get_settings()
    monkeypatch.setattr(settings, "direct_upload_enabled", True)
    monkeypatch.setattr(settings, "max_upload_size_bytes", 100 * 1024 * 1024)

    with TestClient(app) as client:
        yield client, storage, settings

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def _register_login(client: TestClient, email: str) -> dict[str, str]:
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "full_name": "Test User"},
    )
    assert r.status_code == 201, f"register failed: {r.text}"
    client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    return {"X-CSRF-Token": client.cookies["pylake_csrf"]}


def _create_workspace(client: TestClient, headers: dict, slug: str = "test-ws") -> str:
    r = client.post(
        "/api/v1/workspaces",
        json={"name": "Test WS", "slug": slug},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _add_member(client: TestClient, owner_headers: dict, workspace_id: str, email: str, role: str) -> None:
    client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        json={"email": email, "role": role},
        headers=owner_headers,
    )


# ---------------------------------------------------------------------------
# upload-config
# ---------------------------------------------------------------------------

def test_upload_config_direct_enabled(environment):
    client, _, settings = environment
    headers = _register_login(client, "cfg-enabled@example.com")
    ws = _create_workspace(client, headers, "cfg-enabled")

    r = client.get(f"/api/v1/workspaces/{ws}/datasets/upload-config", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["direct_upload"] is True
    assert body["max_upload_size_bytes"] == settings.max_upload_size_bytes


def test_upload_config_direct_disabled(environment, monkeypatch):
    client, _, settings = environment
    monkeypatch.setattr(settings, "direct_upload_enabled", False)
    headers = _register_login(client, "cfg-disabled@example.com")
    ws = _create_workspace(client, headers, "cfg-disabled")

    r = client.get(f"/api/v1/workspaces/{ws}/datasets/upload-config", headers=headers)
    assert r.status_code == 200
    assert r.json()["direct_upload"] is False


def test_upload_config_requires_auth(environment):
    client, _, _ = environment
    # Auth check fires before workspace check.
    r = client.get("/api/v1/workspaces/00000000-0000-0000-0000-000000000001/datasets/upload-config")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# upload-url
# ---------------------------------------------------------------------------

def test_upload_url_happy_path(environment):
    client, storage, settings = environment
    headers = _register_login(client, "upurl-ok@example.com")
    ws = _create_workspace(client, headers, "upurl-ok")

    r = client.post(
        f"/api/v1/workspaces/{ws}/datasets/upload-url",
        json={"filename": "sales.csv", "size_bytes": len(SMALL_CSV), "content_type": "text/csv"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["method"] == "PUT"
    assert "upload_url" in body
    assert "dataset_id" in body
    assert body["expires_in"] == settings.direct_upload_url_ttl_seconds

    # Key must be workspace-scoped and server-generated (not user-supplied).
    assert len(storage.presigned_calls) == 1
    key = storage.presigned_calls[0]["key"]
    assert key.startswith(f"workspaces/{ws}/")
    # Must contain the filename at the leaf.
    assert "sales.csv" in key
    # Must include a UUID segment (server-generated).
    parts = key.split("/")
    try:
        UUID(parts[-2])  # the uuid4 segment
    except (ValueError, IndexError):
        pytest.fail(f"Key does not contain a UUID segment: {key}")


def test_upload_url_requires_auth(environment):
    client, _, _ = environment
    r = client.post(
        "/api/v1/workspaces/00000000-0000-0000-0000-000000000001/datasets/upload-url",
        json={"filename": "x.csv", "size_bytes": 100, "content_type": "text/csv"},
    )
    assert r.status_code == 401


def test_upload_url_requires_csrf(environment):
    client, _, _ = environment
    headers = _register_login(client, "upurl-csrf@example.com")
    ws = _create_workspace(client, headers, "upurl-csrf")
    # Send without the CSRF header.
    r = client.post(
        f"/api/v1/workspaces/{ws}/datasets/upload-url",
        json={"filename": "x.csv", "size_bytes": 100, "content_type": "text/csv"},
    )
    assert r.status_code == 403


def test_upload_url_requires_editor_role(environment):
    client, _, _ = environment
    owner_headers = _register_login(client, "upurl-owner@example.com")
    ws = _create_workspace(client, owner_headers, "upurl-role")

    # Register viewer.
    client.post(
        "/api/v1/auth/register",
        json={"email": "upurl-viewer@example.com", "password": _PASSWORD, "full_name": "Viewer"},
    )
    _add_member(client, owner_headers, ws, "upurl-viewer@example.com", "VIEWER")

    client.post("/api/v1/auth/logout", headers=owner_headers)
    client.post("/api/v1/auth/login", json={"email": "upurl-viewer@example.com", "password": _PASSWORD})
    viewer_headers = {"X-CSRF-Token": client.cookies["pylake_csrf"]}

    r = client.post(
        f"/api/v1/workspaces/{ws}/datasets/upload-url",
        json={"filename": "x.csv", "size_bytes": 100, "content_type": "text/csv"},
        headers=viewer_headers,
    )
    assert r.status_code == 403


def test_upload_url_non_member_gets_404(environment):
    client, _, _ = environment
    owner_headers = _register_login(client, "upurl-nm-owner@example.com")
    ws = _create_workspace(client, owner_headers, "upurl-nonmember")

    client.post("/api/v1/auth/logout", headers=owner_headers)
    _register_login(client, "upurl-nonmember@example.com")
    other_headers = {"X-CSRF-Token": client.cookies["pylake_csrf"]}

    r = client.post(
        f"/api/v1/workspaces/{ws}/datasets/upload-url",
        json={"filename": "x.csv", "size_bytes": 100, "content_type": "text/csv"},
        headers=other_headers,
    )
    assert r.status_code == 404


def test_upload_url_rejects_bad_extension(environment):
    client, _, _ = environment
    headers = _register_login(client, "upurl-ext@example.com")
    ws = _create_workspace(client, headers, "upurl-ext")

    r = client.post(
        f"/api/v1/workspaces/{ws}/datasets/upload-url",
        json={"filename": "script.exe", "size_bytes": 100, "content_type": "application/octet-stream"},
        headers=headers,
    )
    assert r.status_code == 400
    assert "Unsupported" in r.json()["detail"]


def test_upload_url_rejects_oversize(environment, monkeypatch):
    client, _, settings = environment
    monkeypatch.setattr(settings, "max_upload_size_bytes", 1024)
    headers = _register_login(client, "upurl-size@example.com")
    ws = _create_workspace(client, headers, "upurl-size")

    r = client.post(
        f"/api/v1/workspaces/{ws}/datasets/upload-url",
        json={"filename": "big.csv", "size_bytes": 2048, "content_type": "text/csv"},
        headers=headers,
    )
    assert r.status_code == 413


def test_upload_url_key_is_workspace_scoped(environment):
    """The storage key must be scoped to the workspace, never to another workspace."""
    client, storage, _ = environment
    headers = _register_login(client, "upurl-scope@example.com")
    ws = _create_workspace(client, headers, "upurl-scope")

    client.post(
        f"/api/v1/workspaces/{ws}/datasets/upload-url",
        json={"filename": "data.csv", "size_bytes": len(SMALL_CSV), "content_type": "text/csv"},
        headers=headers,
    )
    key = storage.presigned_calls[-1]["key"]
    assert key.startswith(f"workspaces/{ws}/"), f"Key not workspace-scoped: {key}"


# ---------------------------------------------------------------------------
# upload-complete
# ---------------------------------------------------------------------------

def _create_pending_dataset(client, storage, headers, ws, body=SMALL_CSV, filename="data.csv"):
    r = client.post(
        f"/api/v1/workspaces/{ws}/datasets/upload-url",
        json={"filename": filename, "size_bytes": len(body), "content_type": "text/csv"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    dataset_id = r.json()["dataset_id"]
    key = storage.presigned_calls[-1]["key"]
    storage.simulate_put(key, body)
    return dataset_id, key


def test_upload_complete_happy_path(environment):
    client, storage, _ = environment
    headers = _register_login(client, "complete-ok@example.com")
    ws = _create_workspace(client, headers, "complete-ok")

    dataset_id, _ = _create_pending_dataset(client, storage, headers, ws)

    r = client.post(
        f"/api/v1/workspaces/{ws}/datasets/{dataset_id}/upload-complete",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ingestion_status"] == "COMPLETED"
    assert body["row_count"] == 2
    assert body["column_count"] == 3
    assert body["schema_json"] is not None


def test_upload_complete_schema_matches_multipart(environment):
    """Direct-upload ingestion must produce identical schema to the multipart path."""
    client, storage, _ = environment
    headers = _register_login(client, "schema-match@example.com")
    ws = _create_workspace(client, headers, "schema-match")

    # Multipart upload.
    mp = client.post(
        f"/api/v1/workspaces/{ws}/datasets/upload",
        files={"file": ("ref.csv", SMALL_CSV, "text/csv")},
        headers=headers,
    )
    assert mp.status_code == 201
    mp_schema = mp.json()["schema_json"]

    # Direct upload — use a different workspace so presigned_calls index is clean.
    ws2 = _create_workspace(client, headers, "schema-match2")
    dataset_id, _ = _create_pending_dataset(client, storage, headers, ws2)
    r = client.post(
        f"/api/v1/workspaces/{ws2}/datasets/{dataset_id}/upload-complete",
        headers=headers,
    )
    assert r.status_code == 200
    du_schema = r.json()["schema_json"]

    assert mp_schema["columns"] == du_schema["columns"]
    assert mp_schema["row_count"] == du_schema["row_count"]
    assert mp_schema["column_count"] == du_schema["column_count"]


def test_upload_complete_missing_object(environment):
    client, storage, _ = environment
    headers = _register_login(client, "complete-missing@example.com")
    ws = _create_workspace(client, headers, "complete-missing")

    r = client.post(
        f"/api/v1/workspaces/{ws}/datasets/upload-url",
        json={"filename": "data.csv", "size_bytes": len(SMALL_CSV), "content_type": "text/csv"},
        headers=headers,
    )
    dataset_id = r.json()["dataset_id"]
    # Do NOT simulate a PUT — the object is absent.

    r2 = client.post(
        f"/api/v1/workspaces/{ws}/datasets/{dataset_id}/upload-complete",
        headers=headers,
    )
    assert r2.status_code == 422
    assert "not found in storage" in r2.json()["detail"].lower()


def test_upload_complete_size_mismatch(environment):
    client, storage, _ = environment
    headers = _register_login(client, "complete-size@example.com")
    ws = _create_workspace(client, headers, "complete-size")

    large_body = SMALL_CSV * 50  # much larger than declared
    r = client.post(
        f"/api/v1/workspaces/{ws}/datasets/upload-url",
        json={"filename": "data.csv", "size_bytes": len(SMALL_CSV), "content_type": "text/csv"},
        headers=headers,
    )
    dataset_id = r.json()["dataset_id"]
    key = storage.presigned_calls[-1]["key"]
    storage.simulate_put(key, large_body)  # PUT a file much larger than declared

    r2 = client.post(
        f"/api/v1/workspaces/{ws}/datasets/{dataset_id}/upload-complete",
        headers=headers,
    )
    assert r2.status_code == 422
    assert "size" in r2.json()["detail"].lower()


def test_upload_complete_oversize_object(environment, monkeypatch):
    client, storage, settings = environment
    headers = _register_login(client, "complete-oversize@example.com")
    ws = _create_workspace(client, headers, "complete-oversize")

    # Create a dataset that just fits the original limit.
    dataset_id, key = _create_pending_dataset(client, storage, headers, ws)

    # Shrink the limit so the already-stored object is now oversize.
    monkeypatch.setattr(settings, "max_upload_size_bytes", 10)

    r = client.post(
        f"/api/v1/workspaces/{ws}/datasets/{dataset_id}/upload-complete",
        headers=headers,
    )
    assert r.status_code == 413


def test_upload_complete_other_workspace_dataset(environment):
    """upload-complete must 404 when the dataset belongs to a different workspace."""
    client, storage, _ = environment
    headers = _register_login(client, "complete-xws@example.com")
    ws1 = _create_workspace(client, headers, "complete-xws1")
    ws2 = _create_workspace(client, headers, "complete-xws2")

    dataset_id, key = _create_pending_dataset(client, storage, headers, ws1)

    # Try to complete via ws2 — must fail.
    r = client.post(
        f"/api/v1/workspaces/{ws2}/datasets/{dataset_id}/upload-complete",
        headers=headers,
    )
    assert r.status_code == 404


def test_upload_complete_requires_auth(environment):
    client, _, _ = environment
    r = client.post(
        "/api/v1/workspaces/00000000-0000-0000-0000-000000000001"
        "/datasets/00000000-0000-0000-0000-000000000002/upload-complete"
    )
    assert r.status_code == 401


def test_viewer_cannot_call_upload_complete(environment):
    client, storage, _ = environment
    owner_headers = _register_login(client, "complete-viewer-owner@example.com")
    ws = _create_workspace(client, owner_headers, "complete-viewer")

    dataset_id, _ = _create_pending_dataset(client, storage, owner_headers, ws)

    client.post(
        "/api/v1/auth/register",
        json={"email": "complete-viewer@example.com", "password": _PASSWORD, "full_name": "Viewer"},
    )
    _add_member(client, owner_headers, ws, "complete-viewer@example.com", "VIEWER")

    client.post("/api/v1/auth/logout", headers=owner_headers)
    client.post("/api/v1/auth/login", json={"email": "complete-viewer@example.com", "password": _PASSWORD})
    viewer_headers = {"X-CSRF-Token": client.cookies["pylake_csrf"]}

    r = client.post(
        f"/api/v1/workspaces/{ws}/datasets/{dataset_id}/upload-complete",
        headers=viewer_headers,
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Local storage raises NotImplementedError for presigned PUT
# ---------------------------------------------------------------------------

def test_local_storage_raises_not_implemented_for_presigned_put(tmp_path):
    storage = LocalFileStorage(str(tmp_path))
    with pytest.raises(NotImplementedError):
        storage.generate_presigned_put("some/key.csv", "text/csv", 900)


def test_upload_url_returns_400_when_backend_unsupported(environment, monkeypatch):
    client, _, _ = environment
    headers = _register_login(client, "upurl-notsup@example.com")
    ws = _create_workspace(client, headers, "upurl-notsup")

    # Replace storage with one whose generate_presigned_put raises NotImplementedError.
    class NoPresignStorage(FakeStorage):
        def generate_presigned_put(self, key, content_type, expires):
            raise NotImplementedError("not supported")

    monkeypatch.setattr(dataset_api, "get_storage", lambda: NoPresignStorage())

    r = client.post(
        f"/api/v1/workspaces/{ws}/datasets/upload-url",
        json={"filename": "x.csv", "size_bytes": 100, "content_type": "text/csv"},
        headers=headers,
    )
    assert r.status_code == 400
    assert "not supported" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# /members returns email and full_name; non-members get 404
# ---------------------------------------------------------------------------

def test_list_members_returns_email_and_full_name(environment):
    client, _, _ = environment
    headers = _register_login(client, "members-owner@example.com")
    ws = _create_workspace(client, headers, "members-test")

    # Add a second member.
    client.post(
        "/api/v1/auth/register",
        json={"email": "members-editor@example.com", "password": _PASSWORD, "full_name": "Ed Itor"},
    )
    _add_member(client, headers, ws, "members-editor@example.com", "EDITOR")

    r = client.get(f"/api/v1/workspaces/{ws}/members", headers=headers)
    assert r.status_code == 200
    members = r.json()
    assert len(members) == 2
    # Every member must have email and full_name populated.
    for member in members:
        assert member["email"] is not None and "@" in member["email"]
        assert member["full_name"] is not None and len(member["full_name"]) > 0

    # Verify the editor appears with correct data.
    editor = next((m for m in members if m["email"] == "members-editor@example.com"), None)
    assert editor is not None
    assert editor["full_name"] == "Ed Itor"
    assert editor["role"] == "EDITOR"


def test_list_members_non_member_gets_404(environment):
    client, _, _ = environment
    owner_headers = _register_login(client, "members-nm-owner@example.com")
    ws = _create_workspace(client, owner_headers, "members-nonmember")

    client.post("/api/v1/auth/logout", headers=owner_headers)
    _register_login(client, "members-nm-other@example.com")
    other_headers = {"X-CSRF-Token": client.cookies["pylake_csrf"]}

    r = client.get(f"/api/v1/workspaces/{ws}/members", headers=other_headers)
    assert r.status_code == 404
