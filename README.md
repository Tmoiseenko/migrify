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
pip install migrify-db
```

## Quickstart

**1. Configure** (`pyproject.toml` or `migrify.toml`):

```toml
[tool.migrify]
db_url = "postgresql://user:pass@localhost/mydb"
migrations_dir = "migrations"
# models_module = "myapp.models"  # for autogenerate
```

**2. Create a migration:**

```bash
# Empty migration
migrify make create_users_table

# With autogenerate (compares your SQLAlchemy models with DB)
migrify make --autogenerate add_phone_to_users
```

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

