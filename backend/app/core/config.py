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
