"""
Command-line interface for transmute.

Commands
--------
  migrate     Apply all pending migrations
  rollback    Roll back the last batch(es)
  reset       Roll back every migration
  fresh       Drop all tables and re-migrate
  status      Show migration status
  make        Create a new migration file
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click
import sqlalchemy as sa

from migrify.config import Config
from migrify.migrator import Migrator
from migrify.repository.database import DatabaseMigrationRepository
from migrify.script.creator import MigrationCreator
from migrify.script.loader import ScriptLoader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _echo_ok(msg: str) -> None:
    click.echo(click.style("  ✔  ", fg="green") + msg)


def _echo_err(msg: str) -> None:
    click.echo(click.style("  ✖  ", fg="red") + msg, err=True)


def _echo_info(msg: str) -> None:
    click.echo(click.style("  →  ", fg="cyan") + msg)


def _make_migrator(config: Config, verbose: bool = True) -> Migrator:
    engine = sa.create_engine(config.db_url)
    repo = DatabaseMigrationRepository(engine, table_name=config.migrations_table)
    loader = ScriptLoader(Path(config.migrations_dir))

    def log(msg: str) -> None:
        if verbose:
            click.echo(msg)

    return Migrator(engine=engine, repository=repo, loader=loader, on_message=log)


def _load_config(db_url: Optional[str]) -> Config:
    if db_url:
        config = Config(db_url=db_url)
    else:
        config = Config.load()
    if config._async_driver_warning:
        click.echo(click.style("  ⚠  ", fg="yellow") + config._async_driver_warning, err=True)
    return config


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(package_name="migrify")
def cli() -> None:
    """migrify — database migrations with Alembic power and Laravel simplicity."""


# ---------------------------------------------------------------------------
# migrate
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--db-url", envvar="MIGRIFY_DB_URL", default=None, help="Database URL.")
@click.option("--step", is_flag=True, default=False, help="Each migration in its own batch.")
@click.option("--pretend", is_flag=True, default=False, help="Show SQL without executing.")
def migrate(db_url: Optional[str], step: bool, pretend: bool) -> None:
    """Apply all pending migrations."""
    config = _load_config(db_url)
    migrator = _make_migrator(config)
    report = migrator.migrate(step=step, pretend=pretend)

    if pretend:
        for result in report.applied:
            click.echo(f"\n-- {result.name}")
            if result.sql:
                click.echo(result.sql)

    if report.failed:
        _echo_err(f"Migration failed: {report.failed.name}")
        if report.failed.error:
            click.echo(report.failed.error, err=True)
        sys.exit(1)

    if report.applied:
        _echo_ok(f"Ran {len(report.applied)} migration(s).")
    else:
        _echo_info("Nothing to migrate.")


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--db-url", envvar="MIGRIFY_DB_URL", default=None, help="Database URL.")
@click.option("--batch", "batches", default=1, show_default=True, help="Number of batches to roll back.")
@click.option("--pretend", is_flag=True, default=False, help="Show SQL without executing.")
def rollback(db_url: Optional[str], batches: int, pretend: bool) -> None:
    """Roll back the last batch of migrations."""
    config = _load_config(db_url)
    migrator = _make_migrator(config)
    report = migrator.rollback(batches=batches, pretend=pretend)

    if pretend:
        for result in report.applied:
            click.echo(f"\n-- {result.name}")
            if result.sql:
                click.echo(result.sql)

    if report.failed:
        _echo_err(f"Rollback failed: {report.failed.name}")
        if report.failed.error:
            click.echo(report.failed.error, err=True)
        sys.exit(1)

    if report.applied:
        _echo_ok(f"Rolled back {len(report.applied)} migration(s).")
    else:
        _echo_info("Nothing to roll back.")


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--db-url", envvar="MIGRIFY_DB_URL", default=None, help="Database URL.")
@click.option("--pretend", is_flag=True, default=False, help="Show SQL without executing.")
@click.confirmation_option(prompt="This will roll back ALL migrations. Continue?")
def reset(db_url: Optional[str], pretend: bool) -> None:
    """Roll back every applied migration."""
    config = _load_config(db_url)
    migrator = _make_migrator(config)
    report = migrator.reset(pretend=pretend)

    if report.failed:
        _echo_err(f"Reset failed at: {report.failed.name}")
        sys.exit(1)

    _echo_ok(f"Reset {len(report.applied)} migration(s).")


# ---------------------------------------------------------------------------
# fresh
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--db-url", envvar="MIGRIFY_DB_URL", default=None, help="Database URL.")
@click.option("--pretend", is_flag=True, default=False, help="Show SQL without executing.")
@click.confirmation_option(prompt="This will DROP ALL TABLES and re-migrate. Continue?")
def fresh(db_url: Optional[str], pretend: bool) -> None:
    """Drop all tables and re-run every migration from scratch."""
    config = _load_config(db_url)
    migrator = _make_migrator(config)
    report = migrator.fresh(pretend=pretend)

    if report.failed:
        _echo_err(f"Fresh failed at: {report.failed.name}")
        sys.exit(1)

    _echo_ok(f"Fresh complete — ran {len(report.applied)} migration(s).")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--db-url", envvar="MIGRIFY_DB_URL", default=None, help="Database URL.")
def status(db_url: Optional[str]) -> None:
    """Show the status of all migration files."""
    config = _load_config(db_url)
    migrator = _make_migrator(config, verbose=False)
    entries = migrator.status()

    if not entries:
        _echo_info("No migration files found.")
        return

    # Header
    click.echo(
        f"\n  {'Status':<10} {'Batch':<8} Migration\n"
        f"  {'-'*10} {'-'*8} {'-'*50}"
    )
    for entry in entries:
        if entry.ran:
            status_str = click.style("Applied", fg="green")
            batch_str = str(entry.batch)
        else:
            status_str = click.style("Pending", fg="yellow")
            batch_str = "-"
        click.echo(f"  {status_str:<10} {batch_str:<8} {entry.name}")
    click.echo()


# ---------------------------------------------------------------------------
# make
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("name")
@click.option("--db-url", envvar="MIGRIFY_DB_URL", default=None, help="Database URL.")
@click.option("--create", "create_table", default=None, help="Generate a CREATE TABLE stub.")
@click.option("--table", "update_table", default=None, help="Generate an ALTER TABLE stub.")
@click.option(
    "--autogenerate",
    is_flag=True,
    default=False,
    help="Compare models with DB and generate diff automatically.",
)
def make(
    name: str,
    db_url: Optional[str],
    create_table: Optional[str],
    update_table: Optional[str],
    autogenerate: bool,
) -> None:
    """Create a new migration file.

    NAME is used in the filename, e.g. create_users_table.

    Examples:

    \b
        migrify make create_users_table
        migrify make --create users create_users_table
        migrify make --autogenerate add_phone_to_users
    """
    config = _load_config(db_url)
    creator = MigrationCreator(Path(config.migrations_dir))

    if autogenerate:
        if not config.models_module:
            _echo_err(
                "models_module is required for --autogenerate. "
                "Set it in [tool.migrify] → models_module = 'myapp.models'."
            )
            sys.exit(1)

        _echo_info(f"Loading models from {config.models_module!r}…")
        from migrify.autogenerate.api import generate_migration_content, load_metadata_from_module

        engine = sa.create_engine(config.db_url)
        metadata = load_metadata_from_module(config.models_module, config.models_metadata_attr)
        upgrade_body, downgrade_body = generate_migration_content(engine, metadata)

        path = creator.create(
            name,
            upgrade_body=upgrade_body,
            downgrade_body=downgrade_body,
        )
    else:
        path = creator.create(
            name,
            create_table=create_table,
            update_table=update_table,
        )

    _echo_ok(f"Created migration: {path}")


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

_MIGRIFY_TOML_TEMPLATE = """\
# migrify configuration
# Documentation: https://github.com/Tmoiseenko/migrify

# Database connection URL (sync driver required).
# Examples:
#   postgresql+psycopg2://user:password@localhost:5432/mydb
#   mysql+pymysql://user:password@localhost:3306/mydb
#   sqlite:///./db.sqlite3
db_url = "postgresql+psycopg2://user:password@localhost:5432/mydb"

# Directory where migration files are stored.
migrations_dir = "migrations"

# Name of the migrations tracking table in the database.
# migrations_table = "migrations"

# Dotted Python path to the module that exposes your SQLAlchemy MetaData.
# Required for `migrify make --autogenerate`.
# Example: "myapp.models" — the module must expose a `metadata` attribute.
# models_module = "myapp.models"

# Name of the MetaData attribute inside models_module (default: "metadata").
# models_metadata_attr = "metadata"
"""


@cli.command("init")
@click.option(
    "--migrations-dir",
    default="migrations",
    show_default=True,
    help="Directory to create for migration files.",
)
@click.option(
    "--toml/--no-toml",
    "write_toml",
    default=True,
    help="Write a migrify.toml config template.",
)
def init(migrations_dir: str, write_toml: bool) -> None:
    """Scaffold the migrations directory and a config template.

    Run this once at the start of a project to get a ready-to-edit
    migrify.toml and an empty migrations/ directory.

    \b
        migrify init
        migrify init --migrations-dir db/migrations
    """
    # Create migrations directory
    mdir = Path(migrations_dir)
    mdir.mkdir(parents=True, exist_ok=True)
    _echo_ok(f"Migrations directory ready: {mdir}/")

    # Write migrify.toml if requested
    if write_toml:
        toml_path = Path("migrify.toml")
        if toml_path.exists():
            _echo_info("migrify.toml already exists — skipping.")
        else:
            content = _MIGRIFY_TOML_TEMPLATE
            if migrations_dir != "migrations":
                content = content.replace(
                    'migrations_dir = "migrations"',
                    f'migrations_dir = "{migrations_dir}"',
                )
            toml_path.write_text(content, encoding="utf-8")
            _echo_ok(f"Config created: {toml_path}")
            _echo_info("Edit migrify.toml and set db_url before running migrations.")

