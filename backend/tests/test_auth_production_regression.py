"""Regression tests for the production login outage (missing app.storage package)."""
import importlib
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_storage_package_importable():
    module = importlib.import_module("app.storage.factory")
    assert hasattr(module, "get_storage")


def test_storage_package_not_gitignored():
    """backend/app/storage must be committed; a broad `storage/` ignore broke Vercel."""
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "backend/app/storage/factory.py"],
            cwd=REPO_ROOT,
            capture_output=True,
        )
    except FileNotFoundError:
        return  # git not available in this environment
    # exit code 1 == not ignored
    assert result.returncode == 1, "backend/app/storage is ignored by .gitignore"


def test_unhandled_errors_return_safe_json_with_request_id():
    from fastapi.testclient import TestClient
    from app.main import app

    @app.get("/__test_boom")
    def _boom():  # pragma: no cover - exercised via client
        raise RuntimeError("secret internal detail")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/__test_boom", headers={"X-Request-ID": "test-req-1"})
    assert response.status_code == 500
    body = response.json()
    assert body == {"detail": "Internal server error", "request_id": "test-req-1"}
    assert "secret" not in response.text
    assert response.headers["X-Request-ID"] == "test-req-1"
