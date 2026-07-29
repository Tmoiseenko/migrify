# transmute

> Database migrations for Python: the autogenerate power of Alembic, the linear simplicity of Laravel.

## Philosophy

**Alembic** is powerful but complex — branching, DAG graphs, multiple heads, `down_revision` chains.  
**Laravel** migrations are simple — linear order by filename, a `migrations` table with a batch number, `up()` / `down()`.

`transmute` takes the best of both:

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
pip install transmute-db
```

## Quickstart

**1. Configure** (`pyproject.toml` or `transmute.toml`):

```toml
[tool.transmute]
db_url = "postgresql://user:pass@localhost/mydb"
migrations_dir = "migrations"
# models_module = "myapp.models"  # for autogenerate
```

**2. Create a migration:**

```bash
# Empty migration
transmute make create_users_table

# With autogenerate (compares your SQLAlchemy models with DB)
transmute make --autogenerate add_phone_to_users
```

**3. Edit the migration file:**

```python
# migrations/2024_01_15_143022_create_users_table.py
import sqlalchemy as sa
from transmute import op


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
transmute migrate          # apply all pending
transmute status           # see what's applied
transmute rollback         # undo last batch
transmute fresh            # drop everything and re-migrate
```

## CLI Reference

| Command | Description |
|---|---|
| `transmute migrate` | Apply all pending migrations |
| `transmute migrate --step` | Apply pending, each in its own batch |
| `transmute migrate --pretend` | Show SQL without executing |
| `transmute rollback` | Rollback last batch |
| `transmute rollback --batch 3` | Rollback last 3 batches |
| `transmute reset` | Rollback all migrations |
| `transmute fresh` | Drop all tables + migrate |
| `transmute status` | Show migration status |
| `transmute make <name>` | Create empty migration |
| `transmute make --autogenerate <name>` | Create migration from model diff |

## Tracking Table

Unlike Alembic's `alembic_version` (which can have multiple rows for branches),  
`transmute` uses a simple, always-linear `migrations` table:

```sql
CREATE TABLE migrations (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    migration VARCHAR(255) NOT NULL,   -- filename without .py
    batch     INTEGER NOT NULL         -- group applied together
);
```

## License

MIT

