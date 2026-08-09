"""
Core migration orchestrator.

The Migrator ties together:
  - ScriptLoader   — discovers migration files
  - Repository     — tracks which migrations have been applied (+ batch)
  - Operations     — executes DDL within a migration transaction

This is intentionally modelled after Laravel's Migrator class:
  - migrate()  → apply all pending migrations
  - rollback() → undo the last N batches
  - reset()    → undo everything
  - fresh()    → drop all tables, then migrate from scratch
  - status()   → show current state
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from migrify.operations.ops import Operations, _current_ops
from migrify.repository import MigrationRepositoryInterface
from migrify.script.loader import MigrationScript, ScriptLoader

# ---------------------------------------------------------------------------
# Result & Event types
# ---------------------------------------------------------------------------

@dataclass
class MigrationResult:
    name: str
    direction: str          # "upgrade" | "downgrade"
    success: bool
    sql: str | None = None       # populated in pretend mode
    error: str | None = None


@dataclass
class MigrateReport:
    applied: list[MigrationResult] = field(default_factory=list)
    failed: MigrationResult | None = None

    @property
    def success(self) -> bool:
        return self.failed is None


@dataclass
class StatusEntry:
    name: str
    batch: int | None    # None = not yet run
    ran: bool


# ---------------------------------------------------------------------------
# Migrator
# ---------------------------------------------------------------------------

class Migrator:
    """
    Orchestrates migration lifecycle.

    Parameters
    ----------
    engine:
        A SQLAlchemy ``Engine`` for the target database.
    repository:
        An implementation of ``MigrationRepositoryInterface``.
    loader:
        A ``ScriptLoader`` that discovers migration files.
    on_message:
        Optional callback called with human-readable log lines.
    """

    def __init__(
        self,
        engine: Engine,
        repository: MigrationRepositoryInterface,
        loader: ScriptLoader,
        on_message: Callable[[str], None] | None = None,
    ) -> None:
        self._engine = engine
        self._repo = repository
        self._loader = loader
        self._log = on_message or (lambda msg: None)

    # ------------------------------------------------------------------
    # Public commands
    # ------------------------------------------------------------------

    def migrate(
        self,
        step: bool = False,
        pretend: bool = False,
    ) -> MigrateReport:
        """
        Apply all pending migrations.

        Parameters
        ----------
        step:
            If True, each migration runs in its own batch (enables
            per-migration rollback, like Laravel's ``--step``).
        pretend:
            If True, collect the SQL statements without executing them.
        """
        self._ensure_repository()
        ran = self._repo.get_ran()
        pending = self._loader.get_pending(ran)

        if not pending:
            self._log("Nothing to migrate.")
            return MigrateReport()

        report = MigrateReport()
        batch = self._repo.get_next_batch_number()

        for script in pending:
            result = self._run_script(script, "upgrade", pretend=pretend)
            report.applied.append(result)

            if not result.success:
                report.failed = result
                self._log(f"  FAILED  {script.name}")
                break

            if not pretend:
                self._repo.log(script.name, batch)
                self._log(f"  Migrated  {script.name}  (batch {batch})")
            else:
                self._log(f"  [pretend] {script.name}")

            if step:
                batch += 1

        return report

    def rollback(
        self,
        batches: int = 1,
        pretend: bool = False,
    ) -> MigrateReport:
        """
        Roll back the last *batches* batch(es).

        Each rollback removes all migrations belonging to one batch,
        executing their ``downgrade()`` functions in reverse order.
        """
        self._ensure_repository()
        report = MigrateReport()

        last_batch = self._repo.get_last_batch_number()
        if last_batch == 0:
            self._log("Nothing to roll back.")
            return report

        for _ in range(batches):
            current_batch = self._repo.get_last_batch_number()
            if current_batch == 0:
                break
            names = self._repo.get_last_batch()  # already in reverse order

            for name in names:
                script = self._loader.get_script(name)
                if script is None:
                    self._log(f"  WARNING: script not found for {name!r}, skipping.")
                    continue

                result = self._run_script(script, "downgrade", pretend=pretend)
                report.applied.append(result)

                if not result.success:
                    report.failed = result
                    self._log(f"  FAILED  {script.name}")
                    return report

                if not pretend:
                    self._repo.delete(script.name)
                    self._log(f"  Rolled back  {script.name}")
                else:
                    self._log(f"  [pretend] {script.name}")

        return report

    def reset(self, pretend: bool = False) -> MigrateReport:
        """Roll back every applied migration."""
        self._ensure_repository()
        report = MigrateReport()

        all_ran = self._repo.get_ran()
        if not all_ran:
            self._log("Nothing to reset.")
            return report

        # Process in reverse application order
        for name in reversed(all_ran):
            script = self._loader.get_script(name)
            if script is None:
                self._log(f"  WARNING: script not found for {name!r}, skipping.")
                continue

            result = self._run_script(script, "downgrade", pretend=pretend)
            report.applied.append(result)

            if not result.success:
                report.failed = result
                self._log(f"  FAILED  {script.name}")
                return report

            if not pretend:
                self._repo.delete(script.name)
                self._log(f"  Rolled back  {script.name}")

        return report

    def fresh(self, pretend: bool = False) -> MigrateReport:
        """
        Drop **all** tables in the database, then run every migration.

        Equivalent to Laravel's ``migrate:fresh``.
        WARNING: This is destructive — all data will be lost.
        """
        if not pretend:
            self._log("Dropping all tables…")
            self._drop_all_tables()

        return self.migrate(pretend=pretend)

    def status(self) -> list[StatusEntry]:
        """Return the run/pending status of every migration file."""
        self._ensure_repository()
        all_scripts = self._loader.get_all_scripts()
        records = {r.migration: r for r in self._repo.get_all()}

        entries: list[StatusEntry] = []
        for script in all_scripts:
            rec = records.get(script.name)
            entries.append(
                StatusEntry(
                    name=script.name,
                    batch=rec.batch if rec else None,
                    ran=rec is not None,
                )
            )
        return entries

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_repository(self) -> None:
        if not self._repo.repository_exists():
            self._repo.create_repository()

    def _run_script(
        self,
        script: MigrationScript,
        direction: str,
        pretend: bool = False,
    ) -> MigrationResult:
        """
        Execute *script*'s upgrade or downgrade inside a transaction.
        Returns a ``MigrationResult``.
        """
        try:
            module = script.load()
        except Exception:  # noqa: BLE001
            return MigrationResult(
                name=script.name,
                direction=direction,
                success=False,
                error=traceback.format_exc(),
            )

        fn = getattr(module, direction, None)
        if fn is None:
            # No function defined — treat as a no-op (successful).
            return MigrationResult(name=script.name, direction=direction, success=True)

        if pretend:
            sql_lines = self._collect_sql(fn)
            return MigrationResult(
                name=script.name,
                direction=direction,
                success=True,
                sql="\n".join(sql_lines),
            )

        try:
            with self._engine.begin() as conn:
                ops = Operations(conn)
                token = _current_ops.set(ops)
                try:
                    fn()
                finally:
                    _current_ops.reset(token)
        except Exception:  # noqa: BLE001
            return MigrationResult(
                name=script.name,
                direction=direction,
                success=False,
                error=traceback.format_exc(),
            )

        return MigrationResult(name=script.name, direction=direction, success=True)

    def _collect_sql(self, fn: Callable) -> list[str]:
        """
        Run *fn* inside a real transaction that is rolled back immediately,
        capturing every SQL statement via SQLAlchemy's before_cursor_execute event.
        """
        from sqlalchemy import event

        statements: list[str] = []

        def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(self._engine, "before_cursor_execute", _before_cursor_execute)
        try:
            with self._engine.begin() as conn:
                ops = Operations(conn)
                token = _current_ops.set(ops)
                try:
                    fn()
                except Exception:  # noqa: BLE001, S110
                    pass
                finally:
                    _current_ops.reset(token)
                # Roll back so nothing is actually applied
                conn.rollback()
        except Exception:  # noqa: BLE001, S110
            pass
        finally:
            event.remove(self._engine, "before_cursor_execute", _before_cursor_execute)

        return statements

    def _drop_all_tables(self) -> None:
        """Drop every table in the connected database."""
        meta = sa.MetaData()
        meta.reflect(bind=self._engine)
        meta.drop_all(bind=self._engine)



