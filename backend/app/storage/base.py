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
