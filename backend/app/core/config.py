from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "PyLake"
    app_env: str = "local"
    api_v1_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:3000"
    database_url: str = "sqlite:///./pylake.db"
    local_storage_dir: str = "./storage"
    max_upload_size_bytes: int = 100 * 1024 * 1024
    storage_backend: str = "local"
    parquet_compression: str = "snappy"
    sql_query_timeout_seconds: int = 30
    sql_max_returned_rows: int = 1000
    sql_max_result_bytes: int = 10 * 1024 * 1024
    pipeline_job_claim_seconds: int = 300
    pipeline_worker_poll_seconds: int = 2
    log_level: str = "INFO"
    auth_rate_limit_attempts: int = 5
    auth_rate_limit_window_seconds: int = 900
    pipeline_step_timeout_seconds: int = 300
    pipeline_max_retries: int = 3
    trust_sample_rows: int = Field(default=100000, ge=1, le=100000)
    worker_stale_seconds: int = 90
    auth_secret: str = "change-this-secret-before-production"
    auth_cookie_name: str = "pylake_session"
    csrf_cookie_name: str = "pylake_csrf"
    session_ttl_hours: int = 24
    cookie_secure: bool = False
    # S3-compatible object storage (MinIO, Cloudflare R2, AWS S3, …).
    # STORAGE_BACKEND=minio activates boto3-based storage for any S3-compatible endpoint.
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "pylake"
    minio_secret_key: str = "pylake-local-secret"
    minio_bucket: str = "pylake"
    minio_secure: bool = False
    # Optional: full endpoint URL for the boto3 client, e.g.
    #   https://<account>.r2.cloudflarestorage.com
    # Falls back to building from minio_endpoint + minio_secure when not set.
    storage_endpoint_url: str | None = None
    # Region used for SigV4 signing. Cloudflare R2 requires "auto".
    storage_region: str = "auto"
    # Optional separate public endpoint for presigned URL generation (CDN / R2 public bucket).
    # Leave unset to use storage_endpoint_url.
    storage_public_endpoint_url: str | None = None
    # Enable the direct-to-storage upload flow (presigned PUT URLs).
    direct_upload_enabled: bool = False
    # Presigned URL lifetime in seconds.
    direct_upload_url_ttl_seconds: int = 900
    ai_provider: str = "disabled"
    ai_base_url: str = ""
    ai_api_key: SecretStr | None = None
    nvidia_api_key: SecretStr | None = None
    ai_model: str = "gpt-4o-mini"
    ai_timeout_seconds: float = Field(default=45, gt=0, le=300)
    ai_max_retries: int = Field(default=1, ge=0, le=5)
    ai_max_output_tokens: int = Field(default=4096, ge=1, le=8192)
    ai_temperature: float = Field(default=0.7, ge=0, le=2)
    ai_top_p: float = Field(default=0.95, gt=0, le=1)
    ai_enable_thinking: bool = True
    ai_reasoning_budget: int = Field(default=2048, ge=0, le=8192)
    ai_max_context_chars: int = Field(default=12000, ge=1000, le=100000)
    ai_max_input_chars: int = Field(default=30000, ge=12000, le=100000)
    ai_max_history_messages: int = Field(default=12, ge=1, le=50)
    ai_rate_limit_requests: int = Field(default=30, ge=1, le=10000)
    ai_rate_limit_window_seconds: int = Field(default=3600, ge=1, le=86400)
    ai_daily_token_limit: int = Field(default=100000, ge=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
