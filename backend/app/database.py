import logging
from app.db.base import init_db, close_db as close_postgres_db

logger = logging.getLogger(__name__)


async def connect_db():
    """Initialize PostgreSQL database connection."""
    await init_db()
    logger.info("Connected to PostgreSQL ✓")


async def close_db():
    """Close PostgreSQL database connection."""
    await close_postgres_db()
    logger.info("PostgreSQL connection closed")
