"""
Schema comparison engine.

Compares a SQLAlchemy ``MetaData`` object (the *target* — your models)
against the live database schema (the *current* state) using SQLAlchemy's
``inspect()`` API.

Returns a list of ``Diff`` objects that describe what needs to change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine

# ---------------------------------------------------------------------------
# Diff data classes
# ---------------------------------------------------------------------------

@dataclass
class CreateTableDiff:
    table: sa.Table


@dataclass
class DropTableDiff:
    table_name: str
    schema: str | None = None


@dataclass
class AddColumnDiff:
    table_name: str
    column: sa.Column
    schema: str | None = None


@dataclass
class DropColumnDiff:
    table_name: str
    column_name: str
    schema: str | None = None


@dataclass
class AlterColumnDiff:
    table_name: str
    column_name: str
    changes: dict[str, Any]   # e.g. {"type": sa.Integer(), "nullable": False}
    schema: str | None = None


@dataclass
class CreateIndexDiff:
    index: sa.Index
    table_name: str
    schema: str | None = None


@dataclass
class DropIndexDiff:
    index_name: str
    table_name: str
    schema: str | None = None


@dataclass
class CreateForeignKeyDiff:
    constraint: sa.ForeignKeyConstraint
    table_name: str
    schema: str | None = None


@dataclass
class DropForeignKeyDiff:
    constraint_name: str
    table_name: str
    schema: str | None = None


Diff = (
    CreateTableDiff
    | DropTableDiff
    | AddColumnDiff
    | DropColumnDiff
    | AlterColumnDiff
    | CreateIndexDiff
    | DropIndexDiff
    | CreateForeignKeyDiff
    | DropForeignKeyDiff
)


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------

def _type_repr(t: sa.types.TypeEngine) -> str:
    return repr(t)


def _types_equivalent(a: sa.types.TypeEngine, b: sa.types.TypeEngine) -> bool:
    """Best-effort check whether two column types are semantically equivalent."""
    # Compare string representation of compiled types; not 100% accurate but
    # good enough for common cases.
    return type(a).__name__ == type(b).__name__


def _col_from_reflected(col_info: dict) -> sa.Column:
    """Build a Column from a dict returned by Inspector.get_columns()."""
    return sa.Column(
        col_info["name"],
        col_info["type"],
        nullable=col_info.get("nullable", True),
        server_default=col_info.get("default"),
        comment=col_info.get("comment"),
    )


# ---------------------------------------------------------------------------
# Main comparator
# ---------------------------------------------------------------------------

class SchemaComparator:
    """
    Compares *metadata* (your models) with the live DB schema.

    Parameters
    ----------
    engine:
        Active SQLAlchemy engine.
    metadata:
        Target schema (from your SQLAlchemy models).
    include_schemas:
        Set of schema names to consider.  ``None`` means the default schema.
    exclude_tables:
        Table names to skip entirely.
    """

    def __init__(
        self,
        engine: Engine,
        metadata: sa.MetaData,
        include_schemas: set[str | None] | None = None,
        exclude_tables: set[str] | None = None,
    ) -> None:
        self._engine = engine
        self._metadata = metadata
        self._include_schemas: set[str | None] = include_schemas or {None}
        self._exclude_tables: set[str] = exclude_tables or set()

    def compare(self) -> list[Diff]:
        """Run the comparison and return detected diffs."""
        diffs: list[Diff] = []
        inspector = sa_inspect(self._engine)

        for schema in self._include_schemas:
            db_table_names: set[str] = set(inspector.get_table_names(schema=schema))
            model_tables: dict[str, sa.Table] = {
                t.name: t
                for t in self._metadata.sorted_tables
                if t.schema == schema and t.name not in self._exclude_tables
            }

            # ── Tables that exist in models but not in DB → CREATE
            for name, table in model_tables.items():
                if name not in db_table_names:
                    diffs.append(CreateTableDiff(table=table))

            # ── Tables that exist in DB but not in models → DROP
            for name in db_table_names:
                if name not in model_tables and name not in self._exclude_tables:
                    diffs.append(DropTableDiff(table_name=name, schema=schema))

            # ── Tables present in both → compare columns & indexes
            for name in db_table_names & set(model_tables):
                model_table = model_tables[name]
                diffs.extend(
                    self._compare_table(inspector, model_table, schema)
                )

        return diffs

    def _compare_table(
        self,
        inspector,
        model_table: sa.Table,
        schema: str | None,
    ) -> list[Diff]:
        diffs: list[Diff] = []
        table_name = model_table.name

        # ── Columns ──────────────────────────────────────────────────
        db_cols: dict[str, dict] = {
            c["name"]: c
            for c in inspector.get_columns(table_name, schema=schema)
        }
        model_cols: dict[str, sa.Column] = {
            c.name: c for c in model_table.columns
        }

        for col_name, model_col in model_cols.items():
            if col_name not in db_cols:
                diffs.append(
                    AddColumnDiff(
                        table_name=table_name,
                        column=model_col,
                        schema=schema,
                    )
                )
            else:
                db_col_info = db_cols[col_name]
                changes = self._diff_column(model_col, db_col_info)
                if changes:
                    diffs.append(
                        AlterColumnDiff(
                            table_name=table_name,
                            column_name=col_name,
                            changes=changes,
                            schema=schema,
                        )
                    )

        for col_name in db_cols:
            if col_name not in model_cols:
                diffs.append(
                    DropColumnDiff(
                        table_name=table_name,
                        column_name=col_name,
                        schema=schema,
                    )
                )

        # ── Indexes ──────────────────────────────────────────────────
        db_indexes: dict[str, dict] = {
            idx["name"]: idx
            for idx in inspector.get_indexes(table_name, schema=schema)
            if idx.get("name")
        }
        model_indexes: dict[str, sa.Index] = {
            idx.name: idx
            for idx in model_table.indexes
            if idx.name
        }

        for idx_name, model_idx in model_indexes.items():
            if idx_name not in db_indexes:
                diffs.append(
                    CreateIndexDiff(
                        index=model_idx,
                        table_name=table_name,
                        schema=schema,
                    )
                )

        for idx_name in db_indexes:
            if idx_name not in model_indexes:
                diffs.append(
                    DropIndexDiff(
                        index_name=idx_name,
                        table_name=table_name,
                        schema=schema,
                    )
                )

        # ── Foreign keys ─────────────────────────────────────────────
        db_fks: dict[str, dict] = {
            fk.get("name", ""): fk
            for fk in inspector.get_foreign_keys(table_name, schema=schema)
        }
        model_fks: dict[str, sa.ForeignKeyConstraint] = {}
        for constraint in model_table.constraints:
            if isinstance(constraint, sa.ForeignKeyConstraint) and constraint.name:
                model_fks[constraint.name] = constraint

        for fk_name, model_fk in model_fks.items():
            if fk_name not in db_fks:
                diffs.append(
                    CreateForeignKeyDiff(
                        constraint=model_fk,
                        table_name=table_name,
                        schema=schema,
                    )
                )

        for fk_name in db_fks:
            if fk_name and fk_name not in model_fks:
                diffs.append(
                    DropForeignKeyDiff(
                        constraint_name=fk_name,
                        table_name=table_name,
                        schema=schema,
                    )
                )

        return diffs

    @staticmethod
    def _diff_column(model_col: sa.Column, db_info: dict) -> dict[str, Any]:
        """Return a dict of changed attributes between model column and DB column."""
        changes: dict[str, Any] = {}

        if not _types_equivalent(model_col.type, db_info["type"]):
            changes["type"] = model_col.type

        model_nullable = model_col.nullable if model_col.nullable is not None else True
        db_nullable = db_info.get("nullable", True)
        if model_nullable != db_nullable:
            changes["nullable"] = model_nullable

        return changes

