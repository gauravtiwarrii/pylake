"""Data Trust Passport rules and immutable score snapshots.

Revision ID: 20261127_0012
Revises: 20261127_0011
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261127_0012"
down_revision: Union[str, None] = "20261127_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("catalog_assets") as batch:
        batch.add_column(sa.Column("freshness_target_hours", sa.Integer(), nullable=True))
    op.create_table(
        "quality_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("column_name", sa.String(200), nullable=True),
        sa.Column("rule_type", sa.Enum("NOT_NULL", "UNIQUE", "RANGE", "REGEX", "ALLOWED_VALUES", "MIN_ROW_COUNT", name="quality_rule_type", native_enum=bind.dialect.name == "postgresql"), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("severity", sa.Enum("LOW", "MEDIUM", "HIGH", name="quality_rule_severity", native_enum=bind.dialect.name == "postgresql"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["catalog_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("workspace_id", "asset_id", "created_by"):
        op.create_index(f"ix_quality_rules_{col}", "quality_rules", [col])
    op.create_table(
        "trust_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=True),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("rule_results_json", sa.JSON(), nullable=False),
        sa.Column("limitations_json", sa.JSON(), nullable=False),
        sa.Column("sample_rows", sa.Integer(), nullable=False),
        sa.Column("total_rows", sa.BigInteger(), nullable=True),
        sa.Column("sampled", sa.Boolean(), nullable=False),
        sa.Column("trigger", sa.String(30), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["catalog_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["dataset_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("workspace_id", "asset_id", "version_id", "created_by"):
        op.create_index(f"ix_trust_snapshots_{col}", "trust_snapshots", [col])


def downgrade() -> None:
    for col in ("workspace_id", "asset_id", "version_id", "created_by"):
        op.drop_index(f"ix_trust_snapshots_{col}", table_name="trust_snapshots")
    op.drop_table("trust_snapshots")
    for col in ("workspace_id", "asset_id", "created_by"):
        op.drop_index(f"ix_quality_rules_{col}", table_name="quality_rules")
    op.drop_table("quality_rules")
    with op.batch_alter_table("catalog_assets") as batch:
        batch.drop_column("freshness_target_hours")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="quality_rule_type").drop(bind, checkfirst=True)
        sa.Enum(name="quality_rule_severity").drop(bind, checkfirst=True)
