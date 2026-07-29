"""
Configuration loading for migrify.

Priority (highest → lowest):
  1. Explicit kwargs / environment variables (MIGRIFY_DB_URL, etc.)
  2. [tool.migrify] section in pyproject.toml
  3. migrify.toml in the current working directory
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from migrify.exceptions import ConfigurationError

# Python 3.11+ ships tomllib in stdlib; older versions need tomli.
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[no-redef]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            tomllib = None  # type: ignore[assignment]


@dataclass
class Config:
    """Transmute runtime configuration."""

    db_url: str
    migrations_dir: str = "migrations"
    migrations_table: str = "migrations"
    # Dotted Python path to a module that exposes a SQLAlchemy MetaData
    # (or a callable returning one) — used for autogenerate.
    models_module: Optional[str] = None
    # Attribute name inside models_module that holds the MetaData object.
    # Defaults to "metadata".
    models_metadata_attr: str = "metadata"

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        db_url = data.get("db_url") or os.environ.get("MIGRIFY_DB_URL")
        if not db_url:
            raise ConfigurationError(
                "db_url is required. Set it in [tool.migrify] or via the "
                "MIGRIFY_DB_URL environment variable."
            )
        return cls(
            db_url=db_url,
            migrations_dir=data.get("migrations_dir", "migrations"),
            migrations_table=data.get("migrations_table", "migrations"),
            models_module=data.get("models_module"),
            models_metadata_attr=data.get("models_metadata_attr", "metadata"),
        )

    @classmethod
    def from_toml_file(cls, path: Path) -> "Config":
        if tomllib is None:
            raise ConfigurationError(
                "tomllib / tomli is required to read TOML config. "
                "Install tomli: pip install tomli"
            )
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        return cls.from_dict(data)

    @classmethod
    def from_pyproject(cls, path: Path = Path("pyproject.toml")) -> "Config":
        if tomllib is None:
            raise ConfigurationError(
                "tomllib / tomli is required. Install tomli: pip install tomli"
            )
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        section = data.get("tool", {}).get("migrify", {})
        return cls.from_dict(section)

    @classmethod
    def load(cls, start_dir: Optional[Path] = None) -> "Config":
        """
        Auto-discover configuration by walking up from *start_dir*
        (defaults to cwd).  Checks:
          1. MIGRIFY_DB_URL env var (minimal valid config)
          2. migrify.toml
          3. pyproject.toml [tool.migrify]
        """
        cwd = Path(start_dir or os.getcwd())

        # Walk up the directory tree looking for a config file.
        for directory in [cwd, *cwd.parents]:
            toml_path = directory / "migrify.toml"
            if toml_path.exists():
                return cls.from_toml_file(toml_path)

            pyproject_path = directory / "pyproject.toml"
            if pyproject_path.exists():
                try:
                    cfg = cls.from_pyproject(pyproject_path)
                    return cfg
                except ConfigurationError:
                    # pyproject.toml exists but has no [tool.migrify] with db_url
                    pass

        # Last resort: environment variable only
        db_url = os.environ.get("MIGRIFY_DB_URL")
        if db_url:
            return cls(db_url=db_url)

        raise ConfigurationError(
            "Could not find migrify configuration. "
            "Create a migrify.toml or add [tool.migrify] to pyproject.toml "
            "with at least db_url = '...'."
        )

