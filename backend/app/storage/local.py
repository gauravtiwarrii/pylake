from pathlib import Path
from typing import BinaryIO

from app.storage.base import StorageInterface


class LocalFileStorage(StorageInterface):
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if ".." in Path(key).parts or Path(key).is_absolute():
            raise ValueError("Invalid storage key")
        return self.root.joinpath(*Path(key).parts)

    def upload(self, key: str, source: BinaryIO, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as target:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)

    def download(self, key: str) -> BinaryIO:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.open("rb")

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def get_metadata(self, key: str) -> dict:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return {"size": path.stat().st_size, "content_type": "application/octet-stream"}

    def generate_presigned_put(self, key: str, content_type: str, expires: int) -> str:
        raise NotImplementedError(
            "Local filesystem storage does not support presigned PUT URLs. "
            "Set STORAGE_BACKEND=minio and configure STORAGE_ENDPOINT_URL to use direct uploads."
        )

    def head(self, key: str) -> dict:
        return self.get_metadata(key)
