"""Business profile: onboarding answers, research runs, user confirmation, assistant context."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import session_scope
from app.db.models import BusinessProfile, BusinessResearchRun
from app.models.user import CurrentUserContext
from app.research.search import build_search_provider
from app.research.website import analyze_website
from app.research.workflow import ResearchWorkflow
from app.services.onboarding_questions import PROFILE_COLUMNS, QUESTIONS, normalize_answers
from app.services.user_settings_service import (
    UserSettingsError,
    get_user_model_for_purpose,
    require_user_openai_api_key,
)
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

LIST_COLUMNS = {
    "business_model", "products_services", "customer_segments", "goals", "challenges",
    "existing_tools", "monitoring_preferences",
}

# Strong references to running research tasks so they aren't garbage-collected mid-run.
_running_tasks: set[asyncio.Task] = set()


class BusinessProfileError(Exception):
    status_code = 400

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code:
            self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_profile(session: AsyncSession, organization_id: str) -> BusinessProfile | None:
    result = await session.execute(select(BusinessProfile).where(BusinessProfile.organization_id == organization_id))
    return result.scalar_one_or_none()


async def _get_or_create_profile(session: AsyncSession, organization_id: str) -> BusinessProfile:
    profile = await get_profile(session, organization_id)
    if profile is None:
        profile = BusinessProfile(organization_id=organization_id, status="draft", answers={})
        session.add(profile)
        await session.flush()
    return profile


def answers_of(profile: BusinessProfile | None) -> dict:
    """All onboarding answers in one dict: profile columns plus industry-specific extras."""
    if profile is None:
        return {}
    data = dict(profile.answers or {})
    for column in PROFILE_COLUMNS:
        value = getattr(profile, column)
        if value not in (None, "", []):
            data[column] = value
    return data


def serialize_profile(profile: BusinessProfile | None) -> dict | None:
    if profile is None:
        return None
    return {
        "status": profile.status,
        "answers": answers_of(profile),
        "subdomain": profile.subdomain,
        "competitors": profile.competitors or [],
        "opportunities": profile.opportunities or [],
        "provenance": profile.provenance or {},
        "confirmed_at": profile.confirmed_at,
        "onboarding_dismissed": profile.onboarding_dismissed_at is not None,
        "updated_at": profile.updated_at,
    }


def serialize_run(run: BusinessResearchRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "status": run.status,
        "progress": run.progress or [],
        "result": run.result,
        "error": run.error,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


async def latest_run(session: AsyncSession, organization_id: str) -> BusinessResearchRun | None:
    result = await session.execute(
        select(BusinessResearchRun)
        .where(BusinessResearchRun.organization_id == organization_id)
        .order_by(BusinessResearchRun.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_run(session: AsyncSession, organization_id: str, run_id: str) -> BusinessResearchRun | None:
    result = await session.execute(
        select(BusinessResearchRun).where(
            BusinessResearchRun.id == run_id, BusinessResearchRun.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def save_answers(session: AsyncSession, actor: CurrentUserContext, raw: dict) -> BusinessProfile:
    clean = normalize_answers(raw)
    profile = await _get_or_create_profile(session, actor.organization.id)
    extras = {}
    for key, value in clean.items():
        if key in PROFILE_COLUMNS:
            setattr(profile, key, value)
        else:
            extras[key] = value
    # Clear profile columns the user emptied.
    for column in PROFILE_COLUMNS - clean.keys():
        setattr(profile, column, None)
    profile.answers = extras
    await session.flush()
    return profile


async def dismiss_onboarding(session: AsyncSession, actor: CurrentUserContext) -> None:
    profile = await _get_or_create_profile(session, actor.organization.id)
    profile.onboarding_dismissed_at = _now()
    await session.flush()


async def start_research(session: AsyncSession, actor: CurrentUserContext) -> BusinessResearchRun:
    profile = await get_profile(session, actor.organization.id)
    answers = answers_of(profile)
    if not answers.get("name"):
        raise BusinessProfileError("Save at least the business name before starting research.")
    try:
        # BYOK: research runs on the requesting user's OpenAI key.
        await require_user_openai_api_key(actor.user.id, session)
    except UserSettingsError as exc:
        raise BusinessProfileError("Research runs on your OpenAI API key. Add it in Settings first.") from exc

    run = BusinessResearchRun(
        organization_id=actor.organization.id,
        requested_by_user_id=actor.user.id,
        status="queued",
        input=answers,
        progress=[],
    )
    try:
        async with session.begin_nested():
            session.add(run)
    except IntegrityError as exc:
        raise BusinessProfileError("Research is already running for this organization.", 409) from exc
    return run


async def schedule_research_run(run_id: str) -> None:
    """Start the run in the background. Call only after the run row is committed.

    Must be async: Starlette runs sync background tasks in a worker thread, where
    asyncio.create_task has no event loop and the run would silently stay queued.
    """
    task = asyncio.create_task(execute_research_run(run_id))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)


async def _append_progress(run_id: str, message: str) -> None:
    async with session_scope() as session:
        run = await session.get(BusinessResearchRun, run_id)
        if run:
            run.progress = [*(run.progress or []), {"message": message, "at": _now().isoformat()}]


def _friendly_error(exc: Exception) -> str:
    text = str(exc)
    lowered = text.lower()
    if "api key" in lowered or "invalid_api_key" in lowered or "401" in lowered:
        return "OpenAI rejected the API key. Check it in Settings, then try again."
    if "rate limit" in lowered or "quota" in lowered or "429" in lowered:
        return "OpenAI rate limit or quota reached. Try again later."
    return f"Research failed: {text[:300]}"


async def execute_research_run(run_id: str, *, workflow_factory=None) -> None:
    """Run one research job end to end, recording progress, result, or failure on the row."""
    async with session_scope() as session:
        run = await session.get(BusinessResearchRun, run_id)
        if run is None or run.status != "queued":
            return
        run.status = "running"
        run.started_at = _now()
        user_id, run_input = run.requested_by_user_id, dict(run.input)

    try:
        workflow = await (workflow_factory or _build_workflow)(user_id, run_id)
        result = await workflow.run(run_input)
    except asyncio.CancelledError:
        await _finish_run(run_id, status="failed", error="Research was interrupted. Start it again.")
        raise
    except Exception as exc:
        logger.exception("research.run.failed run_id=%s", run_id)
        await _finish_run(run_id, status="failed", error=_friendly_error(exc))
        return
    await _finish_run(run_id, status="completed", result=result)


async def _finish_run(run_id: str, *, status: str, result: dict | None = None, error: str | None = None) -> None:
    async with session_scope() as session:
        run = await session.get(BusinessResearchRun, run_id)
        if run:
            run.status, run.result, run.error, run.finished_at = status, result, error, _now()


async def _build_workflow(user_id: str, run_id: str) -> ResearchWorkflow:
    async with session_scope() as session:
        api_key = await require_user_openai_api_key(user_id, session)
        model = await get_user_model_for_purpose(user_id, "primary", session)

    llm = ChatOpenAI(model=model, api_key=api_key, temperature=0, max_retries=2)

    async def structured(schema, system: str, human: str):
        return await llm.with_structured_output(schema).ainvoke(
            [SystemMessage(content=system), HumanMessage(content=human)]
        )

    async def progress(message: str) -> None:
        await _append_progress(run_id, message)

    return ResearchWorkflow(
        structured=structured,
        search=build_search_provider(user_api_key=api_key, model=model),
        analyze_website=lambda url: analyze_website(
            url, max_pages=settings.research_max_website_pages, crawler=settings.research_crawler
        ),
        progress=progress,
    )


async def recover_interrupted_runs() -> int:
    """Runs can't survive a restart (they execute in-process); mark leftovers as failed.

    Assumes a single backend process. With several workers this would fail another
    worker's live run; the durable job worker planned for scheduling replaces this.
    """
    async with session_scope() as session:
        result = await session.execute(
            update(BusinessResearchRun)
            .where(BusinessResearchRun.status.in_(("queued", "running")))
            .values(status="failed", error="Interrupted by a server restart. Start research again.", finished_at=_now())
        )
        return result.rowcount or 0


async def confirm_profile(session: AsyncSession, actor: CurrentUserContext, data: dict[str, Any]) -> BusinessProfile:
    """Store the profile exactly as the user reviewed it; only now does the assistant use it."""
    answers = {k: v for k, v in data.items() if k in PROFILE_COLUMNS or k == "country"}
    clean = normalize_answers({**answers_of(await get_profile(session, actor.organization.id)), **answers})
    if not clean.get("name"):
        raise BusinessProfileError("The business name is required.")
    profile = await save_answers(session, actor, clean)
    profile.subdomain = (data.get("subdomain") or "").strip()[:200] or None
    profile.competitors = data.get("competitors") or []
    profile.opportunities = data.get("opportunities") or []
    profile.provenance = data.get("provenance") or {}
    profile.status = "confirmed"
    profile.confirmed_at = _now()
    profile.confirmed_by_user_id = actor.user.id
    await session.flush()
    return profile


async def business_context_text(session: AsyncSession, organization_id: str) -> str:
    """Compact confirmed profile for the assistant's system prompt ('' when not confirmed)."""
    profile = await get_profile(session, organization_id)
    if profile is None or profile.status != "confirmed":
        return ""

    def fmt(value, question_id: str | None = None) -> str:
        # Show option labels ("Inventory and supply chain"), not stored codes ("inventory_supply").
        options = {o["value"]: o["label"] for o in QUESTIONS.get(question_id or "", {}).get("options", [])}
        values = value if isinstance(value, list) else [value]
        return ", ".join(options.get(v, str(v)) for v in values)

    lines = ["Confirmed by the organization; treat as known facts about the business you are assisting."]
    for label, key in (
        ("Business", "name"), ("Website", "website"), ("Location", "location"), ("Industry", "industry"),
        ("Niche", "subdomain"), ("Business model", "business_model"), ("Size", "scale"),
        ("Market reach", "geography"), ("About", "description"), ("Products/services", "products_services"),
        ("Customers", "customer_segments"), ("Goals", "goals"), ("Challenges", "challenges"),
        ("Tools in use", "existing_tools"), ("Wants monitored", "monitoring_preferences"),
    ):
        value = getattr(profile, key)
        if value not in (None, "", []):
            lines.append(f"- {label}: {fmt(value, key)}")
    for key, value in (profile.answers or {}).items():
        label = QUESTIONS[key]["label"].rstrip("?") if key in QUESTIONS else key.replace("_", " ").capitalize()
        lines.append(f"- {label}: {fmt(value, key)}")
    if profile.competitors:
        names = [c.get("name") for c in profile.competitors if isinstance(c, dict) and c.get("name")]
        if names:
            lines.append(f"- Known competitors: {', '.join(names[:8])}")
    if profile.opportunities:
        titles = [o.get("title") for o in profile.opportunities if isinstance(o, dict) and o.get("title")]
        if titles:
            lines.append(f"- Improvement areas the owner agreed to focus on: {'; '.join(titles[:6])}")
    return "\n".join(lines)[:3000]
