import logging
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from app.agents.state import AgentState
from app.agents.tooling import get_chat_local_tools
from app.services.llm_service import get_llm

logger = logging.getLogger(__name__)


class ChatDecision(BaseModel):
    action: str = Field(description="Either 'answer' or 'plan'.")
    answer: str = Field(default="", description="Direct user-facing answer when action is 'answer'.")
    execution_brief: str = Field(
        default="",
        description="Concise handoff for the planner when action is 'plan'. Include task, context, constraints, and relevant chat file context.",
    )


CHAT_SYSTEM = """
You are BizAssist, the main chat agent for a business operations assistant.

You are not only for greetings. Solve the user's request directly whenever it can be handled from:
- the ongoing conversation
- uploaded chat files
- simple reasoning grounded in chat-local context

You have chat-local tools for:
- request_clarification
- chat attachment inspection

Use structured output:
- action='answer' when you can solve it directly
- action='plan' when broader planning or external execution is needed

Rules:
1. Use tools when chat-local file access or clarification is needed.
2. Answer directly when chat-local context is sufficient.
3. Route to planning when spreadsheet actions, broader orchestration, or external-system execution is needed.
4. Do not invent facts not grounded in the conversation or tool results.
"""


FINAL_RESPONSE_SYSTEM = """
You are BizAssist, preparing the final answer after execution is complete.

Use the execution findings already present in the conversation.
Provide a concise, grounded final answer for the user.
If the execution surfaced uncertainty or missing data, say so clearly.
"""


def _clean_message_history(messages: list) -> list:
    clean_msgs = []
    for i, msg in enumerate(messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            valid_tool_calls = []
            for tc in msg.tool_calls:
                tc_id = tc.get("id")
                found = False
                for j in range(i + 1, len(messages)):
                    next_msg = messages[j]
                    if isinstance(next_msg, ToolMessage) and next_msg.tool_call_id == tc_id:
                        found = True
                        break
                    if not isinstance(next_msg, ToolMessage):
                        break

                if found:
                    valid_tool_calls.append(tc)

            if not valid_tool_calls:
                clean_msgs.append(AIMessage(content=msg.content))
            else:
                msg.tool_calls = valid_tool_calls
                clean_msgs.append(msg)
        else:
            clean_msgs.append(msg)
    return clean_msgs



def _extract_structured_payload(result: Any) -> tuple[BaseMessage | None, ChatDecision | None]:
    if isinstance(result, dict):
        raw = result.get("raw")
        parsed = result.get("parsed")
        return raw if isinstance(raw, BaseMessage) else None, parsed if isinstance(parsed, ChatDecision) else None
    return None, result if isinstance(result, ChatDecision) else None


async def chat_node(state: AgentState) -> dict:
    messages = _clean_message_history(state.get("messages") or [])

    if state.get("execution_completed"):
        llm = await get_llm(
            user_id=state["user_id"],
            purpose="primary",
            temperature=0.2,
            streaming=True,
        )
        response = await llm.ainvoke([SystemMessage(content=FINAL_RESPONSE_SYSTEM)] + messages)
        return {
            "messages": [response],
            "chat_route": "answer",
            "execution_brief": "",
            "execution_plan": "",
            "execution_steps": [],
            "execution_query": "",
            "execution_completed": False,
            "active_agent": "",
            "active_tool_ids": [],
        }
    llm = await get_llm(
        user_id=state["user_id"],
        purpose="primary",
        temperature=0.1,
        streaming=False,
    )
    unified_model = llm.with_structured_output(
        schema=ChatDecision,
        method="json_schema",
        include_raw=True,
        strict=True,
        tools=get_chat_local_tools(state),
    )
    result = await unified_model.ainvoke([SystemMessage(content=CHAT_SYSTEM)] + messages)
    raw_response, parsed = _extract_structured_payload(result)

    if raw_response and getattr(raw_response, "tool_calls", None):
        return {
            "messages": [raw_response],
            "chat_route": "answer",
            "active_agent": "chat",
        }

    if parsed:
        action = (parsed.action or "answer").strip().lower()
        if action == "plan":
            execution_brief = (parsed.execution_brief or "").strip()
            if not execution_brief:
                execution_brief = "Review the latest user request and plan the required operational steps."
            return {
                "chat_route": "planner",
                "execution_brief": execution_brief,
                "execution_plan": "",
                "execution_steps": [],
                "execution_query": "",
                "execution_completed": False,
                "active_agent": "planner",
                "active_tool_ids": [],
            }

        answer = (parsed.answer or "").strip() or "Sorry something went wrong, can you please try again"
        return {
            "messages": [AIMessage(content=answer)],
            "chat_route": "answer",
            "execution_brief": "",
            "execution_plan": "",
            "execution_steps": [],
            "execution_query": "",
            "execution_completed": False,
            "active_agent": "",
            "active_tool_ids": [],
        }

    fallback_text = ""
    if raw_response is not None:
        fallback_text = str(getattr(raw_response, "content", "") or "").strip()
    fallback_text = fallback_text or "I need a bit more context to help with that."
    return {
        "messages": [AIMessage(content=fallback_text)],
        "chat_route": "answer",
        "active_agent": "",
    }
