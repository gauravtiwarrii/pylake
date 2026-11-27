"""Persist Ask question history."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261127_0013"
down_revision: Union[str, None] = "20261127_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ask_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer_type", sa.String(20), nullable=False),
        sa.Column("sql_text", sa.Text(), nullable=True),
        sa.Column("citations_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ask_history_workspace_id", "ask_history", ["workspace_id"])
    op.create_index("ix_ask_history_user_id", "ask_history", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_ask_history_user_id", table_name="ask_history")
    op.drop_index("ix_ask_history_workspace_id", table_name="ask_history")
    op.drop_table("ask_history")
