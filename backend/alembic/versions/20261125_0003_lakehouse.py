"""Lakehouse tables, versions, objects, and transformations

Revision ID: 20261125_0003
Revises: 20261125_0002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261125_0003"
down_revision: Union[str, None] = "20261125_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    layer = sa.Enum("BRONZE", "SILVER", "GOLD", name="lakehouse_layer")
    version_status = sa.Enum("PENDING", "COMPLETED", "FAILED", name="lakehouse_version_status")
    transformation_status = sa.Enum("PENDING", "COMPLETED", "FAILED", name="transformation_status")

    op.create_table(
        "lakehouse_tables",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("current_layer", layer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_lakehouse_table_workspace_name"),
    )
    op.create_index("ix_lakehouse_tables_workspace_id", "lakehouse_tables", ["workspace_id"], unique=False)

    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("lakehouse_table_id", sa.Uuid(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("layer", layer, nullable=False),
        sa.Column("storage_key", sa.String(length=1000), nullable=False),
        sa.Column("schema_json", sa.JSON(), nullable=True),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("column_count", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("file_format", sa.String(length=20), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("status", version_status, nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lakehouse_table_id"], ["lakehouse_tables.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "version_number", name="uq_dataset_version_number"),
    )
    op.create_index("ix_dataset_versions_dataset_id", "dataset_versions", ["dataset_id"], unique=False)
    op.create_index("ix_dataset_versions_lakehouse_table_id", "dataset_versions", ["lakehouse_table_id"], unique=False)
    op.create_index("ix_dataset_versions_created_by", "dataset_versions", ["created_by"], unique=False)

    op.create_table(
        "storage_objects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=True),
        sa.Column("version_id", sa.Uuid(), nullable=True),
        sa.Column("layer", layer, nullable=False),
        sa.Column("storage_key", sa.String(length=1000), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["dataset_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_storage_object_key"),
    )
    op.create_index("ix_storage_objects_workspace_id", "storage_objects", ["workspace_id"], unique=False)
    op.create_index("ix_storage_objects_dataset_id", "storage_objects", ["dataset_id"], unique=False)
    op.create_index("ix_storage_objects_version_id", "storage_objects", ["version_id"], unique=False)

    op.create_table(
        "transformation_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=False),
        sa.Column("output_version_id", sa.Uuid(), nullable=True),
        sa.Column("transformation_type", sa.String(length=100), nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("execution_status", transformation_status, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_version_id"], ["dataset_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["output_version_id"], ["dataset_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transformation_records_dataset_id", "transformation_records", ["dataset_id"], unique=False)
    op.create_index("ix_transformation_records_source_version_id", "transformation_records", ["source_version_id"], unique=False)
    op.create_index("ix_transformation_records_output_version_id", "transformation_records", ["output_version_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_transformation_records_output_version_id", table_name="transformation_records")
    op.drop_index("ix_transformation_records_source_version_id", table_name="transformation_records")
    op.drop_index("ix_transformation_records_dataset_id", table_name="transformation_records")
    op.drop_table("transformation_records")
    op.drop_index("ix_storage_objects_version_id", table_name="storage_objects")
    op.drop_index("ix_storage_objects_dataset_id", table_name="storage_objects")
    op.drop_index("ix_storage_objects_workspace_id", table_name="storage_objects")
    op.drop_table("storage_objects")
    op.drop_index("ix_dataset_versions_created_by", table_name="dataset_versions")
    op.drop_index("ix_dataset_versions_lakehouse_table_id", table_name="dataset_versions")
    op.drop_index("ix_dataset_versions_dataset_id", table_name="dataset_versions")
    op.drop_table("dataset_versions")
    op.drop_index("ix_lakehouse_tables_workspace_id", table_name="lakehouse_tables")
    op.drop_table("lakehouse_tables")
    sa.Enum(name="transformation_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="lakehouse_version_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="lakehouse_layer").drop(op.get_bind(), checkfirst=True)
