import json
import tempfile
from datetime import timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.v1.datasets as datasets_api
import app.api.v1.trust as trust_api
import app.api.v1.lakehouse as lakehouse_api
import app.ai.actions as ai_actions
import app.api.v1.ai as ai_api
import app.services.pipeline_engine as pipeline_engine
import app.services.trust as trust_service
from app.ai.providers import AICompletion
from app.core.config import Settings
from app.core.db import Base, get_db
from app.main import app
from app.models.entities import CatalogAsset, CatalogSchemaHistory, DatasetVersion, Pipeline, PipelineStep, PipelineStatus, TrustSnapshot, WorkspaceMember, WorkspaceRole, utcnow
from app.storage.local import LocalFileStorage


@pytest.fixture()
def trust_env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    temp = tempfile.TemporaryDirectory(prefix="pylake-trust-")
    storage = LocalFileStorage(temp.name)
    monkeypatch.setattr(datasets_api, "get_storage", lambda: storage)
    monkeypatch.setattr(lakehouse_api, "get_storage", lambda: storage)
    monkeypatch.setattr(trust_api, "get_storage", lambda: storage)
    monkeypatch.setattr(ai_actions, "get_storage", lambda: storage)

    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, sessions, storage
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    temp.cleanup()


def _workspace(client, email, slug):
    assert client.post("/api/v1/auth/register", json={"email": email, "password": "a-secure-password", "full_name": "Trust User"}).status_code == 201
    assert client.post("/api/v1/auth/login", json={"email": email, "password": "a-secure-password"}).status_code == 200
    headers = {"X-CSRF-Token": client.cookies["pylake_csrf"]}
    created = client.post("/api/v1/workspaces", json={"name": "Trust", "slug": slug}, headers=headers)
    assert created.status_code == 201, created.text
    return created.json()["id"], headers


def _asset(client, workspace_id, headers, content=b"id,amount,label\n1,10,ok\n2,,ok\n2,,ok\n"):
    upload = client.post(f"/api/v1/workspaces/{workspace_id}/datasets/upload", files={"file": ("trust.csv", content, "text/csv")}, data={"name": "trust"}, headers=headers)
    assert upload.status_code == 201, upload.text
    catalog = client.get(f"/api/v1/workspaces/{workspace_id}/catalog", headers=headers)
    assert catalog.status_code == 200, catalog.text
    return next(item["id"] for item in catalog.json()["items"] if item["asset_type"] == "DATASET")


def test_trust_measures_real_values_and_excludes_not_measured(trust_env):
    client, _, _ = trust_env
    workspace_id, headers = _workspace(client, "trust-score@example.com", "trust-score")
    asset_id = _asset(client, workspace_id, headers)
    response = client.post(f"/api/v1/workspaces/{workspace_id}/trust/{asset_id}/compute", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metrics"]["completeness"]["score"] == pytest.approx(77.7778, abs=.02)
    assert body["metrics"]["uniqueness"]["score"] == pytest.approx(66.67, abs=.02)
    assert body["metrics"]["validity"]["score"] is None
    assert body["metrics"]["validity"]["status"] == "NOT_MEASURED"
    assert "validity" in body["excluded_metrics"]
    measured = body["measured_metrics"]
    expected = sum(body["metrics"][key]["score"] * weight for key, weight in {
        "completeness": .2, "uniqueness": .15, "consistency": .15, "lineage_completeness": .1,
    }.items() if body["metrics"][key]["status"] == "MEASURED") / sum({"completeness": .2, "uniqueness": .15, "consistency": .15, "lineage_completeness": .1}[key] for key in measured)
    assert body["overall_score"] == pytest.approx(expected, abs=.02)
    assert body["sample_rows"] == 3 and body["total_rows"] == 3 and body["sampled"] is False


@pytest.mark.parametrize(("rule_type", "column", "config", "expected"), [
    ("NOT_NULL", "amount", {}, "FAIL"),
    ("UNIQUE", "id", {}, "FAIL"),
    ("RANGE", "amount", {"minimum": 0, "maximum": 9}, "FAIL"),
    ("REGEX", "label", {"pattern": "(ok|no)"}, "PASS"),
    ("ALLOWED_VALUES", "label", {"values": ["ok", "no"]}, "PASS"),
    ("MIN_ROW_COUNT", None, {"minimum": 3}, "PASS"),
])
def test_each_quality_rule_type_passes_or_fails(trust_env, rule_type, column, config, expected):
    client, _, _ = trust_env
    slug = f"rule-{rule_type.lower().replace('_', '-')}"
    workspace_id, headers = _workspace(client, f"{rule_type.lower()}@example.com", slug)
    asset_id = _asset(client, workspace_id, headers)
    created = client.post(f"/api/v1/workspaces/{workspace_id}/catalog/{asset_id}/quality-rules",
        json={"rule_type": rule_type, "column_name": column, "config_json": config, "severity": "HIGH"}, headers=headers)
    assert created.status_code == 201, created.text
    result = client.post(f"/api/v1/workspaces/{workspace_id}/trust/{asset_id}/compute", headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["rule_results"][0]["status"] == expected


def test_rules_validation_crud_freshness_viewer_csrf_and_workspace_isolation(trust_env):
    client, sessions, _ = trust_env
    workspace_id, headers = _workspace(client, "trust-api@example.com", "trust-api")
    asset_id = _asset(client, workspace_id, headers)
    base = f"/api/v1/workspaces/{workspace_id}/catalog/{asset_id}/quality-rules"
    assert client.post(base, json={"rule_type": "REGEX", "column_name": "label", "config_json": {"pattern": "["}}, headers=headers).status_code == 422
    assert client.post(base, json={"rule_type": "RANGE", "column_name": "amount", "config_json": {"minimum": 5, "maximum": 1}}, headers=headers).status_code == 422
    created = client.post(base, json={"rule_type": "NOT_NULL", "column_name": "amount", "config_json": {}}, headers=headers)
    assert created.status_code == 201
    rule_id = created.json()["id"]
    assert client.get(base, headers=headers).json()[0]["id"] == rule_id
    assert client.patch(f"{base}/{rule_id}", json={"enabled": False}, headers=headers).status_code == 200
    assert client.delete(f"{base}/{rule_id}", headers=headers).status_code == 204
    assert client.patch(f"/api/v1/workspaces/{workspace_id}/catalog/{asset_id}/freshness", json={"freshness_target_hours": 24}, headers=headers).status_code == 200
    assert client.patch(f"/api/v1/workspaces/{workspace_id}/catalog/{asset_id}/freshness", json={"freshness_target_hours": 0}, headers=headers).status_code == 422
    no_csrf = client.post(f"/api/v1/workspaces/{workspace_id}/trust/{asset_id}/compute")
    assert no_csrf.status_code == 403
    foreign = "00000000-0000-0000-0000-000000000001"
    assert client.post(f"/api/v1/workspaces/{workspace_id}/trust/{foreign}/compute", headers=headers).status_code == 404
    with sessions() as db:
        member = db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == UUID(workspace_id)).one()
        member.role = WorkspaceRole.VIEWER
        db.commit()
    assert client.post(base, json={"rule_type": "UNIQUE", "column_name": "id", "config_json": {}}, headers=headers).status_code == 403
    assert client.get(f"/api/v1/workspaces/{workspace_id}/trust/{foreign}", headers=headers).status_code == 404


def test_trust_history_order_and_empty_state(trust_env):
    client, sessions, _ = trust_env
    workspace_id, headers = _workspace(client, "trust-history@example.com", "trust-history")
    asset_id = _asset(client, workspace_id, headers)
    with sessions() as db:
        db.query(TrustSnapshot).filter(TrustSnapshot.asset_id == UUID(asset_id)).delete()
        db.commit()
    assert client.get(f"/api/v1/workspaces/{workspace_id}/trust/{asset_id}", headers=headers).json()["snapshot"] is None
    first = client.post(f"/api/v1/workspaces/{workspace_id}/trust/{asset_id}/compute", headers=headers).json()
    second = client.post(f"/api/v1/workspaces/{workspace_id}/trust/{asset_id}/compute", headers=headers).json()
    items = client.get(f"/api/v1/workspaces/{workspace_id}/trust/{asset_id}/history?limit=1", headers=headers).json()["items"]
    assert len(items) == 1 and items[0]["id"] == second["id"] and first["id"] != second["id"]
    summary = client.get(f"/api/v1/workspaces/{workspace_id}/trust/summary", headers=headers).json()
    assert next(row for row in summary["items"] if row["asset_id"] == asset_id)["overall_score"] is not None


@pytest.mark.parametrize(("payload", "expected_rows", "completeness", "consistency"), [
    (b"a,b\n,\n,\n", 2, 0, "NOT_MEASURED"),
    (b"value\n1\n", 1, 100, "MEASURED"),
    (b"value\n", 0, None, "NOT_MEASURED"),
    (b"amount\n1\n2\n3\n4\nbad\n", 5, 100, "MEASURED"),
])
def test_empty_all_null_single_row_and_wrong_type_samples(trust_env, payload, expected_rows, completeness, consistency):
    client, _, _ = trust_env
    workspace_id, headers = _workspace(client, f"sample-{expected_rows}-{len(payload)}@example.com", f"sample-{expected_rows}-{len(payload)}")
    asset_id = _asset(client, workspace_id, headers, payload)
    result = client.post(f"/api/v1/workspaces/{workspace_id}/trust/{asset_id}/compute", headers=headers)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["sample_rows"] == expected_rows
    assert body["metrics"]["completeness"]["status"] == ("NOT_MEASURED" if completeness is None else "MEASURED")
    if completeness is not None:
        assert body["metrics"]["completeness"]["score"] == pytest.approx(completeness)
    if expected_rows == 5:
        assert body["metrics"]["consistency"]["score"] == pytest.approx(80)
    else:
        assert body["metrics"]["consistency"]["status"] == consistency


def test_freshness_decay_and_schema_stability(trust_env):
    client, sessions, _ = trust_env
    workspace_id, headers = _workspace(client, "trust-decay@example.com", "trust-decay")
    _asset(client, workspace_id, headers)
    table_id = next(item["id"] for item in client.get(f"/api/v1/workspaces/{workspace_id}/catalog", headers=headers).json()["items"] if item["asset_type"] == "TABLE")
    asset_id = UUID(table_id)
    with sessions() as db:
        asset = db.query(CatalogAsset).filter(CatalogAsset.id == asset_id).one()
        version = db.query(DatasetVersion).filter(DatasetVersion.lakehouse_table_id == asset.lakehouse_table_id).one()
        version.created_at = utcnow() - timedelta(hours=24)
        asset.freshness_target_hours = 24
        db.query(CatalogSchemaHistory).filter(CatalogSchemaHistory.asset_id == asset.id).delete()
        now = utcnow()
        db.add_all([
            CatalogSchemaHistory(asset_id=asset.id, version_id=version.id, schema_json={"columns": [{"name": "id", "type": "Int64"}, {"name": "old", "type": "String"}]}, created_at=now - timedelta(hours=1)),
            CatalogSchemaHistory(asset_id=asset.id, version_id=version.id, schema_json={"columns": [{"name": "id", "type": "String"}]}, created_at=now),
        ])
        db.commit()
    result = client.post(f"/api/v1/workspaces/{workspace_id}/trust/{asset_id}/compute", headers=headers)
    assert result.status_code == 200, result.text
    metrics = result.json()["metrics"]
    assert metrics["freshness"]["score"] == pytest.approx(66.67, abs=.1)
    assert metrics["schema_stability"]["score"] == 60


def test_ingestion_trigger_creates_snapshot_and_failure_is_nonfatal(trust_env, monkeypatch):
    client, _, _ = trust_env
    workspace_id, headers = _workspace(client, "trust-trigger@example.com", "trust-trigger")
    asset_id = _asset(client, workspace_id, headers)
    latest = client.get(f"/api/v1/workspaces/{workspace_id}/trust/{asset_id}", headers=headers)
    assert latest.status_code == 200 and latest.json()["overall_score"] is not None

    calls = 0

    def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("injected snapshot failure")

    monkeypatch.setattr(trust_service, "compute_trust", fail)
    uploaded = client.post(f"/api/v1/workspaces/{workspace_id}/datasets/upload",
        files={"file": ("second.csv", b"value\n1\n2\n", "text/csv")}, data={"name": "second"}, headers=headers)
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["ingestion_status"] == "COMPLETED"
    assert calls == 1


def test_pipeline_quality_trigger_failure_does_not_fail_step(trust_env, monkeypatch):
    client, sessions, storage = trust_env
    workspace_id, headers = _workspace(client, "trust-pipeline-trigger@example.com", "trust-pipeline-trigger")
    _asset(client, workspace_id, headers)
    table = next(row for row in client.get(f"/api/v1/workspaces/{workspace_id}/lakehouse/tables", headers=headers).json() if row["name"] == "trust")
    promoted = client.post(f"/api/v1/workspaces/{workspace_id}/lakehouse/tables/{table['id']}/promote",
        json={"target_layer": "SILVER"}, headers=headers)
    assert promoted.status_code == 200, promoted.text
    table_asset_id = next(row["id"] for row in client.get(f"/api/v1/workspaces/{workspace_id}/catalog", headers=headers).json()["items"] if row.get("lakehouse_table_id") == table["id"])
    assert client.get(f"/api/v1/workspaces/{workspace_id}/trust/{table_asset_id}", headers=headers).json()["overall_score"] is not None
    monkeypatch.setattr(pipeline_engine, "get_storage", lambda: storage)

    calls = 0
    def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("injected trust failure")

    monkeypatch.setattr(trust_service, "compute_trust", fail)
    with sessions() as db:
        member = db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == UUID(workspace_id)).one()
        pipeline = Pipeline(workspace_id=UUID(workspace_id), name="trust check", status=PipelineStatus.DRAFT, created_by=member.user_id)
        db.add(pipeline); db.flush()
        step = PipelineStep(pipeline_id=pipeline.id, step_key="quality", name="quality", step_type="DATA_QUALITY",
            configuration_json={"table_name": "trust"}, dependencies_json=[], execution_order=1)
        db.add(step); db.commit(); db.refresh(step)
        output = pipeline_engine.execute_step(db, UUID(int=0), UUID(workspace_id), member.user_id, step)
        assert output["duplicate_rows"] == 1
    assert calls == 1


def test_autopilot_compute_trust_action_previews_without_writes_then_executes(trust_env):
    client, sessions, _ = trust_env
    workspace_id, headers = _workspace(client, "trust-action@example.com", "trust-action")
    asset_id = _asset(client, workspace_id, headers)
    before = client.get(f"/api/v1/workspaces/{workspace_id}/trust/{asset_id}", headers=headers).json()["id"]
    create = client.post(f"/api/v1/workspaces/{workspace_id}/ai/autopilot/plans", json={"goal": "Measure trust", "steps":[
        {"action_key": "compute_trust", "title": "Compute trust", "arguments": {"asset_id": asset_id}}]}, headers=headers)
    assert create.status_code == 201, create.text
    plan = create.json()
    assert plan["steps"][0]["risk_level"] == "LOW"
    assert plan["steps"][0]["preview_json"] is None
    preview = client.post(f"/api/v1/workspaces/{workspace_id}/ai/autopilot/plans/{plan['id']}/preview", headers=headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["steps"][0]["preview_json"]["writes"] is False
    after_preview = client.get(f"/api/v1/workspaces/{workspace_id}/trust/{asset_id}", headers=headers).json()["id"]
    assert after_preview == before
    approved = client.post(f"/api/v1/workspaces/{workspace_id}/ai/autopilot/plans/{plan['id']}/approve",
        json={"plan_hash": preview.json()["plan_hash"]}, headers=headers)
    assert approved.status_code == 200, approved.text
    executed = client.post(f"/api/v1/workspaces/{workspace_id}/ai/autopilot/plans/{plan['id']}/execute", headers=headers)
    assert executed.status_code == 200, executed.text
    assert executed.json()["steps"][0]["status"] == "SUCCEEDED"
    history = client.get(f"/api/v1/workspaces/{workspace_id}/trust/{asset_id}/history", headers=headers).json()["items"]
    assert len(history) >= 2 and history[0]["id"] != before


def test_trust_recommendation_uses_measured_evidence_and_accept_creates_plan(trust_env):
    client, _, _ = trust_env
    workspace_id, headers = _workspace(client, "trust-recommendation@example.com", "trust-recommendation")
    asset_id = _asset(client, workspace_id, headers, b"id,required,other\n1,,\n2,,\n3,,\n")
    response = client.post(f"/api/v1/workspaces/{workspace_id}/ai/recommendations", json={
        "page_type": "quality", "catalog_asset_id": asset_id,
    }, headers=headers)
    assert response.status_code == 200, response.text
    recommendation = next(item for item in response.json() if item["proposed_action"]["tool"] == "create_quality_rule")
    assert "100.00%" in recommendation["evidence"][0]["detail"]
    accepted = client.post(f"/api/v1/workspaces/{workspace_id}/ai/recommendations/{recommendation['id']}/accept", headers=headers)
    assert accepted.status_code == 200, accepted.text
    plan = client.get(f"/api/v1/workspaces/{workspace_id}/ai/autopilot/plans/{accepted.json()['plan_id']}", headers=headers)
    assert plan.status_code == 200 and len(plan.json()["steps"]) == 1
    assert plan.json()["steps"][0]["action_key"] == "create_quality_rule"


def test_trust_explain_uses_aggregates_only_and_returns_503_when_disabled(trust_env, monkeypatch):
    client, _, _ = trust_env
    workspace_id, headers = _workspace(client, "trust-explain@example.com", "trust-explain")
    asset_id = _asset(client, workspace_id, headers, b"payload\nraw_secret_cell_not_for_ai\n")
    url = f"/api/v1/workspaces/{workspace_id}/trust/{asset_id}/explain"
    assert client.post(url, headers=headers).status_code == 503

    class FakeProvider:
        name = "test-provider"
        model = "trust-test"
        messages = []

        def complete(self, messages, max_tokens):
            self.messages = list(messages)
            return AICompletion(json.dumps({"summary": "Measured aggregate scores are available.", "recommendations": ["Review low measured metrics."]}))

    provider = FakeProvider()
    settings = Settings(ai_provider="openai_compatible", ai_api_key="test-key", ai_daily_token_limit=10000)
    monkeypatch.setattr(trust_api, "get_settings", lambda: settings)
    monkeypatch.setattr(trust_api, "_configured_provider", lambda _: provider)
    response = client.post(url, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["ai_estimate"] is True
    assert "raw_secret_cell_not_for_ai" not in " ".join(message["content"] for message in provider.messages)


def test_migration_upgrade_downgrade(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from app.core.config import get_settings

    database = tmp_path / "trust_migration.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    get_settings.cache_clear()
    monkeypatch.delenv("DATABASE_URL", raising=False)
