from abc import ABC, abstractmethod
from typing import BinaryIO


class StorageInterface(ABC):
    @abstractmethod
    def upload(self, key: str, source: BinaryIO, content_type: str) -> None:
        pass

    @abstractmethod
    def download(self, key: str) -> BinaryIO:
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        pass

    @abstractmethod
    def get_metadata(self, key: str) -> dict:
        pass

    def generate_presigned_put(self, key: str, content_type: str, expires: int) -> str:
        """Return a presigned PUT URL for direct client-to-storage upload.

        Raises NotImplementedError for backends that do not support presigned URLs
        (e.g. LocalFileStorage).
        """
        raise NotImplementedError("This storage backend does not support presigned PUT URLs")

    def head(self, key: str) -> dict:
        """Return object metadata {'size': int, 'content_type': str}.

        Raises FileNotFoundError if the object does not exist.
        Default implementation delegates to get_metadata().
        """
        return self.get_metadata(key)
