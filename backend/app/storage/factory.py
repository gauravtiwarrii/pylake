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
            endpoint_url=settings.storage_endpoint_url or None,
            region=settings.storage_region,
            presign_endpoint_url=settings.storage_public_endpoint_url or None,
        )
    return LocalFileStorage(settings.local_storage_dir)
