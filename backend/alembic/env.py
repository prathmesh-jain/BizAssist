from logging.config import fileConfig
from asyncio import run

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import our models
from app.config import get_settings
from app.db.base import Base
from app.db.models import *  # Import all models to register them with Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Use the application's DATABASE_URL rather than the placeholder in alembic.ini.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# Tables owned by other tools in the same database (LangGraph creates checkpoint*
# tables itself). Alembic must never try to drop or alter them.
EXTERNALLY_MANAGED_TABLE_PREFIXES = ("checkpoint",)


def include_object(obj, name, type_, reflected, compare_to):
    table_name = obj.table.name if type_ in ("index", "column", "unique_constraint", "foreign_key_constraint") else name
    if reflected and compare_to is None and str(table_name).startswith(EXTERNALLY_MANAGED_TABLE_PREFIXES):
        return False
    return True

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
