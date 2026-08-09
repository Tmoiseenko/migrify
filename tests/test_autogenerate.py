"""Tests for autogenerate (compare + render)."""

from __future__ import annotations

import sqlalchemy as sa

from migrify.autogenerate.api import compare_metadata, generate_migration_content
from migrify.autogenerate.compare import (
    AddColumnDiff,
    CreateTableDiff,
    DropColumnDiff,
    DropTableDiff,
)
from migrify.autogenerate.compare import AlterColumnDiff, _types_equivalent
from migrify.autogenerate.render import render_column, render_type


class TestTypesEquivalent:
    def test_same_generic_types(self):
        assert _types_equivalent(sa.Integer(), sa.Integer())

    def test_dialect_subclass_equivalent_to_generic(self):
        from sqlalchemy.dialects.postgresql import INTEGER as PG_INTEGER
        assert _types_equivalent(PG_INTEGER(), sa.Integer())
        assert _types_equivalent(sa.Integer(), PG_INTEGER())

    def test_sql_standard_aliases_equivalent(self):
        # DECIMAL and NUMERIC are both aliases of Numeric
        assert _types_equivalent(sa.DECIMAL(10, 2), sa.Numeric(10, 2))
        assert _types_equivalent(sa.NUMERIC(10, 2), sa.Numeric(10, 2))
        assert _types_equivalent(sa.DECIMAL(10, 3), sa.NUMERIC(10, 3))

    def test_varchar_equivalent_to_string(self):
        assert _types_equivalent(sa.VARCHAR(100), sa.String(100))

    def test_different_types_not_equivalent(self):
        assert not _types_equivalent(sa.Integer(), sa.String())
        assert not _types_equivalent(sa.String(), sa.DateTime())


class TestRenderColumnServerDefault:
    def test_server_default_string(self):
        col = sa.Column("created_at", sa.DateTime(), server_default="now()")
        result = render_column(col, indent=0).rstrip(",")
        assert "server_default='now()'" in result

    def test_server_default_func_now(self):
        col = sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now())
        result = render_column(col, indent=0).rstrip(",")
        assert "sa.text(" in result
        assert "<" not in result  # no Python object repr leaked

    def test_no_server_default(self):
        col = sa.Column("name", sa.String())
        result = render_column(col, indent=0)
        assert "server_default" not in result


class TestRenderType:
    def test_integer(self):
        assert render_type(sa.Integer()) == "sa.Integer()"

    def test_string_with_length(self):
        assert render_type(sa.String(255)) == "sa.String(length=255)"

    def test_text(self):
        assert render_type(sa.Text()) == "sa.Text()"

    def test_boolean(self):
        assert render_type(sa.Boolean()) == "sa.Boolean()"

    def test_datetime(self):
        assert render_type(sa.DateTime()) == "sa.DateTime()"


class TestCompareMetadata:
    def test_no_diff_when_synced(self, engine):
        meta = sa.MetaData()
        sa.Table(
            "items",
            meta,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(100)),
        )
        meta.create_all(engine)  # sync DB to models

        diffs = compare_metadata(engine, meta)
        # The migrations table is not in meta → DropTableDiff for it
        # but items is in sync
        table_diffs = [d for d in diffs if isinstance(d, CreateTableDiff)]
        assert table_diffs == []

    def test_detects_new_table(self, engine):
        meta = sa.MetaData()
        sa.Table(
            "brand_new",
            meta,
            sa.Column("id", sa.Integer(), primary_key=True),
        )
        # DB has nothing

        diffs = compare_metadata(engine, meta)
        new_tables = [d for d in diffs if isinstance(d, CreateTableDiff)]
        assert any(d.table.name == "brand_new" for d in new_tables)

    def test_detects_extra_table_in_db(self, engine):
        # Create a table in DB that is NOT in metadata
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE orphan (id INTEGER PRIMARY KEY)"))

        meta = sa.MetaData()  # empty metadata

        diffs = compare_metadata(engine, meta)
        drop_diffs = [d for d in diffs if isinstance(d, DropTableDiff)]
        assert any(d.table_name == "orphan" for d in drop_diffs)

    def test_detects_new_column(self, engine):
        # Create table in DB with fewer columns
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))

        # Model has an extra column
        meta = sa.MetaData()
        sa.Table(
            "users",
            meta,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("email", sa.String(255)),  # new
        )

        diffs = compare_metadata(engine, meta)
        add_cols = [d for d in diffs if isinstance(d, AddColumnDiff)]
        assert any(d.column.name == "email" for d in add_cols)

    def test_detects_removed_column(self, engine):
        # Create table in DB with extra column
        with engine.begin() as conn:
            conn.execute(sa.text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, old_col TEXT)"
            ))

        # Model does NOT have old_col
        meta = sa.MetaData()
        sa.Table("users", meta, sa.Column("id", sa.Integer(), primary_key=True))

        diffs = compare_metadata(engine, meta)
        drop_cols = [d for d in diffs if isinstance(d, DropColumnDiff)]
        assert any(d.column_name == "old_col" for d in drop_cols)

    def test_no_false_alter_column_for_dialect_types(self, engine):
        # Ensure that reflected dialect-specific types (e.g. INTEGER vs Integer)
        # are not treated as a type difference
        with engine.begin() as conn:
            conn.execute(sa.text(
                "CREATE TABLE items (id INTEGER PRIMARY KEY, qty INTEGER, name TEXT)"
            ))

        meta = sa.MetaData()
        sa.Table(
            "items",
            meta,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("qty", sa.Integer()),
            sa.Column("name", sa.Text()),
        )

        diffs = compare_metadata(engine, meta)
        # No diffs with type changes — dialect types must be treated as equivalent
        type_alter_diffs = [
            d for d in diffs
            if isinstance(d, AlterColumnDiff) and "type" in d.changes
        ]
        assert type_alter_diffs == []


class TestGenerateMigrationContent:
    def test_generates_create_table_in_upgrade(self, engine):
        meta = sa.MetaData()
        sa.Table(
            "products",
            meta,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("title", sa.String(200)),
        )

        upgrade_body, downgrade_body = generate_migration_content(engine, meta)

        assert "op.create_table" in upgrade_body
        assert "products" in upgrade_body
        assert "op.drop_table" in downgrade_body

    def test_generates_pass_when_no_diff(self, engine):
        meta = sa.MetaData()
        sa.Table(
            "synced",
            meta,
            sa.Column("id", sa.Integer(), primary_key=True),
        )
        meta.create_all(engine)

        upgrade_body, downgrade_body = generate_migration_content(
            engine, meta, exclude_tables={"synced"}
        )
        assert upgrade_body.strip() == "pass"
        assert downgrade_body.strip() == "pass"

