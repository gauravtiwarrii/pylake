import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_value() -> uuid.UUID:
    return uuid.uuid4()


class WorkspaceRole(str, enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


class DatasetStatus(str, enum.Enum):
    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class LakehouseLayer(str, enum.Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class LakehouseVersionStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TransformationStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class QueryExecutionStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class PipelineStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class RunStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StepStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class QualityRuleType(str, enum.Enum):
    NOT_NULL = "NOT_NULL"
    UNIQUE = "UNIQUE"
    RANGE = "RANGE"
    REGEX = "REGEX"
    ALLOWED_VALUES = "ALLOWED_VALUES"
    MIN_ROW_COUNT = "MIN_ROW_COUNT"


class QualityRuleSeverity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())

    owned_workspaces: Mapped[list["Workspace"]] = relationship(back_populates="owner", cascade="all")
    memberships: Mapped[list["WorkspaceMember"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list["AuthSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    ai_conversations: Mapped[list["AIConversation"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    ai_usage_events: Mapped[list["AIUsage"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())

    owner: Mapped["User"] = relationship(back_populates="owned_workspaces")
    members: Mapped[list["WorkspaceMember"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    ai_conversations: Mapped[list["AIConversation"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    ai_usage_events: Mapped[list["AIUsage"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    role: Mapped[WorkspaceRole] = mapped_column(Enum(WorkspaceRole, name="workspace_role"), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="memberships")
    workspace: Mapped["Workspace"] = relationship(back_populates="members")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="sessions")


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_format: Mapped[str] = mapped_column(String(20), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    schema_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    column_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ingestion_status: Mapped[DatasetStatus] = mapped_column(Enum(DatasetStatus, name="dataset_status"), default=DatasetStatus.PENDING, nullable=False)
    ingestion_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())


class LakehouseTable(Base):
    __tablename__ = "lakehouse_tables"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_lakehouse_table_workspace_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_layer: Mapped[LakehouseLayer] = mapped_column(Enum(LakehouseLayer, name="lakehouse_layer"), default=LakehouseLayer.BRONZE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version_number", name="uq_dataset_version_number"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True, nullable=False)
    lakehouse_table_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lakehouse_tables.id", ondelete="SET NULL"), index=True, nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    layer: Mapped[LakehouseLayer] = mapped_column(Enum(LakehouseLayer, name="lakehouse_layer"), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    schema_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    column_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    file_format: Mapped[str] = mapped_column(String(20), nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    status: Mapped[LakehouseVersionStatus] = mapped_column(Enum(LakehouseVersionStatus, name="lakehouse_version_status"), default=LakehouseVersionStatus.PENDING, nullable=False)


class StorageObject(Base):
    __tablename__ = "storage_objects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True, nullable=True)
    version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"), index=True, nullable=True)
    layer: Mapped[LakehouseLayer] = mapped_column(Enum(LakehouseLayer, name="lakehouse_layer"), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class TransformationRecord(Base):
    __tablename__ = "transformation_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True, nullable=False)
    source_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"), index=True, nullable=False)
    output_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dataset_versions.id", ondelete="SET NULL"), index=True, nullable=True)
    transformation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    configuration_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    execution_status: Mapped[TransformationStatus] = mapped_column(Enum(TransformationStatus, name="transformation_status"), default=TransformationStatus.PENDING, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class QueryHistory(Base):
    __tablename__ = "query_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    query_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sql_text: Mapped[str] = mapped_column(Text, nullable=False)
    execution_status: Mapped[QueryExecutionStatus] = mapped_column(Enum(QueryExecutionStatus, name="query_execution_status"), nullable=False)
    execution_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows_returned: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class AskHistory(Base):
    __tablename__ = "ask_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_type: Mapped[str] = mapped_column(String(20), nullable=False)
    sql_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class SavedQuery(Base):
    __tablename__ = "saved_queries"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_saved_query_workspace_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sql_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())


class CatalogAsset(Base):
    __tablename__ = "catalog_assets"
    __table_args__ = (
        UniqueConstraint("workspace_id", "asset_type", "dataset_id", name="uq_catalog_dataset_asset"),
        UniqueConstraint("workspace_id", "asset_type", "lakehouse_table_id", name="uq_catalog_table_asset"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    tags_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True, nullable=True)
    lakehouse_table_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lakehouse_tables.id", ondelete="CASCADE"), index=True, nullable=True)
    format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    layer: Mapped[str | None] = mapped_column(String(20), nullable=True)
    freshness_target_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())


class CatalogColumn(Base):
    __tablename__ = "catalog_columns"
    __table_args__ = (UniqueConstraint("asset_id", "name", name="uq_catalog_asset_column"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog_assets.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    data_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    glossary_term: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())


class CatalogProfile(Base):
    __tablename__ = "catalog_profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog_assets.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dataset_versions.id", ondelete="SET NULL"), index=True, nullable=True)
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    column_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    statistics_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())


class CatalogSchemaHistory(Base):
    __tablename__ = "catalog_schema_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog_assets.id", ondelete="CASCADE"), index=True, nullable=False)
    version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dataset_versions.id", ondelete="SET NULL"), index=True, nullable=True)
    schema_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class QualityRule(Base):
    __tablename__ = "quality_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog_assets.id", ondelete="CASCADE"), index=True, nullable=False)
    column_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rule_type: Mapped[QualityRuleType] = mapped_column(Enum(QualityRuleType, name="quality_rule_type"), nullable=False)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    severity: Mapped[QualityRuleSeverity] = mapped_column(Enum(QualityRuleSeverity, name="quality_rule_severity"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())


class TrustSnapshot(Base):
    __tablename__ = "trust_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog_assets.id", ondelete="CASCADE"), index=True, nullable=False)
    version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dataset_versions.id", ondelete="SET NULL"), index=True, nullable=True)
    overall_score: Mapped[float | None] = mapped_column(nullable=True)
    metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    rule_results_json: Mapped[list] = mapped_column(JSON, nullable=False)
    limitations_json: Mapped[list] = mapped_column(JSON, nullable=False)
    sample_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    total_rows: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sampled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    trigger: Mapped[str] = mapped_column(String(30), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)


class LineageEdge(Base):
    __tablename__ = "lineage_edges"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    source_asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("catalog_assets.id", ondelete="CASCADE"), index=True, nullable=True)
    target_asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("catalog_assets.id", ondelete="CASCADE"), index=True, nullable=True)
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[str] = mapped_column(String(200), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str] = mapped_column(String(200), nullable=False)
    execution_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class Pipeline(Base):
    __tablename__ = "pipelines"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_pipeline_workspace_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[PipelineStatus] = mapped_column(Enum(PipelineStatus, name="pipeline_status"), default=PipelineStatus.DRAFT, nullable=False)
    configuration_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())


class PipelineStep(Base):
    __tablename__ = "pipeline_steps"
    __table_args__ = (UniqueConstraint("pipeline_id", "execution_order", name="uq_pipeline_step_order"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), index=True, nullable=False)
    step_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    step_type: Mapped[str] = mapped_column(String(50), nullable=False)
    configuration_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    dependencies_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    execution_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (UniqueConstraint("schedule_id", "scheduled_at", name="uq_pipeline_schedule_occurrence"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), index=True, nullable=False)
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pipeline_schedules.id", ondelete="SET NULL"), index=True, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus, name="pipeline_run_status"), default=RunStatus.QUEUED, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    failure_class: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class PipelineStepRun(Base):
    __tablename__ = "pipeline_step_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True, nullable=False)
    pipeline_step_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_steps.id", ondelete="CASCADE"), index=True, nullable=False)
    status: Mapped[StepStatus] = mapped_column(Enum(StepStatus, name="pipeline_step_status"), default=StepStatus.PENDING, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows_processed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class PipelineSchedule(Base):
    __tablename__ = "pipeline_schedules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), index=True, nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    cron_expression: Mapped[str] = mapped_column(String(200), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), default="UTC", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    worker_id: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    active_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="SET NULL"), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ONLINE", nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, default=utcnow, server_default=func.now())


class RateLimitEvent(Base):
    __tablename__ = "rate_limit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    scope_key: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    endpoint: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, default=utcnow, server_default=func.now())


class AIConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())

    workspace: Mapped["Workspace"] = relationship(back_populates="ai_conversations")
    user: Mapped["User"] = relationship(back_populates="ai_conversations")
    messages: Mapped[list["AIMessage"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")
    usage_events: Mapped[list["AIUsage"]] = relationship(back_populates="conversation")


class AIMessage(Base):
    __tablename__ = "ai_messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    conversation: Mapped["AIConversation"] = relationship(back_populates="messages")


class AIUsage(Base):
    __tablename__ = "ai_usage"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_conversations.id", ondelete="SET NULL"), index=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    workspace: Mapped["Workspace"] = relationship(back_populates="ai_usage_events")
    user: Mapped["User"] = relationship(back_populates="ai_usage_events")
    conversation: Mapped["AIConversation | None"] = relationship(back_populates="usage_events")


class AIRecommendation(Base):
    __tablename__ = "ai_recommendations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    page_type: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    expected_impact: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_action_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)
    required_permissions_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PROPOSED", index=True, nullable=False)
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())


class AutopilotPlanStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PREVIEWED = "PREVIEWED"
    APPROVED = "APPROVED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AutopilotStepStatus(str, enum.Enum):
    PENDING = "PENDING"
    SKIPPED = "SKIPPED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AutopilotRiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AutopilotPlan(Base):
    __tablename__ = "autopilot_plans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AutopilotPlanStatus] = mapped_column(
        Enum(AutopilotPlanStatus, name="autopilot_plan_status"),
        default=AutopilotPlanStatus.DRAFT,
        index=True,
        nullable=False,
    )
    plan_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())

    steps: Mapped[list["AutopilotStep"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="AutopilotStep.step_order",
    )


class AutopilotStep(Base):
    __tablename__ = "autopilot_steps"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_value)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("autopilot_plans.id", ondelete="CASCADE"), index=True, nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    action_key: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    arguments_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    preview_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk_level: Mapped[AutopilotRiskLevel] = mapped_column(
        Enum(AutopilotRiskLevel, name="autopilot_risk_level"),
        default=AutopilotRiskLevel.LOW,
        nullable=False,
    )
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[AutopilotStepStatus] = mapped_column(
        Enum(AutopilotStepStatus, name="autopilot_step_status"),
        default=AutopilotStepStatus.PENDING,
        index=True,
        nullable=False,
    )
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    plan: Mapped["AutopilotPlan"] = relationship(back_populates="steps")
