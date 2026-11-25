"""Add dataset ingestion metadata

Revision ID: 20261125_0002
Revises: 20261125_0001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261125_0002"
down_revision: Union[str, None] = "20261125_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    status = sa.Enum("PENDING", "VALIDATING", "PROCESSING", "COMPLETED", "FAILED", name="dataset_status")
    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("file_format", sa.String(length=20), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_backend", sa.String(length=20), nullable=False),
        sa.Column("storage_key", sa.String(length=1000), nullable=False),
        sa.Column("schema_json", sa.JSON(), nullable=True),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("column_count", sa.Integer(), nullable=True),
        sa.Column("ingestion_status", status, nullable=False),
        sa.Column("ingestion_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_datasets_workspace_id", "datasets", ["workspace_id"], unique=False)
    op.create_index("ix_datasets_uploaded_by", "datasets", ["uploaded_by"], unique=False)
    op.create_index("ix_datasets_status", "datasets", ["ingestion_status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_datasets_status", table_name="datasets")
    op.drop_index("ix_datasets_uploaded_by", table_name="datasets")
    op.drop_index("ix_datasets_workspace_id", table_name="datasets")
    op.drop_table("datasets")
    sa.Enum(name="dataset_status").drop(op.get_bind(), checkfirst=True)
