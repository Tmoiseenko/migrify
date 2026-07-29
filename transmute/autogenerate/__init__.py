"""
Autogenerate: compare SQLAlchemy MetaData with the current DB schema
and produce Python code for the detected differences.

Architecture mirrors Alembic's autogenerate but without the revision/DAG system:

    compare.py  — produces a list of Diff objects
    render.py   — turns Diff objects into Python source strings
    api.py      — public entry point
"""

from transmute.autogenerate.api import generate_migration_content, compare_metadata

__all__ = ["generate_migration_content", "compare_metadata"]

