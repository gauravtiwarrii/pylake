"""Persist contextual AI recommendations and user decisions.

Revision ID: 20261127_0010
Revises: 20261126_0009
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261127_0010"
down_revision: Union[str, None] = "20261126_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("page_type", sa.String(length=30), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.String(length=10), nullable=False),
        sa.Column("expected_impact", sa.Text(), nullable=False),
        sa.Column("proposed_action_json", sa.JSON(), nullable=False),
        sa.Column("risk_level", sa.String(length=10), nullable=False),
        sa.Column("required_permissions_json", sa.JSON(), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_recommendations_workspace_id", "ai_recommendations", ["workspace_id"], unique=False)
    op.create_index("ix_ai_recommendations_user_id", "ai_recommendations", ["user_id"], unique=False)
    op.create_index("ix_ai_recommendations_status", "ai_recommendations", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ai_recommendations_status", table_name="ai_recommendations")
    op.drop_index("ix_ai_recommendations_user_id", table_name="ai_recommendations")
    op.drop_index("ix_ai_recommendations_workspace_id", table_name="ai_recommendations")
    op.drop_table("ai_recommendations")
