from typing import BinaryIO

import boto3
from botocore.config import Config as BotocoreConfig
from botocore.exceptions import ClientError

from app.storage.base import StorageInterface


class MinIOStorage(StorageInterface):
    """S3-compatible storage backend.

    Works with local MinIO, Cloudflare R2, AWS S3, and any other S3-compatible
    store.  Pass ``endpoint_url`` as a full URL (e.g.
    ``https://<account>.r2.cloudflarestorage.com``) or leave it as ``None`` to
    build one from the legacy ``endpoint`` + ``secure`` parameters.

    ``region`` is used for SigV4 signing (Cloudflare R2 requires ``"auto"``).
    ``presign_endpoint_url`` overrides the endpoint used when generating
    presigned URLs — useful when the bucket has a separate public CDN hostname.
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool,
        endpoint_url: str | None = None,
        region: str = "auto",
        presign_endpoint_url: str | None = None,
    ):
        self.bucket = bucket
        self._region = region

        # Resolve the boto3 endpoint URL.
        if endpoint_url:
            resolved_endpoint = endpoint_url
        else:
            protocol = "https" if secure else "http"
            resolved_endpoint = f"{protocol}://{endpoint}"

        # Presigned-URL generation endpoint (may differ from the data endpoint).
        self._presign_endpoint_url = presign_endpoint_url or resolved_endpoint

        # Use SigV4 and path-style addressing for compatibility with MinIO / R2.
        cfg = BotocoreConfig(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        )

        self.client = boto3.client(
            "s3",
            endpoint_url=resolved_endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=cfg,
        )

        # Build a second client aimed at the presign endpoint when it differs.
        if self._presign_endpoint_url != resolved_endpoint:
            self._presign_client = boto3.client(
                "s3",
                endpoint_url=self._presign_endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
                config=cfg,
            )
        else:
            self._presign_client = self.client

        try:
            self.client.head_bucket(Bucket=bucket)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            if code in {"404", "NoSuchBucket"}:
                self.client.create_bucket(Bucket=bucket)
            else:
                raise

    # ------------------------------------------------------------------
    # Core StorageInterface implementation
    # ------------------------------------------------------------------

    def upload(self, key: str, source: BinaryIO, content_type: str) -> None:
        self.client.upload_fileobj(
            source, self.bucket, key, ExtraArgs={"ContentType": content_type}
        )

    def download(self, key: str) -> BinaryIO:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"]

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def get_metadata(self, key: str) -> dict:
        try:
            result = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchKey"}:
                raise FileNotFoundError(key) from exc
            raise
        return {
            "size": result["ContentLength"],
            "content_type": result.get("ContentType", "application/octet-stream"),
        }

    # ------------------------------------------------------------------
    # Presigned-URL support
    # ------------------------------------------------------------------

    def generate_presigned_put(self, key: str, content_type: str, expires: int) -> str:
        """Generate a presigned PUT URL for direct client upload."""
        url: str = self._presign_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=expires,
        )
        return url

    def head(self, key: str) -> dict:
        """Return {'size': int, 'content_type': str} or raise FileNotFoundError."""
        return self.get_metadata(key)
