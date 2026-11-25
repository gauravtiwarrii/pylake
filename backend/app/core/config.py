from functools import lru_cache

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
    worker_stale_seconds: int = 90
    auth_secret: str = "change-this-secret-before-production"
    auth_cookie_name: str = "pylake_session"
    csrf_cookie_name: str = "pylake_csrf"
    session_ttl_hours: int = 24
    cookie_secure: bool = False
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "pylake"
    minio_secret_key: str = "pylake-local-secret"
    minio_bucket: str = "pylake"
    minio_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
