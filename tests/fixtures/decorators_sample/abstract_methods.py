"""Abstract method fixture for entry-point detection."""
from abc import ABC, abstractmethod


class Repository(ABC):
    @abstractmethod
    def find_by_id(self, item_id: str) -> object:
        ...

    @abstractmethod
    def save(self, entity: object) -> None:
        ...

    def _internal(self) -> None:  # noqa: B027 - intentional non-abstract helper for test fixture
        pass
