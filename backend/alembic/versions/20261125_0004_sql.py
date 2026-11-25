"""Add SQL history and saved query metadata

Revision ID: 20261125_0004
Revises: 20261125_0003
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261125_0004"
down_revision: Union[str, None] = "20261125_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    query_status = sa.Enum("RUNNING", "SUCCESS", "FAILED", name="query_execution_status")
    op.create_table(
        "query_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("query_name", sa.String(length=200), nullable=True),
        sa.Column("sql_text", sa.Text(), nullable=False),
        sa.Column("execution_status", query_status, nullable=False),
        sa.Column("execution_duration_ms", sa.Integer(), nullable=True),
        sa.Column("rows_returned", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_query_history_workspace_id", "query_history", ["workspace_id"], unique=False)
    op.create_index("ix_query_history_user_id", "query_history", ["user_id"], unique=False)

    op.create_table(
        "saved_queries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sql_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_saved_query_workspace_name"),
    )
    op.create_index("ix_saved_queries_workspace_id", "saved_queries", ["workspace_id"], unique=False)
    op.create_index("ix_saved_queries_user_id", "saved_queries", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_saved_queries_user_id", table_name="saved_queries")
    op.drop_index("ix_saved_queries_workspace_id", table_name="saved_queries")
    op.drop_table("saved_queries")
    op.drop_index("ix_query_history_user_id", table_name="query_history")
    op.drop_index("ix_query_history_workspace_id", table_name="query_history")
    op.drop_table("query_history")
    sa.Enum(name="query_execution_status").drop(op.get_bind(), checkfirst=True)
