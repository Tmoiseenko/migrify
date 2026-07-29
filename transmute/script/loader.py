"""Loading and sorting migration script files."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType
from typing import List, Optional

from transmute.exceptions import ScriptError

# Migration filenames must start with a timestamp: YYYY_MM_DD_HHmmss_<name>.py
_TIMESTAMP_RE = re.compile(r"^\d{4}_\d{2}_\d{2}_\d{6}_")


class MigrationScript:
    """Represents a single migration file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        # e.g. "2024_01_15_143022_create_users_table"
        self.name: str = path.stem

    # ------------------------------------------------------------------
    # Module loading
    # ------------------------------------------------------------------

    def load(self) -> ModuleType:
        """Import the migration file as a Python module."""
        spec = importlib.util.spec_from_file_location(self.name, self.path)
        if spec is None or spec.loader is None:
            raise ScriptError(f"Cannot load migration script: {self.path}")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except Exception as exc:
            raise ScriptError(
                f"Error while loading migration {self.name!r}: {exc}"
            ) from exc
        return module

    def has_upgrade(self) -> bool:
        mod = self.load()
        return callable(getattr(mod, "upgrade", None))

    def has_downgrade(self) -> bool:
        mod = self.load()
        return callable(getattr(mod, "downgrade", None))

    # ------------------------------------------------------------------
    # Ordering — purely by filename (timestamp prefix guarantees order)
    # ------------------------------------------------------------------

    def __lt__(self, other: "MigrationScript") -> bool:
        return self.name < other.name

    def __eq__(self, other: object) -> bool:
        if isinstance(other, MigrationScript):
            return self.name == other.name
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.name)

    def __repr__(self) -> str:
        return f"MigrationScript({self.name!r})"


class ScriptLoader:
    """
    Discovers migration files inside a directory.

    Files must:
      - End in ``.py``
      - Not start with ``_``
      - Have a timestamp prefix (YYYY_MM_DD_HHmmss_)
    """

    def __init__(self, migrations_dir: Path | str) -> None:
        self.migrations_dir = Path(migrations_dir)

    def get_all_scripts(self) -> List[MigrationScript]:
        """Return all migration scripts sorted by name (i.e. by timestamp)."""
        if not self.migrations_dir.exists():
            return []
        scripts = [
            MigrationScript(p)
            for p in self.migrations_dir.glob("*.py")
            if not p.name.startswith("_") and _TIMESTAMP_RE.match(p.name)
        ]
        return sorted(scripts)

    def get_pending(self, ran: List[str]) -> List[MigrationScript]:
        """Return scripts that are not yet in the *ran* list."""
        ran_set = set(ran)
        return [s for s in self.get_all_scripts() if s.name not in ran_set]

    def get_script(self, name: str) -> Optional[MigrationScript]:
        """Find a specific script by its stem name."""
        path = self.migrations_dir / f"{name}.py"
        if path.exists():
            return MigrationScript(path)
        return None

