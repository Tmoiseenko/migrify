"""
Public API for autogenerate.

Usage
-----
From Python:

    from transmute.autogenerate import generate_migration_content
    import sqlalchemy as sa
    from sqlalchemy import create_engine

    engine = create_engine("postgresql://...")
    metadata = sa.MetaData()
    # ... define your tables on metadata ...

    upgrade_body, downgrade_body = generate_migration_content(engine, metadata)

From the CLI this is called transparently via ``transmute make --autogenerate``.
"""

from __future__ import annotations

import importlib
from typing import List, Optional, Set, Tuple

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from transmute.autogenerate.compare import Diff, SchemaComparator
from transmute.autogenerate.render import render_downgrade_body, render_upgrade_body


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def compare_metadata(
    engine: Engine,
    metadata: sa.MetaData,
    include_schemas: Optional[Set[Optional[str]]] = None,
    exclude_tables: Optional[Set[str]] = None,
) -> List[Diff]:
    """
    Compare *metadata* against the live schema and return detected diffs.

    Parameters
    ----------
    engine:
        Active SQLAlchemy engine connected to the target database.
    metadata:
        Your model metadata (the *desired* state).
    include_schemas:
        Schemas to inspect.  Defaults to the default schema (``{None}``).
    exclude_tables:
        Table names to ignore entirely.

    Returns
    -------
    list[Diff]
        Ordered list of differences.  Empty list means schemas are in sync.
    """
    comparator = SchemaComparator(
        engine=engine,
        metadata=metadata,
        include_schemas=include_schemas,
        exclude_tables=exclude_tables,
    )
    return comparator.compare()


def generate_migration_content(
    engine: Engine,
    metadata: sa.MetaData,
    include_schemas: Optional[Set[Optional[str]]] = None,
    exclude_tables: Optional[Set[str]] = None,
) -> Tuple[str, str]:
    """
    Generate the Python source for ``upgrade()`` and ``downgrade()`` bodies.

    Returns
    -------
    (upgrade_body, downgrade_body) : tuple[str, str]
        Indented Python source (4-space) ready to be inserted into a migration
        template.  Both strings already contain leading indentation.
    """
    diffs = compare_metadata(engine, metadata, include_schemas, exclude_tables)
    return render_upgrade_body(diffs), render_downgrade_body(diffs)


def load_metadata_from_module(module_path: str, attr: str = "metadata") -> sa.MetaData:
    """
    Import *module_path* and return its ``metadata`` attribute.

    Parameters
    ----------
    module_path:
        Dotted Python module path, e.g. ``"myapp.models"``.
    attr:
        Attribute name that holds the ``MetaData`` instance.

    Raises
    ------
    ImportError / AttributeError if the module or attribute cannot be found.
    """
    module = importlib.import_module(module_path)
    obj = getattr(module, attr)
    if callable(obj):
        obj = obj()
    if not isinstance(obj, sa.MetaData):
        raise TypeError(
            f"{module_path}.{attr} must be a sqlalchemy.MetaData instance, "
            f"got {type(obj).__name__!r}"
        )
    return obj

