"""Tests for the Migrator orchestrator."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import sqlalchemy as sa

from tests.conftest import write_migration
from migrify.migrator import Migrator


class TestMigratorMigrate:
    def test_migrate_empty_dir(self, migrator):
        report = migrator.migrate()
        assert report.success
        assert report.applied == []

    def test_migrate_runs_pending(self, migrator, migrations_dir, engine):
        write_migration(
            migrations_dir,
            "2024_01_01_000000_create_foo",
            upgrade="op.create_table('foo', sa.Column('id', sa.Integer(), primary_key=True))",
            downgrade="op.drop_table('foo')",
        )
        report = migrator.migrate()
        assert report.success
        assert len(report.applied) == 1

        # Table actually created
        insp = sa.inspect(engine)
        assert insp.has_table("foo")

    def test_migrate_records_in_repository(self, migrator, migrations_dir, repo):
        write_migration(migrations_dir, "2024_01_01_000000_alpha")
        write_migration(migrations_dir, "2024_01_02_000000_beta")
        migrator.migrate()
        ran = repo.get_ran()
        assert "2024_01_01_000000_alpha" in ran
        assert "2024_01_02_000000_beta" in ran

    def test_migrate_assigns_same_batch_by_default(self, migrator, migrations_dir, repo):
        write_migration(migrations_dir, "2024_01_01_000000_a")
        write_migration(migrations_dir, "2024_01_02_000000_b")
        migrator.migrate()
        records = repo.get_all()
        batches = {r.batch for r in records}
        assert batches == {1}

    def test_migrate_step_assigns_separate_batches(self, migrator, migrations_dir, repo):
        write_migration(migrations_dir, "2024_01_01_000000_a")
        write_migration(migrations_dir, "2024_01_02_000000_b")
        migrator.migrate(step=True)
        records = repo.get_all()
        batches = [r.batch for r in records]
        assert batches == [1, 2]

    def test_migrate_skips_already_ran(self, migrator, migrations_dir, repo):
        write_migration(migrations_dir, "2024_01_01_000000_a")
        migrator.migrate()
        # Second run should do nothing
        report = migrator.migrate()
        assert report.applied == []

    def test_migrate_increments_batch(self, migrator, migrations_dir, repo):
        write_migration(migrations_dir, "2024_01_01_000000_a")
        migrator.migrate()
        write_migration(migrations_dir, "2024_01_02_000000_b")
        migrator.migrate()
        records = {r.migration: r.batch for r in repo.get_all()}
        assert records["2024_01_01_000000_a"] == 1
        assert records["2024_01_02_000000_b"] == 2

    def test_migrate_fails_gracefully(self, migrator, migrations_dir):
        write_migration(
            migrations_dir,
            "2024_01_01_000000_bad",
            upgrade="raise RuntimeError('oops')",
        )
        report = migrator.migrate()
        assert not report.success
        assert report.failed is not None
        assert "oops" in report.failed.error

    def test_migrate_pretend_does_not_apply(self, migrator, migrations_dir, repo):
        write_migration(
            migrations_dir,
            "2024_01_01_000000_create_bar",
            upgrade="op.create_table('bar', sa.Column('id', sa.Integer(), primary_key=True))",
        )
        report = migrator.migrate(pretend=True)
        assert report.success
        # Nothing recorded in repository
        assert repo.get_ran() == []


class TestMigratorRollback:
    def test_rollback_empty(self, migrator):
        report = migrator.rollback()
        assert report.success
        assert report.applied == []

    def test_rollback_last_batch(self, migrator, migrations_dir, repo, engine):
        write_migration(
            migrations_dir,
            "2024_01_01_000000_create_tbl",
            upgrade="op.create_table('tbl', sa.Column('id', sa.Integer(), primary_key=True))",
            downgrade="op.drop_table('tbl')",
        )
        migrator.migrate()
        assert sa.inspect(engine).has_table("tbl")

        migrator.rollback()
        assert not sa.inspect(engine).has_table("tbl")
        assert repo.get_ran() == []

    def test_rollback_only_last_batch_with_step(self, migrator, migrations_dir, repo, engine):
        write_migration(
            migrations_dir,
            "2024_01_01_000000_create_a",
            upgrade="op.create_table('a', sa.Column('id', sa.Integer(), primary_key=True))",
            downgrade="op.drop_table('a')",
        )
        write_migration(
            migrations_dir,
            "2024_01_02_000000_create_b",
            upgrade="op.create_table('b', sa.Column('id', sa.Integer(), primary_key=True))",
            downgrade="op.drop_table('b')",
        )
        migrator.migrate(step=True)  # a=batch1, b=batch2
        migrator.rollback()  # rolls back only batch2 (b)

        assert not sa.inspect(engine).has_table("b")
        assert sa.inspect(engine).has_table("a")
        assert repo.get_ran() == ["2024_01_01_000000_create_a"]

    def test_rollback_multiple_batches(self, migrator, migrations_dir, repo, engine):
        write_migration(
            migrations_dir,
            "2024_01_01_000000_create_a",
            upgrade="op.create_table('aa', sa.Column('id', sa.Integer(), primary_key=True))",
            downgrade="op.drop_table('aa')",
        )
        write_migration(
            migrations_dir,
            "2024_01_02_000000_create_b",
            upgrade="op.create_table('bb', sa.Column('id', sa.Integer(), primary_key=True))",
            downgrade="op.drop_table('bb')",
        )
        migrator.migrate(step=True)
        migrator.rollback(batches=2)

        assert not sa.inspect(engine).has_table("aa")
        assert not sa.inspect(engine).has_table("bb")
        assert repo.get_ran() == []


class TestMigratorReset:
    def test_reset_rolls_back_all(self, migrator, migrations_dir, repo, engine):
        write_migration(
            migrations_dir,
            "2024_01_01_000000_create_x",
            upgrade="op.create_table('x', sa.Column('id', sa.Integer(), primary_key=True))",
            downgrade="op.drop_table('x')",
        )
        write_migration(
            migrations_dir,
            "2024_01_02_000000_create_y",
            upgrade="op.create_table('y', sa.Column('id', sa.Integer(), primary_key=True))",
            downgrade="op.drop_table('y')",
        )
        migrator.migrate()
        migrator.reset()
        assert repo.get_ran() == []
        insp = sa.inspect(engine)
        assert not insp.has_table("x")
        assert not insp.has_table("y")


class TestMigratorStatus:
    def test_status_empty(self, migrator):
        entries = migrator.status()
        assert entries == []

    def test_status_shows_pending(self, migrator, migrations_dir):
        write_migration(migrations_dir, "2024_01_01_000000_alpha")
        entries = migrator.status()
        assert len(entries) == 1
        assert entries[0].ran is False
        assert entries[0].batch is None

    def test_status_shows_applied(self, migrator, migrations_dir):
        write_migration(migrations_dir, "2024_01_01_000000_alpha")
        migrator.migrate()
        entries = migrator.status()
        assert entries[0].ran is True
        assert entries[0].batch == 1


class TestMigratorFresh:
    def test_fresh_drops_and_remigrates(self, migrator, migrations_dir, engine):
        write_migration(
            migrations_dir,
            "2024_01_01_000000_create_z",
            upgrade="op.create_table('z', sa.Column('id', sa.Integer(), primary_key=True))",
            downgrade="op.drop_table('z')",
        )
        migrator.migrate()
        assert sa.inspect(engine).has_table("z")

        migrator.fresh()

        # Table exists again (was dropped and re-created)
        assert sa.inspect(engine).has_table("z")

