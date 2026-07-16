import logging

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage

from app.agents.state import AgentState
from app.agents.tooling import build_tools_for_agent
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

    tools = await build_tools_for_agent(state)
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
            SystemMessage(content=system_content),
            *scratchpad,
        ]
    )

    return {
        "messages": [response],
        "execution_completed": not bool(getattr(response, "tool_calls", None)),
        "active_agent": "executor",
        "progress_event": {
            "stage": "execution",
            "message": "Working through the execution steps.",
            "steps": (state.get("execution_steps") or [])[:5],
        },
    }
