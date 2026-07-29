"""Tests for DatabaseMigrationRepository."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from transmute.repository.database import DatabaseMigrationRepository


@pytest.fixture()
def repo(engine):
    r = DatabaseMigrationRepository(engine)
    return r


class TestRepositoryCreation:
    def test_repository_does_not_exist_initially(self, repo):
        assert repo.repository_exists() is False

    def test_create_repository(self, repo):
        repo.create_repository()
        assert repo.repository_exists() is True

    def test_create_repository_idempotent(self, repo):
        repo.create_repository()
        repo.create_repository()  # should not raise
        assert repo.repository_exists() is True


class TestRepositoryOperations:
    @pytest.fixture(autouse=True)
    def _setup(self, repo):
        repo.create_repository()

    def test_get_ran_empty(self, repo):
        assert repo.get_ran() == []

    def test_log_and_get_ran(self, repo):
        repo.log("2024_01_01_000000_first", batch=1)
        repo.log("2024_01_02_000000_second", batch=1)
        ran = repo.get_ran()
        assert "2024_01_01_000000_first" in ran
        assert "2024_01_02_000000_second" in ran

    def test_log_ordered_by_batch_then_name(self, repo):
        repo.log("2024_01_03_000000_third", batch=2)
        repo.log("2024_01_01_000000_first", batch=1)
        repo.log("2024_01_02_000000_second", batch=1)
        ran = repo.get_ran()
        assert ran[0] == "2024_01_01_000000_first"
        assert ran[1] == "2024_01_02_000000_second"
        assert ran[2] == "2024_01_03_000000_third"

    def test_get_last_batch_number_empty(self, repo):
        assert repo.get_last_batch_number() == 0

    def test_get_next_batch_number_empty(self, repo):
        assert repo.get_next_batch_number() == 1

    def test_get_last_batch_number_after_log(self, repo):
        repo.log("first", batch=1)
        repo.log("second", batch=2)
        assert repo.get_last_batch_number() == 2

    def test_get_next_batch_number_after_log(self, repo):
        repo.log("first", batch=3)
        assert repo.get_next_batch_number() == 4

    def test_get_last_batch_returns_last_batch_names(self, repo):
        repo.log("a", batch=1)
        repo.log("b", batch=1)
        repo.log("c", batch=2)
        last = repo.get_last_batch()
        assert last == ["c"]

    def test_get_last_batch_empty(self, repo):
        assert repo.get_last_batch() == []

    def test_delete_removes_record(self, repo):
        repo.log("alpha", batch=1)
        repo.delete("alpha")
        assert "alpha" not in repo.get_ran()

    def test_delete_nonexistent_is_noop(self, repo):
        repo.delete("does_not_exist")  # should not raise

    def test_get_all_returns_records(self, repo):
        repo.log("mig_a", batch=1)
        repo.log("mig_b", batch=2)
        records = repo.get_all()
        assert len(records) == 2
        assert records[0].migration == "mig_a"
        assert records[0].batch == 1

