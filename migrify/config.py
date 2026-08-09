"""
Configuration loading for migrify.

Priority (highest → lowest):
  1. Explicit kwargs / environment variables (MIGRIFY_DB_URL, etc.)
  2. [tool.migrify] section in pyproject.toml
  3. migrify.toml in the current working directory
"""

from __future__ import annotations

# Async SQLAlchemy drivers that migrify cannot use (it is sync-only).
# Maps async driver suffix → sync replacement (empty string = use dialect default).
_ASYNC_DRIVER_MAP = {
    "asyncpg": "psycopg2",
    "aiosqlite": "",
    "aiomysql": "pymysql",
    "asyncmy": "pymysql",
}

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

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
    models_module: str | None = None
    # Attribute name inside models_module that holds the MetaData object.
    # Defaults to "metadata".
    models_metadata_attr: str = "metadata"
    # Set when db_url had an async driver that was auto-replaced.
    _async_driver_warning: str | None = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_db_url(url: str) -> tuple[str, str | None]:
        """
        If *url* uses an async driver (e.g. asyncpg, aiosqlite) that
        migrify cannot use, swap it for a compatible sync driver and
        return (normalized_url, warning_message).  Otherwise return
        (url, None).
        """
        import re
        # Match  dialect+driver://...
        m = re.match(r"^([^+:]+)\+([^:]+):(//.*)", url)
        if m:
            dialect, driver, rest = m.group(1), m.group(2), m.group(3)
            if driver in _ASYNC_DRIVER_MAP:
                sync_driver = _ASYNC_DRIVER_MAP[driver]
                if sync_driver:
                    new_url = f"{dialect}+{sync_driver}:{rest}"
                    warn = (
                        f"Async driver '{driver}' is not supported by migrify (sync-only). "
                        f"Auto-switched to '{sync_driver}'. "
                        f"Update your db_url to use '{dialect}+{sync_driver}://' to suppress this warning."
                    )
                else:
                    new_url = f"{dialect}:{rest}"
                    warn = (
                        f"Async driver '{driver}' is not supported by migrify (sync-only). "
                        f"Auto-switched to the default '{dialect}' driver. "
                        f"Update your db_url to use '{dialect}://' to suppress this warning."
                    )
                return new_url, warn
        return url, None

    @classmethod
    def from_dict(cls, data: dict) -> Config:
        db_url = data.get("db_url") or os.environ.get("MIGRIFY_DB_URL")
        if not db_url:
            raise ConfigurationError(
                "db_url is required. Set it in [tool.migrify] or via the "
                "MIGRIFY_DB_URL environment variable."
            )
        db_url, _warn = cls._normalize_db_url(db_url)
        return cls(
            db_url=db_url,
            migrations_dir=data.get("migrations_dir", "migrations"),
            migrations_table=data.get("migrations_table", "migrations"),
            models_module=data.get("models_module"),
            models_metadata_attr=data.get("models_metadata_attr", "metadata"),
            _async_driver_warning=_warn,
        )

    @classmethod
    def from_toml_file(cls, path: Path) -> Config:
        if tomllib is None:
            raise ConfigurationError(
                "tomllib / tomli is required to read TOML config. "
                "Install tomli: pip install tomli"
            )
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        return cls.from_dict(data)

    @classmethod
    def from_pyproject(cls, path: Path = Path("pyproject.toml")) -> Config:
        if tomllib is None:
            raise ConfigurationError(
                "tomllib / tomli is required. Install tomli: pip install tomli"
            )
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        section = data.get("tool", {}).get("migrify", {})
        return cls.from_dict(section)

    @classmethod
    def load(cls, start_dir: Path | None = None) -> Config:
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

