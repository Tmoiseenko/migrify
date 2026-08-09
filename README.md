# migrify

> Database migrations for Python: the autogenerate power of Alembic, the linear simplicity of Laravel.

## Philosophy

**Alembic** is powerful but complex — branching, DAG graphs, multiple heads, `down_revision` chains.  
**Laravel** migrations are simple — linear order by filename, a `migrations` table with a batch number, `up()` / `down()`.

`migrify` takes the best of both:

| Feature | Source |
|---|---|
| Autogenerate from SQLAlchemy models | Alembic |
| Full DDL operations API (`op.*`) | Alembic |
| Multi-dialect support (PG, MySQL, SQLite...) | Alembic |
| Linear ordering by timestamp filename | Laravel |
| `migrations (id, migration, batch)` tracking table | Laravel |
| Batch-based rollback | Laravel |
| Simple `migrate` / `rollback` / `fresh` CLI | Laravel |

## Installation

```bash
pip install migrify
```

## Quickstart

**1. Initialise** (creates `migrations/` and a ready-to-edit `migrify.toml`):

```bash
migrify init
```

Then open `migrify.toml` and set your `db_url` (use a **sync** driver):

```toml
db_url = "postgresql+psycopg2://user:pass@localhost/mydb"
migrations_dir = "migrations"
# models_module = "myapp.models"  # for autogenerate
```

> **Note:** migrify is sync-only. If your app uses an async driver (e.g. `asyncpg`),
> migrify will auto-switch to the sync equivalent and print a warning.

**2. Create a migration:**

```bash
# Empty migration
migrify make create_users_table

# With autogenerate (compares your SQLAlchemy models with DB)
migrify make --autogenerate add_phone_to_users
```

> **Autogenerate requirement:** the module set in `models_module` must expose a
> `metadata` attribute of type `sqlalchemy.MetaData`.  With declarative models,
> add one line to your models package:
>
> ```python
> # myapp/models/__init__.py
> from .base import Base          # your DeclarativeBase
> # ... other imports ...
>
> metadata = Base.metadata        # ← required for --autogenerate
> ```
>
> The attribute name can be changed via `models_metadata_attr` in the config.

**3. Edit the migration file:**

```python
# migrations/2024_01_15_143022_create_users_table.py
import sqlalchemy as sa
from migrify import op


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("users")
```

**4. Run migrations:**

```bash
migrify migrate          # apply all pending
migrify status           # see what's applied
migrify rollback         # undo last batch
migrify fresh            # drop everything and re-migrate
```

## CLI Reference

| Command | Description |
|---|---|
| `migrify init` | Scaffold `migrations/` dir and `migrify.toml` template |
| `migrify migrate` | Apply all pending migrations |
| `migrify migrate --step` | Apply pending, each in its own batch |
| `migrify migrate --pretend` | Show SQL without executing |
| `migrify rollback` | Rollback last batch |
| `migrify rollback --batch 3` | Rollback last 3 batches |
| `migrify reset` | Rollback all migrations |
| `migrify fresh` | Drop all tables + migrate |
| `migrify status` | Show migration status |
| `migrify make <name>` | Create empty migration |
| `migrify make --autogenerate <name>` | Create migration from model diff |

## Configuration Reference

All options go in `migrify.toml` (or `[tool.migrify]` in `pyproject.toml`).

```toml
# ── Required ────────────────────────────────────────────────────────────────

# Database URL. Must use a sync driver.
# asyncpg / aiosqlite / aiomysql are auto-swapped to their sync equivalents.
db_url = "postgresql+psycopg2://user:pass@localhost/mydb"

# ── Optional ────────────────────────────────────────────────────────────────

# Directory where migration files are stored. Default: "migrations"
migrations_dir = "migrations"

# Name of the migrations tracking table. Default: "migrations"
migrations_table = "migrations"

# ── Autogenerate ─────────────────────────────────────────────────────────────

# Dotted Python path to the module exposing your SQLAlchemy MetaData.
# Required for `migrify make --autogenerate`.
models_module = "myapp.models"

# Attribute name of the MetaData inside models_module. Default: "metadata"
models_metadata_attr = "metadata"

# Whether to detect column type changes. Default: true
# Set to false if you have intentional model/DB type mismatches
# (e.g. Enum in model vs VARCHAR in DB — common when native_enum=False).
compare_types = true

# Tables to skip entirely during autogenerate comparison.
# Supports fnmatch patterns (*, ?, [seq]).
# Use for partition tables, legacy tables, or tables managed outside models.
exclude_tables = [
    "history_changes_p*",       # time-based partitions
    "history_changes_default",
    "alembic_version",          # if migrating away from Alembic
]

# Index names to skip during autogenerate comparison.
# Supports fnmatch patterns.
# Use for manually-created indexes (GIN, trigram, etc.) not defined in models.
# Tip: once you add an index to __table_args__ in your model, remove it here.
exclude_indexes = [
    "idx_products_*",
    "idx_groups_*",
]

# Columns to skip when detecting dropped columns. Format: "table.column".
# Use for columns that exist in DB but are not mapped in models
# (e.g. computed columns accessed via @property, or legacy columns).
exclude_columns = [
    "orders.extra_fee",
]
```

### Autogenerate behaviour

migrify compares your SQLAlchemy models against the live database and generates
the minimal set of DDL operations needed to bring the DB in sync with the models.

| What is compared | Default | Notes |
|---|---|---|
| Missing / extra tables | always | controlled by `exclude_tables` |
| Missing / extra columns | always | controlled by `exclude_columns` |
| Column type changes | `compare_types = true` | disable for Enum↔VARCHAR mismatches |
| Column nullability | always | |
| Missing / extra indexes | always | controlled by `exclude_indexes` |
| Missing / extra foreign keys | always | matched by column signature, not name |
| Missing / extra unique constraints | always | |

**Indexes backed by `UniqueConstraint` or `unique=True`** are automatically
recognised and never generate spurious `drop_index` operations.

**Functional indexes** (e.g. GIN, tsvector) declared via `text()` in
`__table_args__` are rendered correctly with `sa.literal_column(...)`.

## Tracking Table

Unlike Alembic's `alembic_version` (which can have multiple rows for branches),  
`migrify` uses a simple, always-linear `migrations` table:

```sql
CREATE TABLE migrations (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    migration VARCHAR(255) NOT NULL,   -- filename without .py
    batch     INTEGER NOT NULL         -- group applied together
);
```

## License

MIT

