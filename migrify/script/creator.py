"""Creating new migration files from templates."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape


def _make_env() -> Environment:
    return Environment(
        loader=PackageLoader("migrify", "templates"),
        autoescape=select_autoescape([]),
        keep_trailing_newline=True,
    )


class MigrationCreator:
    """
    Generates migration script files from Jinja2 templates.

    File naming convention (mirrors Laravel):
        YYYY_MM_DD_HHmmss_<name>.py
    """

    def __init__(self, migrations_dir: Path | str) -> None:
        self.migrations_dir = Path(migrations_dir)
        self.migrations_dir.mkdir(parents=True, exist_ok=True)
        self._env = _make_env()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(
        self,
        name: str,
        *,
        create_table: str | None = None,
        update_table: str | None = None,
        content: str | None = None,
        upgrade_body: str | None = None,
        downgrade_body: str | None = None,
    ) -> Path:
        """
        Generate a new migration file.

        Parameters
        ----------
        name:
            Human-readable description used in the filename, e.g.
            ``create_users_table``.
        create_table:
            If provided, use the *create* template for this table name.
        update_table:
            If provided, use the *update* template for this table name.
        content:
            Raw Python source for the migration body.  Takes priority over
            template rendering.
        """
        filename = self._make_filename(name)
        path = self.migrations_dir / filename

        if content is not None:
            body = content
        elif upgrade_body is not None or downgrade_body is not None:
            body = self._render(
                "migration_autogenerate.py.j2",
                description=name.replace("_", " "),
                upgrade_body=upgrade_body or "    pass",
                downgrade_body=downgrade_body or "    pass",
            )
        elif create_table is not None:
            body = self._render("migration_create.py.j2", table=create_table)
        elif update_table is not None:
            body = self._render("migration_update.py.j2", table=update_table)
        else:
            body = self._render("migration.py.j2")

        path.write_text(body, encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_filename(name: str) -> str:
        ts = datetime.now(tz=timezone.utc).strftime("%Y_%m_%d_%H%M%S")
        # Normalise name: spaces / hyphens → underscores, lowercase
        safe_name = name.strip().replace(" ", "_").replace("-", "_").lower()
        return f"{ts}_{safe_name}.py"

    def _render(self, template_name: str, **context: str) -> str:
        tmpl = self._env.get_template(template_name)
        return tmpl.render(**context)



