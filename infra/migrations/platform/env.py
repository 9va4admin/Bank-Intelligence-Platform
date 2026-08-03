"""Alembic env for platform schema migrations (YugabyteDB YSQL).

Platform migrations run ALWAYS — for every bank, every module configuration.
This is the mandatory foundation layer: banks, users, config, notifications, audit, AI models.
"""
import os
from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

db_url = os.environ.get(
    "PLATFORM_DB_URL",
    config.get_main_option("sqlalchemy.url", "")
    .replace("%(DB_USER)s", os.environ.get("DB_USER", "astra"))
    .replace("%(DB_PASS)s", os.environ.get("DB_PASS", ""))
    .replace("%(DB_HOST)s", os.environ.get("DB_HOST", "localhost")),
)

config.set_main_option("sqlalchemy.url", db_url.replace("+asyncpg", ""))


def run_migrations_offline() -> None:
    context.configure(
        url=db_url.replace("+asyncpg", ""),
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        version_table_schema="platform",
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
        # alembic creates its own version_table_schema="platform" bookkeeping
        # table before running any migration — but "platform" schema itself is
        # only created inside the first migration's upgrade(). Confirmed via a
        # real run against a fresh YugabyteDB: alembic._ensure_version_table()
        # fails with InvalidSchemaName on a brand-new bank/database, before a
        # single migration script executes. This is the bootstrap this ordering
        # needs — idempotent, safe on every invocation.
        connection.execute(sa.text("CREATE SCHEMA IF NOT EXISTS platform"))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=None,
            include_schemas=True,
            version_table_schema="platform",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
