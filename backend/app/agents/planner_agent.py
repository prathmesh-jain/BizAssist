import logging
from difflib import SequenceMatcher
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.state import AgentState
from app.agents.tooling import get_planner_tools
from app.config import get_settings
from app.services.llm_service import get_llm

logger = logging.getLogger(__name__)
settings = get_settings()


class PlannerOutput(BaseModel):
    execution_query: str = Field(description="Short semantic query used to retrieve the initial executor tools.")
    execution_plan: str = Field(description="Compact high-level execution plan summary.")
    execution_steps: list[str] = Field(description="Ordered execution steps for the executor.")


PLANNER_SYSTEM = """
You are the BizAssist planner.

You receive a short execution brief from the chat agent.
You do have planning-time tool access for clarification, chat attachment inspection, and capability discovery.

Your job:
1. Understand the execution brief.
2. Use tools if needed to clarify the task, inspect uploaded files, or discover relevant capabilities.
3. Return a structured plan with:
   - execution_query
   - execution_plan
   - execution_steps

Rules:
1. Do not answer the user directly.
2. Use request_clarification if a critical detail is missing.
3. Use search_available_tools if executor capabilities need to be explored.
4. Keep the plan concise, operational, and grounded.
"""


def _recent_planner_clarifications(state: AgentState) -> str:
    recent_human_messages: list[str] = []
    for message in reversed(state.get("messages") or []):
        if getattr(message, "type", "") != "human":
            continue
        text = str(getattr(message, "content", "") or "").strip()
        if not text:
            continue
        recent_human_messages.append(text)
        if len(recent_human_messages) >= 3:
            break

    if not recent_human_messages:
        return ""
    return "\n".join(f"- {text}" for text in reversed(recent_human_messages))


def _extract_structured_payload(result: Any) -> tuple[BaseMessage | None, PlannerOutput | None]:
    if isinstance(result, dict):
        raw = result.get("raw")
        parsed = result.get("parsed")
        return raw if isinstance(raw, BaseMessage) else None, parsed if isinstance(parsed, PlannerOutput) else None
    return None, result if isinstance(result, PlannerOutput) else None


def _normalize_step(step: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in step).split())


def _are_similar_steps(left: str, right: str) -> bool:
    left_norm = _normalize_step(left)
    right_norm = _normalize_step(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    return SequenceMatcher(None, left_norm, right_norm).ratio() >= 0.9


def _dedupe_adjacent_steps(steps: list[str]) -> list[str]:
    deduped: list[str] = []
    for raw_step in steps:
        step = str(raw_step or "").strip()
        if not step:
            continue
        if deduped and _are_similar_steps(deduped[-1], step):
            continue
        deduped.append(step)
    return deduped


def _fallback_plan(execution_brief: str, iterations: int) -> dict:
    fallback_step = execution_brief or "Review the latest user request and execute the most likely next action."
    return {
        "execution_query": execution_brief,
        "execution_plan": execution_brief,
        "execution_steps": [fallback_step],
        "execution_completed": False,
        "planner_iterations": 0,
        "active_agent": "executor",
        "active_tool_ids": [],
        "progress_event": {
            "stage": "plan_ready",
            "message": f"Planner stopped after {iterations} iterations. Proceeding with a compact fallback plan.",
            "steps": [fallback_step],
        },
    }


async def planner_node(state: AgentState) -> dict:
    execution_brief = str(state.get("execution_brief") or "").strip()
    if not execution_brief:
        execution_brief = "Review the latest user request and create an execution plan."

    planner_iterations = int(state.get("planner_iterations") or 0) + 1
    if planner_iterations > int(settings.planner_max_iterations or 4):
        logger.warning(
            "Planner iteration limit reached for user %s after %s iterations",
            state.get("user_id"),
            planner_iterations - 1,
        )
        return _fallback_plan(execution_brief, planner_iterations - 1)

    llm = await get_llm(
        user_id=state["user_id"],
        purpose="fast",
        temperature=0,
        streaming=False,
    )
    unified_model = llm.with_structured_output(
        schema=PlannerOutput,
        method="json_schema",
        include_raw=True,
        strict=True,
        tools=get_planner_tools(state),
    )

    planner_input = f"Execution brief:\n{execution_brief}"
    clarifications = _recent_planner_clarifications(state)
    if clarifications:
        planner_input += f"\n\nRecent user clarifications:\n{clarifications}"

    result = await unified_model.ainvoke(
        [
            SystemMessage(content=PLANNER_SYSTEM),
            HumanMessage(content=planner_input),
        ]
    )
    raw_response, parsed = _extract_structured_payload(result)

    if raw_response and getattr(raw_response, "tool_calls", None):
        return {
            "messages": [raw_response],
            "planner_iterations": planner_iterations,
            "active_agent": "planner",
            "progress_event": {
                "stage": "planning",
                "message": "Planning the work and gathering any missing details.",
            },
        }

    if parsed:
        execution_query = (parsed.execution_query or "").strip() or execution_brief
        execution_plan = (parsed.execution_plan or "").strip() or execution_brief
        execution_steps = _dedupe_adjacent_steps(
            [step.strip() for step in (parsed.execution_steps or []) if str(step).strip()]
        )
        if not execution_steps:
            execution_steps = [execution_plan]

        return {
            "execution_query": execution_query,
            "execution_plan": execution_plan,
            "execution_steps": execution_steps,
            "execution_completed": False,
            "planner_iterations": 0,
            "active_agent": "executor",
            "active_tool_ids": [],
            "progress_event": {
                "stage": "plan_ready",
                "message": "Plan ready. Executing the task now.",
                "steps": execution_steps[:5],
            },
        }

    return _fallback_plan(execution_brief, planner_iterations)
