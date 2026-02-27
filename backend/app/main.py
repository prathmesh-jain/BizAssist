import logging
from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import connect_db, close_db
from app.utils.logger import setup_logging
from app.routers import chat, documents, integrations

setup_logging()
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting AI Business Assistant...")
    await connect_db()
    # Pre-compile the agent graph on startup to avoid cold-start latency
    from app.agents.graph import get_compiled_graph
    get_compiled_graph()

    # Background cleanup: sweep old chat tmp attachments
    from app.services.tmp_cleanup_service import run_tmp_sweeper
    stop_event = asyncio.Event()
    sweeper_task = asyncio.create_task(run_tmp_sweeper(stop_event))
    logger.info("Application ready ✓")
    yield
    # Shutdown
    stop_event.set()
    try:
        await sweeper_task
    except Exception:
        logger.exception("Error stopping tmp sweeper")
    await close_db()
    logger.info("Application shutdown complete")


app = FastAPI(
    title="AI Business Operations Assistant",
    description="A production-quality AI-powered business operations assistant.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(chat.router)
app.include_router(documents.router)
app.include_router(integrations.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "AI Business Assistant"}
