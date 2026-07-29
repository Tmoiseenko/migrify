"""
SQL-backed migration repository.

Stores applied migrations in a table with the following schema:

    CREATE TABLE migrations (
        id        INTEGER  PRIMARY KEY AUTOINCREMENT,
        migration VARCHAR(255) NOT NULL,
        batch     INTEGER      NOT NULL
    );

This is intentionally identical to Laravel's migrations table so the
concept (and the mental model) is identical.
"""

from __future__ import annotations

from typing import List

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from migrify.repository import MigrationRecord, MigrationRepositoryInterface


class DatabaseMigrationRepository(MigrationRepositoryInterface):
    """Persists migration history in a relational database table."""

    def __init__(self, engine: Engine, table_name: str = "migrations") -> None:
        self._engine = engine
        self._table_name = table_name
        self._meta = sa.MetaData()
        self._table = sa.Table(
            table_name,
            self._meta,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("migration", sa.String(255), nullable=False),
            sa.Column("batch", sa.Integer, nullable=False),
        )

    # ------------------------------------------------------------------
    # MigrationRepositoryInterface
    # ------------------------------------------------------------------

    def create_repository(self) -> None:
        self._meta.create_all(self._engine)

    def repository_exists(self) -> bool:
        insp = sa.inspect(self._engine)
        return insp.has_table(self._table_name)

    def get_ran(self) -> List[str]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(self._table.c.migration).order_by(
                    self._table.c.batch, self._table.c.migration
                )
            )
            return [r[0] for r in rows]

    def get_last_batch(self) -> List[str]:
        batch_num = self.get_last_batch_number()
        if batch_num == 0:
            return []
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(self._table.c.migration)
                .where(self._table.c.batch == batch_num)
                .order_by(self._table.c.id.desc())
            )
            return [r[0] for r in rows]

    def get_last_batch_number(self) -> int:
        with self._engine.connect() as conn:
            result = conn.execute(sa.select(sa.func.max(self._table.c.batch)))
            value = result.scalar()
            return value if value is not None else 0

    def get_next_batch_number(self) -> int:
        return self.get_last_batch_number() + 1

    def log(self, migration: str, batch: int) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                sa.insert(self._table).values(migration=migration, batch=batch)
            )

    def delete(self, migration: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                sa.delete(self._table).where(self._table.c.migration == migration)
            )

    def get_all(self) -> List[MigrationRecord]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(self._table).order_by(
                    self._table.c.batch, self._table.c.migration
                )
            )
            return [MigrationRecord(r.id, r.migration, r.batch) for r in rows]

