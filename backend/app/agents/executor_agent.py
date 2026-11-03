import logging

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage, HumanMessage

from app.agents.business_context import with_business_context
from app.agents.state import AgentState
from app.agents.tooling import build_tools_for_agent, select_initial_tool_ids
from app.services.llm_service import get_llm

logger = logging.getLogger(__name__)


EXECUTOR_SYSTEM = """
You are the BizAssist executor.

Your job is to execute the planner's instructions using tools when needed.

Rules:
1. Follow the execution brief and execution plan.
2. Use tools for document access, spreadsheet work, and retrieval.
3. If the loaded tools are not enough, call search_available_tools with a short semantic query.
4. If a critical detail is missing, call request_clarification.
5. Ground every claim in tool outputs or chat context.
6. When execution is complete, provide a short findings summary for the chat agent to turn into the final user-facing answer.
7. For calendar work, resolve relative dates from the [Now] line, or call calendar_now if there is none. Calendar create, update and
   delete tools ask the user to approve by themselves, so do not ask for confirmation separately. Report Meet links and
   event details only from tool results.
"""


def _executor_scratchpad(messages: list[BaseMessage]) -> list[BaseMessage]:
    scratchpad: list[BaseMessage] = []
    index = len(messages) - 1

    while index >= 0:
        message = messages[index]
        if isinstance(message, ToolMessage):
            scratchpad.append(message)
            index -= 1
            continue
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            scratchpad.append(message)
            index -= 1
            continue
        break

    scratchpad.reverse()
    return scratchpad


async def executor_node(state: AgentState) -> dict:
    llm = await get_llm(
        user_id=state["user_id"],
        purpose="primary",
        temperature=0.2,
        streaming=True,
    )

    # Search once and keep the result: the tool step and later rounds reuse it.
    active_tool_ids = list(state.get("active_tool_ids") or await select_initial_tool_ids(state))
    tools = await build_tools_for_agent({**state, "active_tool_ids": active_tool_ids})
    llm_with_tools = llm.bind_tools(tools)
    scratchpad = _executor_scratchpad(state.get("messages") or [])

    system_content = (
        EXECUTOR_SYSTEM
        + f"\n\n[Execution Brief]\n{state.get('execution_brief', '')}"
        + f"\n\n[Execution Plan]\n{state.get('execution_plan', '')}"
        + f"\n\n[Execution Steps]\n{chr(10).join(f'- {step}' for step in (state.get('execution_steps') or []))}"
        + f"\n\n[Execution Query]\n{state.get('execution_query', '')}"
    )

    response = await llm_with_tools.ainvoke(
        [
            SystemMessage(content=with_business_context(system_content, state)),
            # Non-OpenAI providers require a user turn before any assistant or tool messages.
            HumanMessage(content="Carry out the plan."),
            *scratchpad,
        ]
    )

    return {
        "messages": [response],
        "execution_completed": not bool(getattr(response, "tool_calls", None)),
        "active_agent": "executor",
        "active_tool_ids": active_tool_ids,
        "progress_event": {
            "stage": "execution",
            "message": "Working through the execution steps.",
            "steps": (state.get("execution_steps") or [])[:5],
        },
    }
