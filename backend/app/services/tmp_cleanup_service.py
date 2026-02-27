import asyncio
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def chat_tmp_base_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "tmp" / "chats"


def delete_chat_tmp_dir(chat_id: str) -> None:
    base = chat_tmp_base_dir() / str(chat_id)
    if not base.exists():
        return
    try:
        shutil.rmtree(base, ignore_errors=True)
    except Exception:
        logger.exception("Failed to delete chat tmp dir: %s", base)


def _iter_chat_dirs() -> list[Path]:
    base = chat_tmp_base_dir()
    if not base.exists():
        return []
    return [p for p in base.iterdir() if p.is_dir()]


def sweep_old_chat_tmp_dirs(now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    ttl = timedelta(seconds=int(getattr(settings, "chat_tmp_ttl_seconds", 86400) or 86400))
    cutoff = now - ttl

    deleted = 0
    for d in _iter_chat_dirs():
        try:
            mtime = datetime.utcfromtimestamp(d.stat().st_mtime)
        except Exception:
            mtime = now

        if mtime < cutoff:
            try:
                shutil.rmtree(d, ignore_errors=True)
                deleted += 1
            except Exception:
                logger.exception("Failed to sweep tmp dir: %s", d)

    if deleted:
        logger.info("Swept %s old chat tmp dirs", deleted)
    return deleted


async def run_tmp_sweeper(stop_event: asyncio.Event) -> None:
    interval = int(getattr(settings, "chat_tmp_sweep_interval_seconds", 900) or 900)
    while not stop_event.is_set():
        try:
            sweep_old_chat_tmp_dirs()
        except Exception:
            logger.exception("Chat tmp sweeper failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue
