"""Autopilot plans and steps.

Revision ID: 20261127_0011
Revises: 20261127_0010
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261127_0011"
down_revision: Union[str, None] = "20261127_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    plan_status = sa.Enum(
        "DRAFT",
        "PREVIEWED",
        "APPROVED",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        name="autopilot_plan_status",
    )
    step_status = sa.Enum(
        "PENDING",
        "SKIPPED",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        name="autopilot_step_status",
    )
    risk_level = sa.Enum("LOW", "MEDIUM", "HIGH", name="autopilot_risk_level")

    op.create_table(
        "autopilot_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", plan_status, nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=True),
        sa.Column("ai_provider", sa.String(length=40), nullable=True),
        sa.Column("ai_model", sa.String(length=200), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("report_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_autopilot_plans_workspace_id", "autopilot_plans", ["workspace_id"], unique=False)
    op.create_index("ix_autopilot_plans_created_by", "autopilot_plans", ["created_by"], unique=False)
    op.create_index("ix_autopilot_plans_status", "autopilot_plans", ["status"], unique=False)

    op.create_table(
        "autopilot_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("action_key", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("arguments_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("preview_json", sa.JSON(), nullable=True),
        sa.Column("risk_level", risk_level, nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("status", step_status, nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["plan_id"], ["autopilot_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_autopilot_steps_plan_id", "autopilot_steps", ["plan_id"], unique=False)
    op.create_index("ix_autopilot_steps_status", "autopilot_steps", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_autopilot_steps_status", table_name="autopilot_steps")
    op.drop_index("ix_autopilot_steps_plan_id", table_name="autopilot_steps")
    op.drop_table("autopilot_steps")
    op.drop_index("ix_autopilot_plans_status", table_name="autopilot_plans")
    op.drop_index("ix_autopilot_plans_created_by", table_name="autopilot_plans")
    op.drop_index("ix_autopilot_plans_workspace_id", table_name="autopilot_plans")
    op.drop_table("autopilot_plans")
    sa.Enum(name="autopilot_plan_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="autopilot_step_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="autopilot_risk_level").drop(op.get_bind(), checkfirst=True)
