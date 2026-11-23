"""Which tools a run may use. Team bots set a policy; the web app runs without one.

The policy is a list of allowed tool names in the agent state (`tool_policy`). Every place that
hands tools to a model, or executes them, filters through `restrict`, so a tool that isn't
allowed is never offered to the model and can't run even if the model asks for it by name.
"""
from __future__ import annotations

from typing import Iterable

from app.agents.state import AgentState

# Groups an admin switches on for a team bot (Bots > Settings > Tools).
TOOL_GROUPS: dict[str, tuple[str, ...]] = {
    "documents": ("rag_retrieve", "list_documents"),
    "memory": ("remember", "forget_memory", "recall_memory"),
    "calendar_read": ("calendar_now", "calendar_list_events", "calendar_find_free_slots"),
    "calendar_write": ("calendar_create_event", "calendar_update_event", "calendar_delete_event"),
    "sheets_read": ("sheets_list_tabs", "sheets_read_range", "sheets_get_headers", "sheets_get_metadata"),
    "sheets_write": (
        "sheets_append_values", "sheets_update_values", "sheets_clear_values", "sheets_batch_update",
        "sheets_create_tab", "sheets_rename_tab", "sheets_delete_tab", "sheets_resize_grid",
        "sheets_insert_dimension", "sheets_delete_dimension",
    ),
}
GROUP_LABELS: dict[str, str] = {
    "documents": "Answer from uploaded documents",
    "memory": "Use and save long-term memory",
    "calendar_read": "Read calendar and find free time",
    "calendar_write": "Create, move and cancel meetings (asks to approve first)",
    "sheets_read": "Read Google Sheets",
    "sheets_write": "Change Google Sheets",
}
DEFAULT_TEAM_GROUPS = ("documents", "memory", "calendar_read", "calendar_write", "sheets_read")

# Plumbing every run needs: routing, asking a question, finding tools (results are filtered too).
ALWAYS_ALLOWED = frozenset({"request_clarification", "delegate_to_planner", "search_available_tools"})


def tool_names_for(groups: Iterable[str]) -> list[str]:
    names: list[str] = []
    for group in groups:
        names.extend(TOOL_GROUPS.get(group, ()))
    return sorted(set(names))


def is_allowed(state: AgentState, tool_name: str) -> bool:
    policy = state.get("tool_policy")
    return policy is None or tool_name in ALWAYS_ALLOWED or tool_name in policy


def restrict(state: AgentState, tools: list) -> list:
    if state.get("tool_policy") is None:
        return tools
    return [t for t in tools if is_allowed(state, getattr(t, "name", ""))]


def restrict_ids(state: AgentState, tool_ids: Iterable[str]) -> list[str]:
    return [tool_id for tool_id in tool_ids if is_allowed(state, tool_id)]
