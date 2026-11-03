"""Business onboarding, research runs, confirmation, and assistant context."""
import pytest


async def _join(make_user, owner_ctx, uid, email, role):
    from app.db.base import session_scope
    from app.repositories import UserRepository

    personal = await make_user(uid, email)
    async with session_scope() as session:
        await UserRepository.create_organization_member(session, owner_ctx.organization.id, personal.user.id, role=role)
    return await make_user(uid, email, organization_id=owner_ctx.organization.id)


ANSWERS = {
    "name": "Sharma Grocers",
    "location": "Andheri, Mumbai",
    "country": "IN",
    "industry": "retail",
    "business_model": ["B2C"],
    "scale": "small",
    "sales_channels": ["in_store", "delivery_apps"],
    "location_count": "2",
    "goals": ["improve_retention"],
    "monitoring_preferences": ["sales_revenue", "competitors"],
}


@pytest.fixture
def no_background(monkeypatch):
    """Keep research runs queued instead of launching the real workflow."""
    from app.services import business_profile_service

    scheduled = []

    async def record(run_id):
        scheduled.append(run_id)

    monkeypatch.setattr(business_profile_service, "schedule_research_run", record)
    return scheduled


async def test_questions_and_answers_round_trip(make_user, client_for):
    owner = client_for(await make_user("uid-o", "owner@acme.com"))

    steps = (await owner.get("/api/business-profile/questions")).json()["steps"]
    questions = {q["id"]: q for s in steps for q in s["questions"]}
    assert questions["sales_channels"]["show_if"] == {"field": "industry", "in": ["retail", "ecommerce", "food_beverage"]}

    assert (await owner.get("/api/business-profile")).json() == {"profile": None, "latest_run": None}

    saved = await owner.put("/api/business-profile/answers", json={"answers": {**ANSWERS, "unknown_field": "x"}})
    assert saved.status_code == 200, saved.text
    answers = saved.json()["profile"]["answers"]
    assert answers["location_count"] == 2 and answers["sales_channels"] == ["in_store", "delivery_apps"]
    assert "unknown_field" not in answers
    assert saved.json()["profile"]["status"] == "draft"

    bad = await owner.put("/api/business-profile/answers", json={"answers": {"name": "X", "industry": "spaceships"}})
    assert bad.status_code == 400 and "valid option" in bad.json()["detail"]
    bad = await owner.put("/api/business-profile/answers", json={"answers": {"name": "X", "country": "India"}})
    assert bad.status_code == 400


async def test_permissions(make_user, client_for, no_background):
    owner_ctx = await make_user("uid-o", "owner@acme.com")
    member = client_for(await _join(make_user, owner_ctx, "uid-m", "m@acme.com", "member"))
    viewer = client_for(await _join(make_user, owner_ctx, "uid-v", "v@acme.com", "viewer"))

    assert (await viewer.get("/api/business-profile")).status_code == 200
    assert (await member.put("/api/business-profile/answers", json={"answers": ANSWERS})).status_code == 403
    assert (await member.post("/api/business-profile/research")).status_code == 403
    assert (await member.post("/api/business-profile/confirm", json={"answers": ANSWERS})).status_code == 403
    assert (await viewer.post("/api/business-profile/dismiss-onboarding")).status_code == 403

    # Another organization never sees this one's profile.
    owner = client_for(owner_ctx)
    await owner.put("/api/business-profile/answers", json={"answers": ANSWERS})
    outsider = client_for(await make_user("uid-x", "x@other.com"))
    assert (await outsider.get("/api/business-profile")).json()["profile"] is None


async def test_research_requires_name_and_api_key_and_runs_one_at_a_time(make_user, client_for, no_background):
    owner = client_for(await make_user("uid-o", "owner@acme.com"))

    resp = await owner.post("/api/business-profile/research")
    assert resp.status_code == 400 and "business name" in resp.json()["detail"]

    await owner.put("/api/business-profile/answers", json={"answers": {"name": "Sharma Grocers"}})
    resp = await owner.post("/api/business-profile/research")
    assert resp.status_code == 400 and "city and country" in resp.json()["detail"]

    await owner.put("/api/business-profile/answers", json={"answers": ANSWERS})
    resp = await owner.post("/api/business-profile/research")
    assert resp.status_code == 400 and "API key" in resp.json()["detail"]

    await owner.patch("/api/settings/ai", json={"openai_api_key": "sk-test-not-real"})
    started = await owner.post("/api/business-profile/research")
    assert started.status_code == 200
    run = started.json()["run"]
    assert run["status"] == "queued"
    assert no_background == [run["id"]]

    assert (await owner.post("/api/business-profile/research")).status_code == 409
    latest = (await owner.get("/api/business-profile")).json()["latest_run"]
    assert latest["id"] == run["id"]


async def test_run_execution_success_failure_and_restart_recovery(make_user, client_for, no_background):
    from app.services import business_profile_service as svc

    owner = client_for(await make_user("uid-o", "owner@acme.com"))
    await owner.patch("/api/settings/ai", json={"openai_api_key": "sk-test-not-real"})
    await owner.put("/api/business-profile/answers", json={"answers": ANSWERS})

    class FakeWorkflow:
        def __init__(self, progress):
            self.progress = progress

        async def run(self, data):
            await self.progress("Reading the website")
            assert data["name"] == "Sharma Grocers"  # runs on the saved answers
            return {"profile": {"name": {"value": data["name"], "basis": "user_provided"}}, "competitors": []}

    async def factory(user_id, run_id):
        return FakeWorkflow(lambda message: svc._append_progress(run_id, message))

    run_id = (await owner.post("/api/business-profile/research")).json()["run"]["id"]
    await svc.execute_research_run(run_id, workflow_factory=factory)
    done = (await owner.get(f"/api/business-profile/research/{run_id}")).json()["run"]
    assert done["status"] == "completed"
    assert [p["message"] for p in done["progress"]] == ["Reading the website"]
    assert done["result"]["profile"]["name"]["value"] == "Sharma Grocers"

    async def failing_factory(user_id, run_id):
        class Boom:
            async def run(self, data):
                raise RuntimeError("Error code: 401 - invalid_api_key")
        return Boom()

    run_id = (await owner.post("/api/business-profile/research")).json()["run"]["id"]
    await svc.execute_research_run(run_id, workflow_factory=failing_factory)
    failed = (await owner.get(f"/api/business-profile/research/{run_id}")).json()["run"]
    assert failed["status"] == "failed" and "rejected the API key" in failed["error"]

    run_id = (await owner.post("/api/business-profile/research")).json()["run"]["id"]
    assert await svc.recover_interrupted_runs() == 1
    recovered = (await owner.get(f"/api/business-profile/research/{run_id}")).json()["run"]
    assert recovered["status"] == "failed" and "restart" in recovered["error"]
    # The org can start a new run once the old one is closed.
    assert (await owner.post("/api/business-profile/research")).status_code == 200

    other_org = client_for(await make_user("uid-x", "x@other.com"))
    assert (await other_org.get(f"/api/business-profile/research/{run_id}")).status_code == 404


async def test_confirm_profile_feeds_the_assistant(make_user, client_for):
    from app.agents.business_context import with_business_context
    from app.db.base import session_scope
    from app.services.business_profile_service import business_context_text

    owner_ctx = await make_user("uid-o", "owner@acme.com")
    owner = client_for(owner_ctx)
    await owner.put("/api/business-profile/answers", json={"answers": ANSWERS})

    async with session_scope() as session:
        # Drafts are never used as assistant context.
        assert await business_context_text(session, owner_ctx.organization.id) == ""

    confirm = await owner.post("/api/business-profile/confirm", json={
        "answers": {**ANSWERS, "products_services": ["groceries", "home delivery"]},
        "subdomain": "grocery",
        "competitors": [
            {"name": "Patel Provisions", "competition": "direct", "relative_scale": "similar",
             "rationale": "Same street", "sources": ["https://patel.example"]},
            {"name": "Corner Mart", "added_by_user": True},
        ],
        "opportunities": [{"title": "Repeat-purchase analysis", "area": "customer retention", "basis": "evidence"}],
        "provenance": {"subdomain": {"basis": "verified", "sources": ["https://sharma.example"]}},
    })
    assert confirm.status_code == 200, confirm.text
    profile = confirm.json()["profile"]
    assert profile["status"] == "confirmed" and profile["confirmed_at"]
    assert profile["subdomain"] == "grocery" and len(profile["competitors"]) == 2

    async with session_scope() as session:
        context = await business_context_text(session, owner_ctx.organization.id)
    assert "Business: Sharma Grocers" in context and "Niche: grocery" in context
    assert "Known competitors: Patel Provisions, Corner Mart" in context
    assert "Where do you sell: In store, Delivery apps" in context
    assert "Wants monitored: Sales and revenue, Competitor pricing and activity" in context
    prompt = with_business_context("SYSTEM", {"business_context": context})
    assert prompt.startswith("SYSTEM\n\n[Today] ") and "\n\n[Business Context]\nConfirmed by" in prompt
    assert "[Business Context]" not in with_business_context("SYSTEM", {})

    bad = await owner.post("/api/business-profile/confirm", json={"answers": {"name": ""}, "competitors": [{"name": ""}]})
    assert bad.status_code == 422


async def test_dismiss_onboarding(make_user, client_for):
    owner = client_for(await make_user("uid-o", "owner@acme.com"))
    assert (await owner.post("/api/business-profile/dismiss-onboarding")).status_code == 200
    assert (await owner.get("/api/business-profile")).json()["profile"]["onboarding_dismissed"] is True


async def test_starting_research_actually_launches_the_run(make_user, client_for, monkeypatch):
    """Through the real BackgroundTasks -> schedule_research_run path (regression: it ran in a
    worker thread without an event loop and runs stayed queued forever)."""
    import asyncio

    from app.services import business_profile_service as svc

    launched = asyncio.Event()

    async def fake_execute(run_id, **_):
        launched.set()

    monkeypatch.setattr(svc, "execute_research_run", fake_execute)
    owner = client_for(await make_user("uid-o", "owner@acme.com"))
    await owner.patch("/api/settings/ai", json={"openai_api_key": "sk-test-not-real"})
    await owner.put("/api/business-profile/answers", json={"answers": ANSWERS})
    assert (await owner.post("/api/business-profile/research")).status_code == 200
    await asyncio.wait_for(launched.wait(), timeout=5)
