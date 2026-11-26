from typing import BinaryIO

import boto3
from botocore.exceptions import ClientError

from app.storage.base import StorageInterface


class MinIOStorage(StorageInterface):
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool):
        protocol = "https" if secure else "http"
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=f"{protocol}://{endpoint}",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        try:
            self.client.head_bucket(Bucket=bucket)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            if code in {"404", "NoSuchBucket"}:
                self.client.create_bucket(Bucket=bucket)
            else:
                raise

    def upload(self, key: str, source: BinaryIO, content_type: str) -> None:
        self.client.upload_fileobj(source, self.bucket, key, ExtraArgs={"ContentType": content_type})

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
        result = self.client.head_object(Bucket=self.bucket, Key=key)
        return {
            "size": result["ContentLength"],
            "content_type": result.get("ContentType", "application/octet-stream"),
        }
