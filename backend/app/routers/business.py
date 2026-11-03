from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.base import get_db_session
from app.dependencies import BusinessManager, BusinessReader, CurrentUser
from app.services import business_profile_service as svc
from app.services.onboarding_questions import STEPS, AnswerError

router = APIRouter(prefix="/api/business-profile", tags=["business"])

Basis = Literal["user_provided", "verified", "estimated", "unknown", "edited"]


class SaveAnswersRequest(BaseModel):
    answers: dict


class ConfirmedCompetitor(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    website: Optional[str] = Field(default=None, max_length=500)
    competition: Literal["direct", "indirect"] = "direct"
    relative_scale: Literal["similar", "smaller", "larger", "much_larger", "unknown"] = "unknown"
    rationale: str = Field(default="", max_length=1000)
    sources: list[str] = Field(default_factory=list, max_length=10)
    added_by_user: bool = False


class ConfirmedOpportunity(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    area: str = Field(default="", max_length=100)
    rationale: str = Field(default="", max_length=1000)
    basis: Literal["evidence", "general_practice", "user_added"] = "user_added"
    sources: list[str] = Field(default_factory=list, max_length=10)


class FieldProvenance(BaseModel):
    basis: Basis
    sources: list[str] = Field(default_factory=list, max_length=10)


class ConfirmProfileRequest(BaseModel):
    """The profile as the user reviewed it. Fields mirror the onboarding question ids."""
    answers: dict
    subdomain: Optional[str] = Field(default=None, max_length=200)
    competitors: list[ConfirmedCompetitor] = Field(default_factory=list, max_length=20)
    opportunities: list[ConfirmedOpportunity] = Field(default_factory=list, max_length=20)
    provenance: dict[str, FieldProvenance] = Field(default_factory=dict)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.BusinessProfileError):
        return HTTPException(status_code=exc.status_code, detail=exc.message)
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/questions")
async def get_questions(user: CurrentUser):
    return {"steps": STEPS}


@router.get("")
async def get_business_profile(user: BusinessReader, session = Depends(get_db_session, scope="function")):
    profile = await svc.get_profile(session, user.organization.id)
    run = await svc.latest_run(session, user.organization.id)
    return {"profile": svc.serialize_profile(profile), "latest_run": svc.serialize_run(run)}


@router.put("/answers")
async def save_answers(body: SaveAnswersRequest, user: BusinessManager, session = Depends(get_db_session, scope="function")):
    try:
        profile = await svc.save_answers(session, user, body.answers)
    except AnswerError as exc:
        raise _http(exc) from exc
    return {"profile": svc.serialize_profile(profile)}


@router.post("/research")
async def start_research(
    user: BusinessManager,
    background: BackgroundTasks,
    session = Depends(get_db_session, scope="function"),
):
    try:
        run = await svc.start_research(session, user)
    except svc.BusinessProfileError as exc:
        raise _http(exc) from exc
    # Background tasks run after the response, i.e. after the session above has committed the run.
    background.add_task(svc.schedule_research_run, run.id)
    return {"run": svc.serialize_run(run)}


@router.get("/research/{run_id}")
async def get_research_run(run_id: str, user: BusinessReader, session = Depends(get_db_session, scope="function")):
    run = await svc.get_run(session, user.organization.id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    return {"run": svc.serialize_run(run)}


@router.post("/confirm")
async def confirm_profile(body: ConfirmProfileRequest, user: BusinessManager, session = Depends(get_db_session, scope="function")):
    data = {
        **body.answers,
        "subdomain": body.subdomain,
        "competitors": [c.model_dump() for c in body.competitors],
        "opportunities": [o.model_dump() for o in body.opportunities],
        "provenance": {k: v.model_dump() for k, v in body.provenance.items()},
    }
    try:
        profile = await svc.confirm_profile(session, user, data)
    except (svc.BusinessProfileError, AnswerError) as exc:
        raise _http(exc) from exc
    return {"profile": svc.serialize_profile(profile)}


@router.post("/dismiss-onboarding")
async def dismiss_onboarding(user: BusinessManager, session = Depends(get_db_session, scope="function")):
    await svc.dismiss_onboarding(session, user)
    return {"ok": True}
