"""
Shared pytest fixtures.

All tests use an in-memory SQLite database and a temporary migrations directory.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import sqlalchemy as sa

from transmute.migrator import Migrator
from transmute.repository.database import DatabaseMigrationRepository
from transmute.script.loader import ScriptLoader


@pytest.fixture()
def engine():
    """In-memory SQLite engine, freshly created per test."""
    e = sa.create_engine("sqlite:///:memory:")
    yield e
    e.dispose()


@pytest.fixture()
def migrations_dir(tmp_path: Path) -> Path:
    """Temporary directory for migration files."""
    d = tmp_path / "migrations"
    d.mkdir()
    return d


@pytest.fixture()
def repo(engine):
    """DatabaseMigrationRepository backed by the in-memory engine."""
    r = DatabaseMigrationRepository(engine, table_name="migrations")
    r.create_repository()
    return r


@pytest.fixture()
def loader(migrations_dir: Path):
    return ScriptLoader(migrations_dir)


@pytest.fixture()
def migrator(engine, repo, loader):
    messages = []
    m = Migrator(
        engine=engine,
        repository=repo,
        loader=loader,
        on_message=messages.append,
    )
    m._messages = messages  # expose for assertions
    return m


# ---------------------------------------------------------------------------
# Helper: write a migration file
# ---------------------------------------------------------------------------

def write_migration(migrations_dir: Path, name: str, upgrade: str = "pass", downgrade: str = "pass") -> Path:
    """Create a migration .py file in *migrations_dir*."""
    body = textwrap.dedent(f"""\
        import sqlalchemy as sa
        from transmute import op

        def upgrade():
            {upgrade}

        def downgrade():
            {downgrade}
    """)
    path = migrations_dir / f"{name}.py"
    path.write_text(body)
    return path

