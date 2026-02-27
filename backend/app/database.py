import logging
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongodb_uri)
    return _client


def get_db():
    return get_client()[settings.db_name]


# Typed collection accessors
def identities_col():
    return get_db()["identities"]


def users_col():
    return get_db()["users"]


def chats_col():
    return get_db()["chats"]


def messages_col():
    return get_db()["messages"]


def invoices_col():
    return get_db()["invoices"]


def documents_col():
    return get_db()["documents"]


def financial_docs_col():
    return get_db()["financial_docs"]


def oauth_tokens_col():
    return get_db()["oauth_tokens"]


def oauth_states_col():
    return get_db()["oauth_states"]


async def connect_db():
    client = get_client()
    await client.admin.command("ping")
    logger.info("Connected to MongoDB ✓")


async def close_db():
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("MongoDB connection closed")
