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

    # Ensure indexes exist (idempotent). TTL prevents oauth_states growth.
    try:
        db = get_db()
        # TTL index: when expires_at < now, MongoDB will delete the document automatically.
        # expireAfterSeconds=0 means expire exactly at the timestamp.
        await db["oauth_states"].create_index("expires_at", expireAfterSeconds=0)
        # Speed up the callback validation query.
        await db["oauth_states"].create_index([
            ("user_id", 1),
            ("state_hash", 1),
            ("used", 1),
            ("expires_at", 1),
        ])
    except Exception:
        logger.exception("Failed to ensure Mongo indexes")


async def close_db():
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("MongoDB connection closed")
