"""Long-term memory: isolation, permissions, replacement/undo, the per-turn context, activity,
agent tools, and automatic extraction (with a fake model)."""
import pytest

from app.services import memory_service
from app.services.memory_service import (
    MemoryActor, describe_tool_activity, looks_secret, normalize_topic, worth_extracting,
)
from app.services import bm25, memory_index


# ---------- pure helpers ----------

@pytest.mark.no_db
def test_secret_detection_and_topics():
    assert looks_secret("my api key is sk-abcdefghijklmnopqrstuvwx")
    assert looks_secret("card 4111 1111 1111 1111")
    assert looks_secret("The wifi password is hunter2")
    assert not looks_secret("Sharma Packaging is our main supplier; contact Meera.")
    assert not looks_secret("We pay net-30, invoice 2024-118 is due 5 Dec")
    assert normalize_topic("Supplier / Packaging!") == "supplier_packaging"
    assert normalize_topic("   ") is None


@pytest.mark.no_db
def test_activity_descriptions_only_for_successful_writes():
    created = describe_tool_activity(
        "calendar_create_event",
        {"title": "Sharma catch-up", "attendees": ["meera@sharma.in"]},
        {"ok": True, "event": {"title": "Sharma catch-up", "start": "2026-11-26T15:00:00+05:30", "meet_link": "https://meet"}},
    )
    assert created == ("Scheduled “Sharma catch-up” for Thu 26 Nov 2026, 15:00 with meera@sharma.in with a Google Meet link.", "personal")
    rows = describe_tool_activity("sheets_append_values", {"range_a1": "Expenses!A:D", "values": [[1], [2]]}, {"ok": True})
    assert rows == ("Added 2 rows to the spreadsheet (Expenses!A:D).", "shared")
    assert describe_tool_activity("sheets_append_values", {}, {"ok": False, "error": "x"}) is None
    assert describe_tool_activity("calendar_create_event", {}, {"ok": False, "cancelled": True}) is None
    assert describe_tool_activity("sheets_read_range", {}, {"ok": True}) is None


@pytest.mark.no_db
def test_extraction_skips_trivial_messages_and_search_terms_drop_noise():
    assert not worth_extracting("thanks!")
    assert not worth_extracting("ok")
    assert worth_extracting("Our main packaging supplier is Sharma Packaging")
    assert bm25.tokenize("What is the price of the Diwali hamper?") == ["price", "diwali", "hamper"]
    # Identifiers stay whole for exact matches, and their parts are searchable too.
    assert bm25.tokenize("Invoice INV-2024-118") == ["invoic", "inv-2024-118", "inv", "2024", "118"]
    assert bm25.query_vector("the and of").indices == []


# ---------- fixtures ----------

# Words a real embedding model would place close together. The fake model below maps each group to
# one dimension, so "cartons" is near "boxes" even though they share no letters.
_CONCEPTS = {
    "packaging": {"box", "boxes", "carton", "cartons", "packaging", "packag", "crate", "crates"},
    "supplier": {"supplier", "suppliers", "supplies", "vendor", "vendors", "sends", "send"},
    "money": {"rent", "pay", "paid", "payment", "fee", "invoice", "cost", "price"},
    "freight": {"freight", "shipping", "courier", "transport", "delivery"},
}


def _fake_vector(text: str) -> list[float]:
    import math
    import re
    import zlib

    size = memory_index._settings().embedding_vector_size
    vec = [0.0] * size
    for word in re.findall(r"[a-z]+", text.lower()):
        for i, (_, words) in enumerate(_CONCEPTS.items()):
            if word in words:
                vec[i] += 1.0
        vec[10 + zlib.crc32(word.encode()) % (size - 10)] += 0.15  # weak per-word signal
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@pytest.fixture(autouse=True)
def qdrant(monkeypatch):
    """A fresh in-memory Qdrant per test, and a fake embedding model used only when a key is present."""
    from qdrant_client import QdrantClient

    from app.services import qdrant_service

    client = QdrantClient(":memory:")
    monkeypatch.setattr(qdrant_service, "get_qdrant_client", lambda: client)
    memory_index.reset_collection_cache()
    calls: list[str] = []

    async def fake_embed(texts, api_key):
        if not api_key or not texts:
            return None
        calls.append(api_key)
        return [_fake_vector(t) for t in texts]

    monkeypatch.setattr(memory_index, "embed", fake_embed)
    yield client
    memory_index.reset_collection_cache()

@pytest.fixture
async def team(make_user):
    """An owner, a viewer in the owner's organization, and an outsider in another organization."""
    from app.db.base import session_scope
    from app.repositories import UserRepository

    owner = await make_user("uid-owner", "owner@shop.test")
    viewer_home = await make_user("uid-viewer", "viewer@shop.test")
    async with session_scope() as session:
        await UserRepository.create_organization_member(session, owner.organization.id, viewer_home.user.id, role="viewer")
    viewer = await make_user("uid-viewer", "viewer@shop.test", organization_id=owner.organization.id)
    outsider = await make_user("uid-out", "out@other.test")
    return owner, viewer, outsider


def _actor(ctx):
    return MemoryActor(ctx.organization.id, ctx.user.id, ctx.role)


# ---------- API ----------

async def test_shared_and_personal_visibility_across_people_and_organizations(team, client_for):
    owner, viewer, outsider = team
    o, v, x = client_for(owner), client_for(viewer), client_for(outsider)

    shared = await o.post("/api/memory", json={"content": "We pay suppliers net-30.", "kind": "fact", "scope": "shared"})
    assert shared.status_code == 200, shared.text
    personal = await o.post("/api/memory", json={"content": "Show amounts in lakhs.", "kind": "preference"})
    assert personal.json()["memory"]["scope"] == "personal"  # preferences are always personal

    owner_view = {m["content"] for m in (await o.get("/api/memory")).json()["memories"]}
    viewer_view = {m["content"] for m in (await v.get("/api/memory")).json()["memories"]}
    outsider_view = (await x.get("/api/memory")).json()["memories"]
    assert owner_view == {"We pay suppliers net-30.", "Show amounts in lakhs."}
    assert viewer_view == {"We pay suppliers net-30."}  # not the owner's personal preference
    assert outsider_view == []

    # The viewer can see the shared memory but not change it; the outsider can't even find it.
    memory_id = shared.json()["memory"]["id"]
    assert (await v.patch(f"/api/memory/{memory_id}", json={"content": "x"})).status_code == 400
    assert (await v.delete(f"/api/memory/{memory_id}")).status_code == 403
    assert (await x.delete(f"/api/memory/{memory_id}")).status_code == 404


async def test_viewers_save_personal_only_and_secrets_are_refused(team, client_for):
    owner, viewer, _ = team
    v = client_for(viewer)
    assert (await v.post("/api/memory", json={"content": "We open at 9", "scope": "shared"})).status_code == 403
    ok = await v.post("/api/memory", json={"content": "I handle procurement.", "scope": "personal"})
    assert ok.status_code == 200 and ok.json()["memory"]["scope"] == "personal"
    listing = (await v.get("/api/memory")).json()
    assert listing["can_write_shared"] is False

    o = client_for(owner)
    refused = await o.post("/api/memory", json={"content": "The bank password is Diwali2026"})
    assert refused.status_code == 400 and "secret" in refused.json()["detail"]


async def test_same_topic_replaces_and_undo_restores(team, client_for):
    owner, _, _ = team
    o = client_for(owner)
    first = (await o.post("/api/memory", json={"content": "Freight goes with BlueDart.", "topic": "freight_partner"})).json()
    second = (await o.post("/api/memory", json={"content": "Freight goes with Northline from December.", "topic": "freight_partner"})).json()
    assert second["action"] == "updated" and second["memory"]["replaced"] is True
    assert [m["content"] for m in (await o.get("/api/memory")).json()["memories"]] == ["Freight goes with Northline from December."]

    undone = (await o.post(f"/api/memory/{second['memory']['id']}/undo")).json()
    assert undone["restored"]["id"] == first["memory"]["id"]
    assert [m["content"] for m in (await o.get("/api/memory")).json()["memories"]] == ["Freight goes with BlueDart."]

    # Saving the exact same thing twice doesn't create a duplicate.
    again = (await o.post("/api/memory", json={"content": "freight goes with bluedart."})).json()
    assert again["action"] == "unchanged"


async def test_pin_edit_search_and_settings_toggle(team, client_for):
    owner, _, _ = team
    o = client_for(owner)
    a = (await o.post("/api/memory", json={"content": "Rent is due on the 5th."})).json()["memory"]
    await o.post("/api/memory", json={"content": "Meera at Sharma Packaging handles our orders.", "kind": "contact"})
    assert (await o.patch(f"/api/memory/{a['id']}", json={"pinned": True})).json()["memory"]["pinned"] is True
    listing = (await o.get("/api/memory")).json()["memories"]
    assert listing[0]["id"] == a["id"]  # pinned first
    found = (await o.get("/api/memory", params={"q": "sharma orders"})).json()["memories"]
    assert [m["kind"] for m in found] == ["contact"]
    edited = (await o.patch(f"/api/memory/{a['id']}", json={"content": "Rent is due on the 7th."})).json()
    # Edits are versioned: a new memory replaces the old one, keeps the pin, and undo restores it.
    assert edited["memory"]["content"] == "Rent is due on the 7th." and edited["replaced_id"] == a["id"]
    assert edited["memory"]["pinned"] is True and edited["memory"]["replaced"] is True
    contents = [m["content"] for m in (await o.get("/api/memory")).json()["memories"]]
    assert "Rent is due on the 5th." not in contents
    await o.post(f"/api/memory/{edited['memory']['id']}/undo")
    assert "Rent is due on the 5th." in [m["content"] for m in (await o.get("/api/memory")).json()["memories"]]

    assert (await o.get("/api/memory/settings")).json() == {"enabled": True}
    assert (await o.patch("/api/memory/settings", json={"enabled": False})).json() == {"enabled": False}
    assert (await o.get("/api/memory")).json()["enabled"] is False


# ---------- per-turn context ----------

async def test_memory_context_is_scoped_relevant_and_respects_the_switch(team):
    from app.db.base import session_scope

    owner, viewer, outsider = team
    async with session_scope() as session:
        await memory_service.remember(session, _actor(owner), content="Sharma Packaging supplies our boxes.", kind="contact")
        await memory_service.remember(session, _actor(owner), content="Owner likes short answers.", kind="preference")
        await memory_service.remember(session, _actor(outsider), content="Outsider secret plan for packaging.")
    await memory_service.record_activity(
        organization_id=owner.organization.id, user_id=owner.user.id, content="Added 3 rows to the spreadsheet.",
    )

    async with session_scope() as session:
        owner_ctx = await memory_service.build_memory_context(
            session, organization_id=owner.organization.id, user_id=owner.user.id, query="who supplies packaging?")
        viewer_ctx = await memory_service.build_memory_context(
            session, organization_id=viewer.organization.id, user_id=viewer.user.id, query="packaging")
    assert "Sharma Packaging supplies our boxes." in owner_ctx
    assert "Owner likes short answers." in owner_ctx
    assert "Added 3 rows to the spreadsheet." in owner_ctx and "Recent activity" in owner_ctx
    assert "Outsider" not in owner_ctx
    assert "Sharma Packaging" in viewer_ctx and "short answers" not in viewer_ctx

    async with session_scope() as session:
        await memory_service.set_memory_enabled(session, owner.user.id, False)
    async with session_scope() as session:
        assert await memory_service.build_memory_context(
            session, organization_id=owner.organization.id, user_id=owner.user.id, query="packaging") == ""


# ---------- agent tools ----------

async def test_remember_forget_and_recall_tools(team):
    from app.tools.memory_tools import get_memory_tools

    owner, viewer, _ = team
    tools = {t.name: t for t in get_memory_tools(
        organization_id=owner.organization.id, user_id=owner.user.id, role=owner.role, chat_id=None)}
    saved = await tools["remember"].ainvoke({"content": "GST is filed by Anita every quarter.", "topic": "gst_filing"})
    assert saved["ok"] and saved["action"] == "added" and saved["memory"]["scope"] == "shared"
    recalled = await tools["recall_memory"].ainvoke({"query": "who files GST"})
    assert [m["content"] for m in recalled["memories"]] == ["GST is filed by Anita every quarter."]
    gone = await tools["forget_memory"].ainvoke({"query": "GST filing"})
    assert gone["ok"] and gone["action"] == "deleted"
    assert (await tools["recall_memory"].ainvoke({"query": "GST"}))["memories"] == []

    viewer_tools = {t.name: t for t in get_memory_tools(
        organization_id=viewer.organization.id, user_id=viewer.user.id, role=viewer.role, chat_id=None)}
    mine = await viewer_tools["remember"].ainvoke({"content": "Viewer works the weekend shift."})
    assert mine["memory"]["scope"] == "personal"  # viewers' business facts are kept personal
    refused = await viewer_tools["remember"].ainvoke({"content": "The safe pin is 4821"})
    assert refused["ok"] is False


# ---------- automatic extraction ----------

@pytest.fixture
def fake_model(monkeypatch):
    """Make the extraction model return whatever ops the test queues."""
    from app.services import llm_providers, llm_service

    queued: list = []

    async def fake_get_llm(**_):
        return object()

    class Runner:
        async def ainvoke(self, _messages):
            item = queued.pop(0)
            if isinstance(item, Exception):
                raise item
            return memory_service._MemoryOps(ops=[memory_service._MemoryOp(**op) for op in item])

    monkeypatch.setattr(llm_service, "get_llm", fake_get_llm)
    monkeypatch.setattr(llm_providers, "structured", lambda llm, schema: Runner())
    return queued


async def test_extraction_adds_updates_and_deletes(team, fake_model):
    from app.db.base import session_scope
    from app.repositories.memory_repository import MemoryRepository

    owner, _, _ = team
    kw = dict(organization_id=owner.organization.id, user_id=owner.user.id, role=owner.role, chat_id=None)

    fake_model.append([
        {"action": "add", "kind": "contact", "scope": "business", "topic": "supplier_packaging",
         "content": "Sharma Packaging is the main packaging supplier."},
        {"action": "add", "kind": "preference", "scope": "business", "topic": "currency",
         "content": "Prefers amounts in lakhs."},
    ])
    changes = await memory_service.extract_memories(
        **kw, user_text="Our packaging supplier is Sharma Packaging, and show amounts in lakhs please.",
        assistant_text="Noted.")
    assert [(c["action"], c["scope"]) for c in changes] == [("added", "shared"), ("added", "personal")]

    async with session_scope() as session:
        supplier = (await memory_service.find_relevant(session, _actor(owner), "packaging supplier"))[0][0]
    fake_model.append([{"action": "update", "kind": "contact", "target_id": supplier.id,
                        "content": "Kumar Boxes is the main packaging supplier now."}])
    changes = await memory_service.extract_memories(
        **kw, user_text="We switched packaging supplier to Kumar Boxes this month.", assistant_text="Got it.")
    assert changes[0]["action"] == "updated"

    async with session_scope() as session:
        rows, _ = await MemoryRepository.list_visible(session, owner.organization.id, owner.user.id)
        current = {m.content for m, _ in rows}
        new_supplier = next(m for m, _ in rows if "Kumar" in m.content)
    assert "Kumar Boxes is the main packaging supplier now." in current
    assert "Sharma Packaging is the main packaging supplier." not in current

    fake_model.append([{"action": "delete", "target_id": new_supplier.id}])
    changes = await memory_service.extract_memories(
        **kw, user_text="Forget the packaging supplier detail, it's not right.", assistant_text="Done.")
    assert changes[0]["action"] == "deleted"


async def test_extraction_never_raises_and_respects_trivial_turns(team, fake_model):
    owner, _, _ = team
    kw = dict(organization_id=owner.organization.id, user_id=owner.user.id, role=owner.role, chat_id=None)
    assert await memory_service.extract_memories(**kw, user_text="thanks!", assistant_text="Welcome") == []
    fake_model.append(RuntimeError("provider down"))
    assert await memory_service.extract_memories(
        **kw, user_text="Our shop closes at 10 pm on Saturdays.", assistant_text="Noted") == []
    # Delete/update ops for ids the model wasn't shown are ignored.
    fake_model.append([{"action": "delete", "target_id": "not-a-real-id"}])
    assert await memory_service.extract_memories(
        **kw, user_text="Remove that old note about the shop hours please.", assistant_text="Ok") == []


async def test_leaving_an_organization_deletes_personal_memories_there(team):
    from app.db.base import session_scope
    from app.repositories.memory_repository import MemoryRepository
    from app.services import membership_service

    owner, viewer, _ = team
    async with session_scope() as session:
        await memory_service.remember(session, _actor(viewer), content="Viewer prefers mornings.", kind="preference")
        await memory_service.remember(session, _actor(owner), content="The shop opens at 9.")
    async with session_scope() as session:
        await membership_service.leave_organization(session, viewer)
    async with session_scope() as session:
        rows, _ = await MemoryRepository.list_visible(session, owner.organization.id, viewer.user.id)
    assert [m.content for m, _ in rows] == ["The shop opens at 9."]


# ---------- chat integration ----------

@pytest.mark.no_db
def test_memory_block_is_added_to_agent_prompts_and_tool_results_become_ui_events():
    import json

    from app.agents.business_context import with_business_context
    from app.services.chat_service import memory_change_from_tool

    prompt = with_business_context("SYSTEM", {"business_context": "Kiran Stores", "memory_context": "About the business:\n- x"})
    assert prompt.index("[Business Context]") < prompt.index("[Memory]")
    assert "[Memory]" not in with_business_context("SYSTEM", {})

    saved = json.dumps({"ok": True, "action": "added", "memory": {"id": "m1", "content": "c", "scope": "shared"}})
    assert memory_change_from_tool("remember", saved) == {"action": "added", "id": "m1", "content": "c", "scope": "shared"}
    assert memory_change_from_tool("remember", json.dumps({"ok": True, "action": "unchanged", "memory": {}})) is None
    assert memory_change_from_tool("remember", json.dumps({"ok": False, "error": "x"})) is None
    assert memory_change_from_tool("rag_retrieve", saved) is None


# ---------- hybrid search (Qdrant: meaning + BM25) ----------

async def _set_openai_key(client, key="sk-test-key-for-embeddings"):
    assert (await client.patch("/api/settings/ai", json={"openai_api_key": key})).status_code == 200


async def test_meaning_based_matches_need_an_embedding_key(team, client_for):
    owner, _, _ = team
    o = client_for(owner)
    await o.post("/api/memory", json={"content": "Sharma Packaging supplies our boxes.", "kind": "contact"})

    # No key: keyword search only. "cartons" shares no word with the memory, so nothing comes back.
    listing = (await o.get("/api/memory", params={"q": "who sends our cartons"})).json()
    assert listing["vector_search"] is False and listing["memories"] == []
    # A shared keyword is still found without a key.
    assert len((await o.get("/api/memory", params={"q": "sharma"})).json()["memories"]) == 1

    # With a key, the meaning vector is backfilled on the next save and "cartons" now finds "boxes".
    await _set_openai_key(o)
    await o.post("/api/memory", json={"content": "Rent is due on the 5th.", "kind": "fact"})
    listing = (await o.get("/api/memory", params={"q": "who sends our cartons"})).json()
    assert listing["vector_search"] is True
    assert [m["content"] for m in listing["memories"]][0] == "Sharma Packaging supplies our boxes."


async def test_exact_identifiers_are_found_by_bm25_even_when_meaning_misses(team, client_for):
    owner, _, _ = team
    o = client_for(owner)
    await _set_openai_key(o)
    await o.post("/api/memory", json={"content": "INV-2024-118 from Northline was disputed; hold payment."})
    await o.post("/api/memory", json={"content": "Courier pickups happen every Tuesday."})
    found = (await o.get("/api/memory", params={"q": "INV-2024-118"})).json()["memories"]
    assert found and found[0]["content"].startswith("INV-2024-118")
    gstin = await o.post("/api/memory", json={"content": "Kumar Boxes GSTIN 27AAPFU0939F1ZV.", "kind": "contact"})
    assert gstin.status_code == 200
    assert (await o.get("/api/memory", params={"q": "27AAPFU0939F1ZV"})).json()["memories"][0]["kind"] == "contact"


async def test_index_follows_replace_delete_undo_and_leaving(team, client_for, qdrant):
    owner, viewer, outsider = team
    o, v, x = client_for(owner), client_for(viewer), client_for(outsider)
    first = (await o.post("/api/memory", json={"content": "Freight goes with BlueDart.", "topic": "freight"})).json()["memory"]
    second = (await o.post("/api/memory", json={"content": "Freight goes with Northline.", "topic": "freight"})).json()["memory"]

    def point_ids():
        points, _ = qdrant.scroll(memory_index.collection_name(), limit=100)
        return {str(p.id) for p in points}

    assert second["id"] in point_ids() and first["id"] not in point_ids()  # replaced version leaves the index
    await o.post(f"/api/memory/{second['id']}/undo")
    assert first["id"] in point_ids() and second["id"] not in point_ids()
    await o.delete(f"/api/memory/{first['id']}")
    assert first["id"] not in point_ids()

    # Search is scoped: the outsider's organization and others' personal memories never come back.
    await o.post("/api/memory", json={"content": "Owner prefers freight quotes in the morning.", "kind": "preference"})
    await o.post("/api/memory", json={"content": "We switched freight partners last month."})
    assert {m["scope"] for m in (await v.get("/api/memory", params={"q": "freight"})).json()["memories"]} == {"shared"}
    assert (await x.get("/api/memory", params={"q": "freight"})).json()["memories"] == []

    mine = (await v.post("/api/memory", json={"content": "Viewer handles freight calls.", "scope": "personal"})).json()["memory"]
    from app.db.base import session_scope
    from app.services import membership_service

    async with session_scope() as session:
        await membership_service.leave_organization(session, viewer)
    assert mine["id"] not in point_ids()


async def test_search_degrades_to_nothing_when_qdrant_is_down(team, client_for, monkeypatch):
    from app.services import qdrant_service

    owner, _, _ = team
    o = client_for(owner)

    def broken():
        raise RuntimeError("qdrant unavailable")

    monkeypatch.setattr(qdrant_service, "get_qdrant_client", broken)
    memory_index.reset_collection_cache()
    saved = await o.post("/api/memory", json={"content": "Rent is due on the 5th."})
    assert saved.status_code == 200  # Postgres still records it; the index can be rebuilt later
    assert (await o.get("/api/memory", params={"q": "rent"})).json()["memories"] == []
    assert len((await o.get("/api/memory")).json()["memories"]) == 1
