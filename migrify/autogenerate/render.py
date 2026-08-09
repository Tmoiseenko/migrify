"""
Render engine: convert Diff objects into Python source strings.

The generated code uses the ``op.*`` API and ``sqlalchemy`` types,
matching what a developer would write by hand.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.sql.elements import ClauseElement
from sqlalchemy.sql.sqltypes import TypeEngine

from migrify.autogenerate.compare import (
    AddColumnDiff,
    AlterColumnDiff,
    CreateForeignKeyDiff,
    CreateIndexDiff,
    CreateTableDiff,
    Diff,
    DropColumnDiff,
    DropForeignKeyDiff,
    DropIndexDiff,
    DropTableDiff,
)

# ---------------------------------------------------------------------------
# Type renderer
# ---------------------------------------------------------------------------

def render_type(t: TypeEngine) -> str:
    """
    Render a SQLAlchemy type as a Python expression.

    Examples
    --------
    Integer()           → "sa.Integer()"
    String(255)         → "sa.String(length=255)"
    Numeric(10, 2)      → "sa.Numeric(precision=10, scale=2)"
    """
    cls = type(t).__name__

    # Enum — check before length since sa.Enum has a length attribute
    if isinstance(t, sa.Enum) and t.enums:
        enums_str = ", ".join(f"{e!r}" for e in t.enums)
        return f"sa.Enum({enums_str})"

    # Types with explicit length
    if hasattr(t, "length") and t.length is not None:
        return f"sa.{cls}(length={t.length})"

    # Numeric precision/scale
    if hasattr(t, "precision") and hasattr(t, "scale"):
        p = getattr(t, "precision", None)
        s = getattr(t, "scale", None)
        if p is not None and s is not None:
            return f"sa.{cls}(precision={p}, scale={s})"
        if p is not None:
            return f"sa.{cls}(precision={p})"

    # Enum
    if isinstance(t, sa.Enum) and t.enums:
        enums_str = ", ".join(f"{e!r}" for e in t.enums)
        return f"sa.Enum({enums_str})"

    return f"sa.{cls}()"


# ---------------------------------------------------------------------------
# Column renderer
# ---------------------------------------------------------------------------

def render_column(col: sa.Column, indent: int = 8) -> str:
    """
    Render a ``sa.Column(...)`` expression.

    Parameters
    ----------
    col:
        The Column to render.
    indent:
        Number of spaces to indent the line.
    """
    pad = " " * indent
    parts: list[str] = [f"{col.name!r}", render_type(col.type)]

    if col.primary_key:
        parts.append("primary_key=True")
    if col.autoincrement is True and col.primary_key:
        parts.append("autoincrement=True")
    if not col.nullable and not col.primary_key:
        parts.append("nullable=False")
    if col.server_default is not None:
        sd = col.server_default
        if hasattr(sd, "arg"):
            arg = sd.arg
            if isinstance(arg, str):
                parts.append(f"server_default={arg!r}")
            elif isinstance(arg, ClauseElement):
                compiled = str(arg.compile(compile_kwargs={"literal_binds": True}))
                parts.append(f"server_default=sa.text({compiled!r})")
        # FetchedValue (no arg) — no server_default to render
    if col.comment:
        parts.append(f"comment={col.comment!r}")

    args_str = ", ".join(parts)
    return f"{pad}sa.Column({args_str}),"


# ---------------------------------------------------------------------------
# Diff renderers
# ---------------------------------------------------------------------------

def render_create_table(diff: CreateTableDiff) -> str:
    table = diff.table
    lines: list[str] = ['    op.create_table(']
    lines.append(f'        {table.name!r},')

    for col in table.columns:
        lines.append(render_column(col, indent=8))

    # Primary key constraint (if composite)
    pk_cols = [c.name for c in table.primary_key.columns]
    if len(pk_cols) > 1:
        pk_str = ", ".join(f"{n!r}" for n in pk_cols)
        lines.append(f"        sa.PrimaryKeyConstraint({pk_str}),")

    # Unique constraints
    for constraint in table.constraints:
        if isinstance(constraint, sa.UniqueConstraint) and constraint.columns:
            col_names = ", ".join(f"{c.name!r}" for c in constraint.columns)
            name_str = f"name={constraint.name!r}, " if constraint.name else ""
            lines.append(f"        sa.UniqueConstraint({col_names}, {name_str}),")

    schema_str = f", schema={table.schema!r}" if table.schema else ""
    lines.append(f"    {schema_str})")
    return "\n".join(lines)


def render_drop_table(diff: DropTableDiff) -> str:
    schema_str = f", schema={diff.schema!r}" if diff.schema else ""
    return f"    op.drop_table({diff.table_name!r}{schema_str})"


def render_add_column(diff: AddColumnDiff) -> str:
    col_str = render_column(diff.column, indent=0).rstrip(",")
    schema_str = f", schema={diff.schema!r}" if diff.schema else ""
    return (
        f"    op.add_column(\n"
        f"        {diff.table_name!r},\n"
        f"        {col_str}\n"
        f"    {schema_str})"
    )


def render_drop_column(diff: DropColumnDiff) -> str:
    schema_str = f", schema={diff.schema!r}" if diff.schema else ""
    return (
        f"    op.drop_column({diff.table_name!r}, {diff.column_name!r}{schema_str})"
    )


def render_alter_column(diff: AlterColumnDiff) -> str:
    parts: list[str] = []
    if "type" in diff.changes:
        parts.append(f"type_={render_type(diff.changes['type'])}")
    if "nullable" in diff.changes:
        parts.append(f"nullable={diff.changes['nullable']!r}")
    schema_str = f", schema={diff.schema!r}" if diff.schema else ""
    kw_str = ", ".join(parts)
    return (
        f"    op.alter_column(\n"
        f"        {diff.table_name!r}, {diff.column_name!r},\n"
        f"        {kw_str}{schema_str},\n"
        f"    )"
    )


def render_create_index(diff: CreateIndexDiff) -> str:
    idx = diff.index
    col_exprs: list[str] = []
    for expr in idx.expressions:
        if hasattr(expr, "name") and expr.name:
            # Regular Column
            col_exprs.append(repr(expr.name))
        else:
            # text() or other SQL expression (e.g. functional/GIN index)
            compiled = str(expr.compile(compile_kwargs={"literal_binds": True}))
            col_exprs.append(f"sa.literal_column({compiled!r})")
    cols_str = ", ".join(col_exprs)
    unique_str = ", unique=True" if idx.unique else ""
    schema_str = f", schema={diff.schema!r}" if diff.schema else ""
    # Render dialect-specific kwargs, skipping None and empty collections
    dialect_opts = ""
    if idx.dialect_options:
        for dialect, opts in idx.dialect_options.items():
            for key, val in opts.items():
                if val is None or val == {} or val == [] or val is False:
                    continue
                dialect_opts += f", {dialect}_{key}={val!r}"
    return (
        f"    op.create_index(\n"
        f"        {idx.name!r}, {diff.table_name!r},\n"
        f"        [{cols_str}]{unique_str}{schema_str}{dialect_opts},\n"
        f"    )"
    )


def render_drop_index(diff: DropIndexDiff) -> str:
    schema_str = f", schema={diff.schema!r}" if diff.schema else ""
    return (
        f"    op.drop_index({diff.index_name!r}, table_name={diff.table_name!r}{schema_str})"
    )


def render_create_fk(diff: CreateForeignKeyDiff) -> str:
    fk = diff.constraint
    local_cols = [c.name for c in fk.columns]
    remote_cols = [fkc.column.name for fkc in fk.elements]
    referent = next(iter(fk.elements)).column.table.name if fk.elements else "unknown"
    local_str = ", ".join(f"{c!r}" for c in local_cols)
    remote_str = ", ".join(f"{c!r}" for c in remote_cols)
    schema_str = f", source_schema={diff.schema!r}" if diff.schema else ""
    return (
        f"    op.create_foreign_key(\n"
        f"        {fk.name!r}, {diff.table_name!r}, {referent!r},\n"
        f"        [{local_str}], [{remote_str}]{schema_str},\n"
        f"    )"
    )


def render_drop_fk(diff: DropForeignKeyDiff) -> str:
    schema_str = f", schema={diff.schema!r}" if diff.schema else ""
    return (
        f"    op.drop_constraint(\n"
        f"        {diff.constraint_name!r}, {diff.table_name!r},"
        f" type_='foreignkey'{schema_str},\n"
        f"    )"
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def render_diff(diff: Diff) -> str:
    """Render a single Diff object to a Python source string."""
    if isinstance(diff, CreateTableDiff):
        return render_create_table(diff)
    if isinstance(diff, DropTableDiff):
        return render_drop_table(diff)
    if isinstance(diff, AddColumnDiff):
        return render_add_column(diff)
    if isinstance(diff, DropColumnDiff):
        return render_drop_column(diff)
    if isinstance(diff, AlterColumnDiff):
        return render_alter_column(diff)
    if isinstance(diff, CreateIndexDiff):
        return render_create_index(diff)
    if isinstance(diff, DropIndexDiff):
        return render_drop_index(diff)
    if isinstance(diff, CreateForeignKeyDiff):
        return render_create_fk(diff)
    if isinstance(diff, DropForeignKeyDiff):
        return render_drop_fk(diff)
    return f"    # TODO: unhandled diff: {diff!r}"


def render_upgrade_body(diffs: list[Diff]) -> str:
    """Render the body of the ``upgrade()`` function."""
    if not diffs:
        return "    pass"
    lines = [render_diff(d) for d in diffs
             if not isinstance(d, (DropTableDiff, DropColumnDiff, DropIndexDiff, DropForeignKeyDiff))]
    # DropTable/DropColumn in the diff means they were REMOVED from models →
    # upgrade() should drop them; downgrade() should add them back.
    lines += [render_diff(d) for d in diffs
              if isinstance(d, (DropTableDiff, DropColumnDiff, DropIndexDiff, DropForeignKeyDiff))]
    return "\n\n".join(lines) if lines else "    pass"


def render_downgrade_body(diffs: list[Diff]) -> str:
    """Render the body of the ``downgrade()`` function (reverse of upgrade)."""
    if not diffs:
        return "    pass"

    lines: list[str] = []
    for diff in reversed(diffs):
        if isinstance(diff, CreateTableDiff):
            lines.append(render_drop_table(DropTableDiff(diff.table.name, diff.table.schema)))
        elif isinstance(diff, DropTableDiff):
            # We don't know the original schema, render a placeholder
            lines.append(f"    # TODO: recreate table {diff.table_name!r}")
        elif isinstance(diff, AddColumnDiff):
            lines.append(
                render_drop_column(DropColumnDiff(diff.table_name, diff.column.name, diff.schema))
            )
        elif isinstance(diff, DropColumnDiff):
            lines.append(f"    # TODO: add back column {diff.column_name!r} to {diff.table_name!r}")
        elif isinstance(diff, AlterColumnDiff):
            lines.append(f"    # TODO: revert alter_column on {diff.table_name!r}.{diff.column_name!r}")
        elif isinstance(diff, CreateIndexDiff):
            lines.append(
                render_drop_index(DropIndexDiff(diff.index.name, diff.table_name, diff.schema))
            )
        elif isinstance(diff, DropIndexDiff):
            lines.append(f"    # TODO: recreate index {diff.index_name!r}")
        elif isinstance(diff, CreateForeignKeyDiff):
            lines.append(
                render_drop_fk(DropForeignKeyDiff(diff.constraint.name, diff.table_name, diff.schema))
            )
        elif isinstance(diff, DropForeignKeyDiff):
            lines.append(f"    # TODO: recreate foreign key {diff.constraint_name!r}")

    return "\n\n".join(lines) if lines else "    pass"

