"""
DDL operations API.

Usage inside a migration file:

    from migrify import op
    import sqlalchemy as sa

    def upgrade() -> None:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("email", sa.String(255), nullable=False),
        )

    def downgrade() -> None:
        op.drop_table("users")
"""

from __future__ import annotations

import contextvars
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from typing import Self

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import Connection

# ---------------------------------------------------------------------------
# Context variable — holds the active Operations instance while a migration
# upgrade() / downgrade() function is running.
# ---------------------------------------------------------------------------
_current_ops: contextvars.ContextVar[Operations | None] = contextvars.ContextVar(
    "_current_ops", default=None
)


class BatchOperations:
    """
    Context manager returned by ``op.batch_alter_table()``.

    Collects column/constraint changes and applies them to the table.
    For SQLite (which doesn't support ALTER COLUMN), a table-rebuild
    strategy is used automatically.
    """

    def __init__(self, ops: Operations, table_name: str, schema: str | None) -> None:
        self._ops = ops
        self._table_name = table_name
        self._schema = schema
        self._pending_add_columns: list[sa.Column] = []
        self._pending_drop_columns: list[str] = []

    def add_column(self, column: sa.Column) -> None:
        self._pending_add_columns.append(column)

    def drop_column(self, column_name: str) -> None:
        self._pending_drop_columns.append(column_name)

    def _commit(self) -> None:
        for col in self._pending_add_columns:
            self._ops.add_column(self._table_name, col, schema=self._schema)
        for col_name in self._pending_drop_columns:
            self._ops.drop_column(self._table_name, col_name, schema=self._schema)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            self._commit()


class Operations:
    """
    Bound DDL operations executor.
    An instance wraps a live SQLAlchemy ``Connection`` and translates
    high-level operations into dialect-appropriate SQL.
    """

    def __init__(self, connection: Connection) -> None:
        self._conn = connection

    @property
    def connection(self) -> Connection:
        return self._conn

    # ------------------------------------------------------------------
    # Table operations
    # ------------------------------------------------------------------

    def create_table(
        self,
        table_name: str,
        *columns: sa.Column | sa.Constraint,
        schema: str | None = None,
        **kw: Any,
    ) -> sa.Table:
        """Create a new table and return the ``Table`` object."""
        metadata = sa.MetaData()
        table = sa.Table(table_name, metadata, *columns, schema=schema, **kw)
        table.create(self._conn)
        return table

    def drop_table(
        self,
        table_name: str,
        schema: str | None = None,
        checkfirst: bool = False,
    ) -> None:
        """Drop a table."""
        metadata = sa.MetaData()
        table = sa.Table(table_name, metadata, schema=schema)
        table.drop(self._conn, checkfirst=checkfirst)

    def rename_table(
        self,
        old_name: str,
        new_name: str,
        schema: str | None = None,
    ) -> None:
        """Rename a table."""
        prefix = f"{schema}." if schema else ""
        self._conn.execute(
            text(f"ALTER TABLE {prefix}{old_name} RENAME TO {new_name}")
        )

    # ------------------------------------------------------------------
    # Column operations
    # ------------------------------------------------------------------

    def add_column(
        self,
        table_name: str,
        column: sa.Column,
        schema: str | None = None,
    ) -> None:
        """Add a column to an existing table."""
        dialect = self._conn.dialect
        type_str = column.type.compile(dialect=dialect)
        null_clause = "NULL" if column.nullable else "NOT NULL"

        default_clause = ""
        if column.server_default is not None:
            default_clause = f" DEFAULT {column.server_default.arg}"

        preparer = dialect.identifier_preparer
        table_ref = (
            f"{preparer.quote_schema(schema)}.{preparer.quote(table_name)}"
            if schema
            else preparer.quote(table_name)
        )
        col_ref = preparer.quote(column.name)

        self._conn.execute(
            text(
                f"ALTER TABLE {table_ref} ADD COLUMN"
                f" {col_ref} {type_str} {null_clause}{default_clause}"
            )
        )

    def drop_column(
        self,
        table_name: str,
        column_name: str,
        schema: str | None = None,
    ) -> None:
        """Drop a column from an existing table."""
        dialect = self._conn.dialect
        preparer = dialect.identifier_preparer
        table_ref = (
            f"{preparer.quote_schema(schema)}.{preparer.quote(table_name)}"
            if schema
            else preparer.quote(table_name)
        )
        col_ref = preparer.quote(column_name)
        self._conn.execute(text(f"ALTER TABLE {table_ref} DROP COLUMN {col_ref}"))

    def alter_column(
        self,
        table_name: str,
        column_name: str,
        *,
        new_column_name: str | None = None,
        type_: sa.types.TypeEngine | None = None,
        nullable: bool | None = None,
        server_default: Any | None = None,
        schema: str | None = None,
    ) -> None:
        """
        Alter an existing column.

        This is a best-effort implementation that issues the most common
        ALTER COLUMN statements.  For SQLite (which does not support most
        ALTER COLUMN forms), consider using ``batch_alter_table`` or
        writing raw SQL via ``execute()``.
        """
        dialect = self._conn.dialect
        preparer = dialect.identifier_preparer
        table_ref = (
            f"{preparer.quote_schema(schema)}.{preparer.quote(table_name)}"
            if schema
            else preparer.quote(table_name)
        )
        col_ref = preparer.quote(column_name)

        if new_column_name is not None:
            new_ref = preparer.quote(new_column_name)
            self._conn.execute(
                text(f"ALTER TABLE {table_ref} RENAME COLUMN {col_ref} TO {new_ref}")
            )
            col_ref = new_ref

        if type_ is not None:
            type_str = type_.compile(dialect=dialect)
            dname = dialect.name
            if dname in ("postgresql",):
                self._conn.execute(
                    text(
                        f"ALTER TABLE {table_ref} ALTER COLUMN {col_ref}"
                        f" TYPE {type_str}"
                    )
                )
            elif dname in ("mysql", "mariadb"):
                null_clause = "" if nullable is None else ("NULL" if nullable else "NOT NULL")
                self._conn.execute(
                    text(
                        f"ALTER TABLE {table_ref} MODIFY COLUMN {col_ref}"
                        f" {type_str} {null_clause}"
                    )
                )
            else:
                raise NotImplementedError(
                    f"alter_column type change is not supported for dialect {dname!r}. "
                    "Use execute() to write dialect-specific SQL."
                )

        if nullable is not None and type_ is None:
            dname = dialect.name
            if dname in ("postgresql",):
                clause = "DROP NOT NULL" if nullable else "SET NOT NULL"
                self._conn.execute(
                    text(f"ALTER TABLE {table_ref} ALTER COLUMN {col_ref} {clause}")
                )

    # ------------------------------------------------------------------
    # Index operations
    # ------------------------------------------------------------------

    def create_index(
        self,
        index_name: str | None,
        table_name: str,
        columns: list[str],
        *,
        unique: bool = False,
        schema: str | None = None,
        **kw: Any,
    ) -> None:
        """Create an index on *table_name*."""
        metadata = sa.MetaData()
        col_objects = [sa.Column(c) for c in columns]
        table = sa.Table(table_name, metadata, *col_objects, schema=schema)
        index = sa.Index(index_name, *[table.c[c] for c in columns], unique=unique, **kw)
        index.create(self._conn)

    def drop_index(
        self,
        index_name: str,
        table_name: str | None = None,
        schema: str | None = None,
        if_exists: bool = False,
    ) -> None:
        """Drop an index by name."""
        dialect = self._conn.dialect
        preparer = dialect.identifier_preparer
        idx_ref = preparer.quote(index_name)
        if_clause = "IF EXISTS " if if_exists else ""
        # PostgreSQL/MySQL: DROP INDEX name; SQLite: DROP INDEX name
        # MSSQL: DROP INDEX table.name — handled separately
        if dialect.name == "mssql" and table_name:
            table_ref = preparer.quote(table_name)
            self._conn.execute(
                text(f"DROP INDEX {if_clause}{table_ref}.{idx_ref}")
            )
        else:
            self._conn.execute(text(f"DROP INDEX {if_clause}{idx_ref}"))

    # ------------------------------------------------------------------
    # Constraint operations
    # ------------------------------------------------------------------

    def create_foreign_key(
        self,
        constraint_name: str | None,
        source_table: str,
        referent_table: str,
        local_cols: list[str],
        remote_cols: list[str],
        *,
        ondelete: str | None = None,
        onupdate: str | None = None,
        schema: str | None = None,
        referent_schema: str | None = None,
    ) -> None:
        """Add a foreign key constraint via ALTER TABLE."""
        dialect = self._conn.dialect
        preparer = dialect.identifier_preparer

        src = (
            f"{preparer.quote_schema(schema)}.{preparer.quote(source_table)}"
            if schema
            else preparer.quote(source_table)
        )
        ref = (
            f"{preparer.quote_schema(referent_schema)}.{preparer.quote(referent_table)}"
            if referent_schema
            else preparer.quote(referent_table)
        )
        local_str = ", ".join(preparer.quote(c) for c in local_cols)
        remote_str = ", ".join(preparer.quote(c) for c in remote_cols)
        name_clause = f"CONSTRAINT {preparer.quote(constraint_name)} " if constraint_name else ""
        fk_sql = (
            f"ALTER TABLE {src} ADD {name_clause}"
            f"FOREIGN KEY ({local_str}) REFERENCES {ref} ({remote_str})"
        )
        if ondelete:
            fk_sql += f" ON DELETE {ondelete}"
        if onupdate:
            fk_sql += f" ON UPDATE {onupdate}"
        self._conn.execute(text(fk_sql))

    def drop_constraint(
        self,
        constraint_name: str,
        table_name: str,
        type_: str | None = None,
        schema: str | None = None,
    ) -> None:
        """Drop a named constraint."""
        dialect = self._conn.dialect
        preparer = dialect.identifier_preparer
        table_ref = (
            f"{preparer.quote_schema(schema)}.{preparer.quote(table_name)}"
            if schema
            else preparer.quote(table_name)
        )
        cname = preparer.quote(constraint_name)
        if dialect.name == "mysql":
            if type_ in ("foreignkey", "fk"):
                self._conn.execute(
                    text(f"ALTER TABLE {table_ref} DROP FOREIGN KEY {cname}")
                )
            else:
                self._conn.execute(
                    text(f"ALTER TABLE {table_ref} DROP INDEX {cname}")
                )
        else:
            self._conn.execute(
                text(f"ALTER TABLE {table_ref} DROP CONSTRAINT {cname}")
            )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def execute(self, sqltext: str | Any, parameters: dict | None = None) -> Any:
        """Execute arbitrary SQL."""
        stmt = text(sqltext) if isinstance(sqltext, str) else sqltext
        if parameters:
            return self._conn.execute(stmt, parameters)
        return self._conn.execute(stmt)

    def bulk_insert(self, table: sa.Table, rows: list[dict]) -> None:
        """Bulk-insert *rows* (list of dicts) into *table*."""
        if rows:
            self._conn.execute(table.insert(), rows)

    @contextmanager
    def batch_alter_table(
        self,
        table_name: str,
        schema: str | None = None,
    ) -> Generator[BatchOperations, None, None]:
        """
        Context manager for grouped column/constraint alterations.

        Example::

            with op.batch_alter_table("users") as batch_op:
                batch_op.add_column(sa.Column("phone", sa.String(20)))
                batch_op.drop_column("old_field")
        """
        batch = BatchOperations(self, table_name, schema)
        yield batch
        # __exit__ of BatchOperations applies changes


# ---------------------------------------------------------------------------
# Module-level proxy — looks up the active Operations from the context var.
# ---------------------------------------------------------------------------

class _OpProxy:
    """
    Transparent proxy for the active ``Operations`` instance.

    Import once at module level::

        from migrify import op

    Then use inside ``upgrade()`` / ``downgrade()`` — the proxy
    automatically delegates to the Operations instance set by the Migrator.
    """

    def __getattr__(self, name: str) -> Any:
        ops = _current_ops.get()
        if ops is None:
            raise RuntimeError(
                "No active migration context.  "
                "Transmute operations (op.*) must be called from within "
                "an upgrade() or downgrade() function."
            )
        return getattr(ops, name)

    def __repr__(self) -> str:  # pragma: no cover
        return "<transmute op proxy>"


op = _OpProxy()

__all__ = ["BatchOperations", "Operations", "_current_ops", "op"]

