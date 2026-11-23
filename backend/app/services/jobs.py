"""A small durable job queue in Postgres.

Webhooks must answer within seconds, and work started with asyncio.create_task is lost if the
server restarts. Jobs are rows instead: a worker inside the API process claims due jobs with
`FOR UPDATE SKIP LOCKED` (so several server instances never take the same job), runs the
handler registered for the job's kind, and retries with backoff when it raises.

    await jobs.enqueue(session, "bot.inbound", {"message_id": "..."})

`enqueue` only adds the row to the caller's transaction; the worker sees it after commit and is
woken right away in this process, so a job normally starts within milliseconds.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import exists, or_, select, update
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import session_scope
from app.db.models.bot import Job

logger = logging.getLogger(__name__)

Handler = Callable[[dict], Awaitable[None]]

_handlers: dict[str, Handler] = {}
_wake = asyncio.Event()
POLL_SECONDS = 5.0
# A job still "running" after this long belonged to a process that died; it is picked up again.
STALE_AFTER = timedelta(minutes=10)
CONCURRENCY = 4


def _now() -> datetime:
    return datetime.now(timezone.utc)


def handler(kind: str):
    """Register the coroutine that runs jobs of this kind."""
    def register(fn: Handler) -> Handler:
        _handlers[kind] = fn
        return fn
    return register


async def enqueue(session: AsyncSession, kind: str, payload: dict, *, delay: float = 0, max_attempts: int = 3,
                  key: str | None = None) -> Job:
    """Queue a job. Jobs sharing a `key` never run at the same time and run in order."""
    now = _now()
    job = Job(kind=kind, key=key, payload=payload, status="queued", attempts=0, max_attempts=max_attempts,
              run_after=now + timedelta(seconds=delay), created_at=now, updated_at=now)
    session.add(job)
    await session.flush()
    _wake.set()
    return job


async def _claim(limit: int) -> list[Job]:
    now = _now()
    running = aliased(Job)
    earlier = aliased(Job)
    async with session_scope() as session:
        rows = (await session.execute(
            select(Job)
            .where(or_(
                (Job.status == "queued") & (Job.run_after <= now),
                (Job.status == "running") & (Job.locked_at < now - STALE_AFTER),
            ))
            # One at a time per key: skip a key with a job still running, or an older job waiting.
            .where(or_(Job.key.is_(None), ~exists().where(
                running.key == Job.key, running.id != Job.id, running.status == "running",
                running.locked_at >= now - STALE_AFTER)))
            .where(or_(Job.key.is_(None), ~exists().where(
                earlier.key == Job.key, earlier.status == "queued", earlier.created_at < Job.created_at)))
            .order_by(Job.run_after)
            .limit(limit * 3)
            .with_for_update(skip_locked=True)
        )).scalars().all()
        seen: set[str] = set()
        claimed: list[Job] = []
        for job in rows:
            if job.key and job.key in seen:
                continue
            if job.key:
                seen.add(job.key)
            claimed.append(job)
            if len(claimed) >= limit:
                break
        rows = claimed
        for job in rows:
            job.status, job.locked_at, job.attempts, job.updated_at = "running", now, job.attempts + 1, now
        return list(rows)


def _backoff(attempt: int) -> timedelta:
    return timedelta(seconds=min(5 * 4 ** (attempt - 1), 600))  # 5s, 20s, 80s, ... up to 10 min


async def run_job(job: Job) -> None:
    fn = _handlers.get(job.kind)
    error: str | None = None
    if fn is None:
        error = f"No handler for job kind '{job.kind}'"
    else:
        try:
            await fn(job.payload or {})
        except Exception as exc:  # noqa: BLE001 - recorded on the job and retried
            logger.warning("jobs.failed kind=%s id=%s attempt=%s", job.kind, job.id, job.attempts, exc_info=True)
            error = f"{exc.__class__.__name__}: {exc}"[:2000]
    async with session_scope() as session:
        values: dict = {"updated_at": _now(), "locked_at": None}
        if error is None:
            values["status"] = "done"
        elif job.attempts >= job.max_attempts or fn is None:
            values.update(status="failed", last_error=error)
        else:
            values.update(status="queued", last_error=error, run_after=_now() + _backoff(job.attempts))
        await session.execute(update(Job).where(Job.id == job.id).values(**values))


async def run_due_jobs(limit: int = CONCURRENCY) -> int:
    """Claim and run one batch of what's due now. Used by the worker."""
    claimed = await _claim(limit)
    if claimed:
        await asyncio.gather(*(run_job(job) for job in claimed))
    return len(claimed)


async def drain(max_batches: int = 50) -> int:
    """Run batches until nothing is due (tests and scripts)."""
    total = 0
    for _ in range(max_batches):
        ran = await run_due_jobs()
        if not ran:
            break
        total += ran
    return total


async def cleanup(older_than: timedelta = timedelta(days=7)) -> None:
    from sqlalchemy import delete

    async with session_scope() as session:
        await session.execute(delete(Job).where(Job.status.in_(("done", "failed")), Job.updated_at < _now() - older_than))


async def run_worker(stop: asyncio.Event) -> None:
    logger.info("jobs.worker started")
    last_cleanup = _now()
    while not stop.is_set():
        try:
            ran = await run_due_jobs()
            if _now() - last_cleanup > timedelta(hours=6):
                await cleanup()
                from app.services.bot_service import purge_old_messages
                await purge_old_messages()
                last_cleanup = _now()
        except Exception:
            logger.exception("jobs.worker loop error")
            ran = 0
        if ran:
            continue  # there may be more waiting
        _wake.clear()
        waiters = {asyncio.create_task(_wake.wait()), asyncio.create_task(stop.wait())}
        _, pending = await asyncio.wait(waiters, timeout=POLL_SECONDS, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    logger.info("jobs.worker stopped")
