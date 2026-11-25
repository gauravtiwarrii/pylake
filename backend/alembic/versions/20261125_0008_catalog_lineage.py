"""Catalog documentation profiling and lineage

Revision ID: 20261125_0008
Revises: 20261125_0007
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261125_0008"
down_revision: Union[str, None] = "20261125_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalog_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("asset_type", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=True),
        sa.Column("lakehouse_table_id", sa.Uuid(), nullable=True),
        sa.Column("format", sa.String(length=20), nullable=True),
        sa.Column("layer", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lakehouse_table_id"], ["lakehouse_tables.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "asset_type", "dataset_id", name="uq_catalog_dataset_asset"),
        sa.UniqueConstraint("workspace_id", "asset_type", "lakehouse_table_id", name="uq_catalog_table_asset"),
    )
    op.create_index("ix_catalog_assets_workspace_id", "catalog_assets", ["workspace_id"], unique=False)
    op.create_index("ix_catalog_assets_owner_id", "catalog_assets", ["owner_id"], unique=False)
    op.create_index("ix_catalog_assets_asset_type", "catalog_assets", ["asset_type"], unique=False)

    op.create_table(
        "catalog_columns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("data_type", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("business_name", sa.String(length=200), nullable=True),
        sa.Column("glossary_term", sa.String(length=200), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["catalog_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "name", name="uq_catalog_asset_column"),
    )
    op.create_index("ix_catalog_columns_asset_id", "catalog_columns", ["asset_id"], unique=False)

    op.create_table(
        "catalog_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=True),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("column_count", sa.Integer(), nullable=True),
        sa.Column("statistics_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["catalog_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["dataset_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", name="uq_catalog_profile_asset"),
    )
    op.create_index("ix_catalog_profiles_asset_id", "catalog_profiles", ["asset_id"], unique=True)
    op.create_index("ix_catalog_profiles_version_id", "catalog_profiles", ["version_id"], unique=False)

    op.create_table(
        "catalog_schema_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=True),
        sa.Column("schema_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["catalog_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["dataset_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_catalog_schema_history_asset_id", "catalog_schema_history", ["asset_id"], unique=False)

    op.create_table(
        "lineage_edges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_asset_id", sa.Uuid(), nullable=True),
        sa.Column("target_asset_id", sa.Uuid(), nullable=True),
        sa.Column("relation_type", sa.String(length=50), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.String(length=200), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.String(length=200), nullable=False),
        sa.Column("execution_status", sa.String(length=20), nullable=True),
        sa.Column("execution_id", sa.String(length=200), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_asset_id"], ["catalog_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_asset_id"], ["catalog_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lineage_edges_workspace_id", "lineage_edges", ["workspace_id"], unique=False)
    op.create_index("ix_lineage_edges_source_asset_id", "lineage_edges", ["source_asset_id"], unique=False)
    op.create_index("ix_lineage_edges_target_asset_id", "lineage_edges", ["target_asset_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_lineage_edges_target_asset_id", table_name="lineage_edges")
    op.drop_index("ix_lineage_edges_source_asset_id", table_name="lineage_edges")
    op.drop_index("ix_lineage_edges_workspace_id", table_name="lineage_edges")
    op.drop_table("lineage_edges")
    op.drop_index("ix_catalog_schema_history_asset_id", table_name="catalog_schema_history")
    op.drop_table("catalog_schema_history")
    op.drop_index("ix_catalog_profiles_version_id", table_name="catalog_profiles")
    op.drop_index("ix_catalog_profiles_asset_id", table_name="catalog_profiles")
    op.drop_table("catalog_profiles")
    op.drop_index("ix_catalog_columns_asset_id", table_name="catalog_columns")
    op.drop_table("catalog_columns")
    op.drop_index("ix_catalog_assets_asset_type", table_name="catalog_assets")
    op.drop_index("ix_catalog_assets_owner_id", table_name="catalog_assets")
    op.drop_index("ix_catalog_assets_workspace_id", table_name="catalog_assets")
    op.drop_table("catalog_assets")
