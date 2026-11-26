import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.pipeline_engine as pipeline_engine
from app.core.db import Base
from app.models.entities import (
    Pipeline,
    PipelineRun,
    PipelineStatus,
    PipelineStep,
    RunStatus,
    User,
    Workspace,
)
from app.services.pipeline_graph import PipelineGraphError, validate_pipeline_graph


@pytest.fixture()
def pipeline_database(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(pipeline_engine, "SessionLocal", testing_session)
    yield testing_session
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def step(key: str, order: int, dependencies: list[str] | None = None, step_type: str = "SOURCE_DATASET"):
    return {
        "step_key": key,
        "name": key,
        "step_type": step_type,
        "dependencies": dependencies or [],
        "execution_order": order,
    }


def test_dependency_ordering():
    steps = [
        step("quality", 3, ["transform"], "DATA_QUALITY"),
        step("source", 1),
        step("transform", 2, ["source"], "TRANSFORM"),
    ]
    ordered = validate_pipeline_graph(steps)
    assert [item["step_key"] for item in ordered] == ["source", "transform", "quality"]


def test_missing_dependency_rejected():
    try:
        validate_pipeline_graph([step("quality", 1, ["missing"], "DATA_QUALITY")])
        raise AssertionError("Missing dependency should fail")
    except PipelineGraphError:
        pass


def test_circle_rejected():
    steps = [
        step("a", 1, ["b"]),
        step("b", 2, ["a"]),
    ]
    try:
        validate_pipeline_graph(steps)
        raise AssertionError("Cycle should fail")
    except PipelineGraphError:
        pass


def test_duplicate_step_identifier_rejected():
    try:
        validate_pipeline_graph([step("source", 1), step("source", 2)])
        raise AssertionError("Duplicate identifier should fail")
    except PipelineGraphError:
        pass


def test_pipeline_retries_failed_step_then_succeeds(pipeline_database, monkeypatch):
    user_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()
    step_id = uuid.uuid4()
    run_id = uuid.uuid4()
    with pipeline_database() as db:
        db.add(User(
            id=user_id,
            email="pipeline-retry@example.com",
            hashed_password="test-hash",
            full_name="Pipeline Test",
        ))
        db.add(Workspace(
            id=workspace_id,
            name="Pipeline Test",
            slug="pipeline-retry-test",
            owner_id=user_id,
        ))
        db.add(Pipeline(
            id=pipeline_id,
            workspace_id=workspace_id,
            name="Retry test",
            status=PipelineStatus.DRAFT,
        ))
        db.add(PipelineStep(
            id=step_id,
            pipeline_id=pipeline_id,
            step_key="test-step",
            name="Test step",
            step_type="SOURCE_DATASET",
            configuration_json={},
            dependencies_json=[],
            execution_order=1,
        ))
        db.add(PipelineRun(
            id=run_id,
            pipeline_id=pipeline_id,
            workspace_id=workspace_id,
            status=RunStatus.QUEUED,
            max_retries=1,
        ))
        db.commit()

    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient test failure")
        return {"row_count": 1}

    monkeypatch.setattr(pipeline_engine, "execute_step", fail_once)

    assert pipeline_engine.claim_next_job("test-worker").id == run_id
    pipeline_engine.execute_pipeline_run(run_id)

    with pipeline_database() as db:
        retried_run = db.get(PipelineRun, run_id)
        assert retried_run.status == RunStatus.QUEUED
        assert retried_run.retry_count == 1
        assert retried_run.started_at is None
        assert retried_run.completed_at is None
        assert retried_run.duration_ms is None

    assert pipeline_engine.claim_next_job("test-worker").id == run_id
    pipeline_engine.execute_pipeline_run(run_id)

    with pipeline_database() as db:
        completed_run = db.get(PipelineRun, run_id)
        assert completed_run.status == RunStatus.SUCCEEDED
        assert completed_run.retry_count == 1
        assert completed_run.completed_at is not None
        assert completed_run.duration_ms is not None
