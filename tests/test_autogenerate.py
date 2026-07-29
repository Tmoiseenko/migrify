"""Tests for autogenerate (compare + render)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from migrify.autogenerate.api import compare_metadata, generate_migration_content
from migrify.autogenerate.compare import (
    AddColumnDiff,
    CreateTableDiff,
    DropColumnDiff,
    DropTableDiff,
)
from migrify.autogenerate.render import render_type


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
        tbl = sa.Table(
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

