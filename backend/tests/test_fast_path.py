"""Fast path: tools chosen before chat's first call, local time in the prompt, no repeat searches."""
import pytest
from langchain_core.messages import HumanMessage

from app.agents.business_context import with_business_context
from app.agents.tooling import CHAT_TOOL_LIMIT, get_chat_local_tools, select_chat_tool_ids
from app.services.llm_service import _GPT5_MINIMAL_EFFORT

pytestmark = pytest.mark.no_db


def select(*messages, timezone="Asia/Kolkata"):
    return select_chat_tool_ids({"messages": [HumanMessage(content=m) for m in messages], "user_timezone": timezone})


@pytest.mark.parametrize("message, expected", [
    ("What do I have planned this weekend?", "calendar_list_events"),
    ("What meetings do I have tomorrow?", "calendar_list_events"),
    ("Find a free hour for me on Friday afternoon", "calendar_find_free_slots"),
    ("Schedule a Google Meet with rahul@acme.com tomorrow at 3 PM", "calendar_create_event"),
    ("Book a call with priya@acme.com next Monday at 11 AM", "calendar_create_event"),
    ("Move my 4 PM meeting to Friday", "calendar_update_event"),
    ("Cancel tomorrow's standup", "calendar_delete_event"),
    ("read the transactions from my spreadsheet", "sheets_read_range"),
])
def test_requests_select_the_right_tool_first(message, expected):
    selected = select(message)
    assert selected[0] == expected and len(selected) <= CHAT_TOOL_LIMIT


@pytest.mark.parametrize("message", [
    "Say hello in five words", "What is the capital of France?", "Summarize the uploaded invoice",
    "How can I increase revenue this year?", "thanks a lot",
])
def test_unrelated_messages_add_no_tools(message):
    assert select(message) == []


def test_spreadsheet_writes_stay_with_the_planner():
    assert not [t for t in select("append this row to my spreadsheet and update the sheet") if "read" not in t and t.startswith("sheets_") and t not in (
        "sheets_list_tabs", "sheets_get_headers", "sheets_get_metadata",
    )]


def test_follow_up_keeps_previous_context_but_a_new_topic_wins():
    assert select("What meetings do I have tomorrow?", "and on Friday?")[0] == "calendar_list_events"
    assert select("What meetings do I have tomorrow?", "read my spreadsheet")[0].startswith("sheets_")


def test_calendar_now_is_only_offered_when_local_time_is_unknown():
    assert "calendar_now" not in select("what time and date is it now in my timezone")
    assert "calendar_now" in select("what time and date is it now in my timezone", timezone="")


def test_chat_can_execute_the_selected_tools_and_only_those():
    base = {"user_id": "u", "organization_id": "o", "chat_id": "c", "messages": []}
    names = {t.name for t in get_chat_local_tools({**base, "chat_tool_ids": ["calendar_list_events"]})}
    assert "calendar_list_events" in names and "delegate_to_planner" in names
    assert "calendar_delete_event" not in names
    assert "calendar_list_events" not in {t.name for t in get_chat_local_tools(base)}


def test_prompt_has_local_time_when_the_timezone_is_known():
    local = with_business_context("S", {"user_timezone": "Asia/Kolkata"})
    assert "[Now] " in local and "Asia/Kolkata" in local
    for state in ({}, {"user_timezone": "Not/AZone"}):
        assert "[Today] " in with_business_context("S", state)


@pytest.mark.parametrize("model, minimal", [
    ("gpt-5-nano", True), ("gpt-5-mini", True), ("gpt-5", True), ("gpt-5-nano-2025-08-07", True),
    ("gpt-5.4-nano", False), ("gpt-5-pro", False), ("gpt-4.1-mini", False), ("gpt-6-luna", False),
])
def test_minimal_reasoning_only_for_models_that_accept_it(model, minimal):
    assert bool(_GPT5_MINIMAL_EFFORT.match(model)) is minimal


async def test_executor_searches_once_and_stores_the_result(monkeypatch):
    from langchain_core.messages import AIMessage

    from app.agents import executor_agent

    searches = []

    async def fake_select(state):
        searches.append(state)
        return ["calendar_list_events"]

    class FakeLLM:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            return AIMessage(content="done")

    async def fake_get_llm(**kwargs):
        return FakeLLM()

    monkeypatch.setattr(executor_agent, "select_initial_tool_ids", fake_select)
    monkeypatch.setattr(executor_agent, "get_llm", fake_get_llm)
    state = {"user_id": "u", "organization_id": "o", "chat_id": "c", "messages": []}
    result = await executor_agent.executor_node(state)
    assert result["active_tool_ids"] == ["calendar_list_events"] and len(searches) == 1
    await executor_agent.executor_node({**state, "active_tool_ids": result["active_tool_ids"]})
    assert len(searches) == 1


def test_new_messages_are_found_by_id_even_when_the_list_shrinks():
    from langchain_core.messages import AIMessage, ToolMessage

    from app.services.chat_service import new_messages_since

    human = HumanMessage(content="book it", id="h1")
    call = AIMessage(content="", id="a1")
    tool = ToolMessage(content="{}", tool_call_id="t", id="t1")
    answer = AIMessage(content="Booked.", id="a2")
    # After approval chat drops its tool exchange: same length as before, but one new message.
    assert new_messages_since([human, call], [human, answer]) == [answer]
    assert new_messages_since([human, call, tool], [human, answer]) == [answer]
    assert new_messages_since([human], [human]) == []
