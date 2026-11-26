from app.core.config import get_settings
from app.storage.local import LocalFileStorage
from app.storage.minio import MinIOStorage


def get_storage():
    settings = get_settings()
    if settings.storage_backend.lower() == "minio":
        return MinIOStorage(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
    return LocalFileStorage(settings.local_storage_dir)
