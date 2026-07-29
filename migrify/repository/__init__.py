"""Abstract interface for the migration tracking repository."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List


class MigrationRecord:
    """A single row from the migrations tracking table."""

    __slots__ = ("id", "migration", "batch")

    def __init__(self, id: int, migration: str, batch: int) -> None:
        self.id = id
        self.migration = migration
        self.batch = batch

    def __repr__(self) -> str:
        return f"MigrationRecord(id={self.id}, migration={self.migration!r}, batch={self.batch})"


class MigrationRepositoryInterface(ABC):
    """
    Defines the contract for the migrations tracking backend.
    The default implementation uses a SQL table, but custom backends
    (e.g. file-based, Redis) can be plugged in.
    """

    @abstractmethod
    def create_repository(self) -> None:
        """Create the underlying storage (e.g. the migrations table)."""

    @abstractmethod
    def repository_exists(self) -> bool:
        """Return True if the storage has already been initialised."""

    @abstractmethod
    def get_ran(self) -> List[str]:
        """Return migration names that have already been applied, ordered by batch then name."""

    @abstractmethod
    def get_last_batch(self) -> List[str]:
        """Return migration names belonging to the last batch (in reverse run order)."""

    @abstractmethod
    def get_last_batch_number(self) -> int:
        """Return the highest batch number recorded, or 0 if empty."""

    @abstractmethod
    def get_next_batch_number(self) -> int:
        """Return the batch number to use for the next migrate run."""

    @abstractmethod
    def log(self, migration: str, batch: int) -> None:
        """Record that *migration* was applied as part of *batch*."""

    @abstractmethod
    def delete(self, migration: str) -> None:
        """Remove the record for *migration* (called during rollback)."""

    @abstractmethod
    def get_all(self) -> List[MigrationRecord]:
        """Return all records, ordered by batch then migration name."""

