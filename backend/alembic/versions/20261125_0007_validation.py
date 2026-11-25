"""Milestone 7.1 schedule and audit reliability fixes

Revision ID: 20261125_0007
Revises: 20261125_0006
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261125_0007"
down_revision: Union[str, None] = "20261125_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("pipeline_runs") as batch:
        batch.add_column(sa.Column("schedule_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_pipeline_runs_schedule_id",
            "pipeline_schedules",
            ["schedule_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_pipeline_runs_schedule_id", ["schedule_id"], unique=False)
        batch.create_index("ix_pipeline_runs_scheduled_at", ["scheduled_at"], unique=False)
        batch.create_unique_constraint(
            "uq_pipeline_schedule_occurrence",
            ["schedule_id", "scheduled_at"],
        )

def downgrade() -> None:
    with op.batch_alter_table("pipeline_runs") as batch:
        batch.drop_constraint("uq_pipeline_schedule_occurrence", type_="unique")
        batch.drop_index("ix_pipeline_runs_scheduled_at")
        batch.drop_index("ix_pipeline_runs_schedule_id")
        batch.drop_constraint("fk_pipeline_runs_schedule_id", type_="foreignkey")
        batch.drop_column("scheduled_at")
        batch.drop_column("schedule_id")
