"""Alembic env for CTS schema migrations (YugabyteDB YSQL)."""
import os
from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Allow environment variable overrides for CI and bank deployments
db_url = os.environ.get(
    "CTS_DB_URL",
    config.get_main_option("sqlalchemy.url", "")
    .replace("%(DB_USER)s", os.environ.get("DB_USER", "astra"))
    .replace("%(DB_PASS)s", os.environ.get("DB_PASS", ""))
    .replace("%(DB_HOST)s", os.environ.get("DB_HOST", "localhost")),
)

config.set_main_option("sqlalchemy.url", db_url.replace("+asyncpg", ""))  # sync driver for migrations


def run_migrations_offline() -> None:
    context.configure(
        url=db_url.replace("+asyncpg", ""),
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        version_table_schema="cts",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # See infra/migrations/platform/env.py for why this bootstrap is required:
        # alembic's own version_table_schema="cts" bookkeeping table needs the
        # "cts" schema to exist before the first migration (which creates it) runs.
        connection.execute(sa.text("CREATE SCHEMA IF NOT EXISTS cts"))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=None,
            include_schemas=True,
            version_table_schema="cts",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
