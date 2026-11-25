"""Pipeline orchestration models

Revision ID: 20261125_0005
Revises: 20261125_0004
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261125_0005"
down_revision: Union[str, None] = "20261125_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pipeline_status = sa.Enum("DRAFT", "ACTIVE", "DISABLED", name="pipeline_status")
    run_status = sa.Enum("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", name="pipeline_run_status")
    step_status = sa.Enum("PENDING", "RUNNING", "SUCCEEDED", "FAILED", "SKIPPED", name="pipeline_step_status")

    op.create_table("pipelines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", pipeline_status, nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_pipeline_workspace_name"))
    op.create_index("ix_pipelines_workspace_id", "pipelines", ["workspace_id"], unique=False)

    op.create_table("pipeline_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("step_key", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("step_type", sa.String(50), nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("dependencies_json", sa.JSON(), nullable=False),
        sa.Column("execution_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pipeline_id", "execution_order", name="uq_pipeline_step_order"))
    op.create_index("ix_pipeline_steps_pipeline_id", "pipeline_steps", ["pipeline_id"], unique=False)

    op.create_table("pipeline_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("triggered_by", sa.Uuid(), nullable=True),
        sa.Column("status", run_status, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["triggered_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_pipeline_runs_pipeline_id", "pipeline_runs", ["pipeline_id"], unique=False)
    op.create_index("ix_pipeline_runs_workspace_id", "pipeline_runs", ["workspace_id"], unique=False)

    op.create_table("pipeline_step_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_run_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_step_id", sa.Uuid(), nullable=False),
        sa.Column("status", step_status, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("rows_processed", sa.Integer(), nullable=True),
        sa.Column("output_metadata_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pipeline_step_id"], ["pipeline_steps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_pipeline_step_runs_pipeline_run_id", "pipeline_step_runs", ["pipeline_run_id"], unique=False)
    op.create_index("ix_pipeline_step_runs_pipeline_step_id", "pipeline_step_runs", ["pipeline_step_id"], unique=False)

    op.create_table("pipeline_schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("cron_expression", sa.String(200), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_pipeline_schedules_pipeline_id", "pipeline_schedules", ["pipeline_id"], unique=False)
    op.create_index("ix_pipeline_schedules_workspace_id", "pipeline_schedules", ["workspace_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pipeline_schedules_workspace_id", table_name="pipeline_schedules")
    op.drop_index("ix_pipeline_schedules_pipeline_id", table_name="pipeline_schedules")
    op.drop_table("pipeline_schedules")
    op.drop_index("ix_pipeline_step_runs_pipeline_step_id", table_name="pipeline_step_runs")
    op.drop_index("ix_pipeline_step_runs_pipeline_run_id", table_name="pipeline_step_runs")
    op.drop_table("pipeline_step_runs")
    op.drop_index("ix_pipeline_runs_workspace_id", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_pipeline_id", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
    op.drop_index("ix_pipeline_steps_pipeline_id", table_name="pipeline_steps")
    op.drop_table("pipeline_steps")
    op.drop_index("ix_pipelines_workspace_id", table_name="pipelines")
    op.drop_table("pipelines")
    sa.Enum(name="pipeline_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="pipeline_run_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="pipeline_step_status").drop(op.get_bind(), checkfirst=True)
