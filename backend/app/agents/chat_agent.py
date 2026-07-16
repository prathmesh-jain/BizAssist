from langchain_core.messages import AIMessage, BaseMessage, RemoveMessage, SystemMessage, ToolMessage

from app.agents.state import AgentState
from app.agents.tooling import get_chat_local_tools
from app.services.llm_service import get_llm


CHAT_SYSTEM = """
You are BizAssist, the main chat agent for a business operations assistant.

You are not only for greetings. Solve the user's request directly whenever it can be handled from:
- the ongoing conversation
- uploaded chat files
- simple reasoning grounded in chat-local context

You have chat-local tools for:
- request_clarification
- chat attachment inspection
- list_documents
- rag_retrieve

Chat attachments are files uploaded in this conversation.

The list_documents tool returns documents from both:
- chat_upload
- indexed_document

If the user names a file, you may pass that filename to list_documents to get the top fuzzy matches.

If a result is from chat_upload, you may inspect it with chat attachment tools.

If a result is from indexed_document, you may use rag_retrieve for single-step factual lookup or direct question answering.
Delegate_to_planner only when the indexed-document task is broader, multi-step, comparative, or requires execution after analysis.

Google Sheets are NOT chat attachments.

If the user refers to:
- Google Sheets
- spreadsheets stored externally
- "my sheet"
- "my spreadsheet"
- workbook
- tabs
- spreadsheet operations

Then delegate_to_planner.

Rules:
1. Answer directly when chat-local context is sufficient.
2. Use tools when chat-local file access or clarification is needed.
3. Use rag_retrieve for direct knowledge-base lookup questions that can be answered in one pass.
4. If the task needs broader planning, orchestration, spreadsheet work, or external-system execution, call delegate_to_planner with a concise execution brief.
5. Do not invent facts not grounded in the conversation or tool results.
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


def _recent_tool_exchange_removals(messages: list[BaseMessage]) -> list[RemoveMessage]:
    removals: list[RemoveMessage] = []
    index = len(messages) - 1

    while index >= 0 and isinstance(messages[index], ToolMessage):
        message_id = getattr(messages[index], "id", None)
        if message_id:
            removals.append(RemoveMessage(id=message_id))
        index -= 1

    if removals and index >= 0:
        candidate = messages[index]
        if isinstance(candidate, AIMessage) and getattr(candidate, "tool_calls", None):
            message_id = getattr(candidate, "id", None)
            if message_id:
                removals.append(RemoveMessage(id=message_id))

    return removals


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
        replacement_messages = [response]
        if messages:
            last_message = messages[-1]
            if isinstance(last_message, AIMessage) and not getattr(last_message, "tool_calls", None):
                last_id = getattr(last_message, "id", None)
                if last_id:
                    replacement_messages = [RemoveMessage(id=last_id), response]
        return {
            "messages": replacement_messages,
            "chat_route": "answer",
            "execution_brief": "",
            "execution_plan": "",
            "execution_steps": [],
            "execution_query": "",
            "execution_completed": False,
            "planner_iterations": 0,
            "active_agent": "",
            "active_tool_ids": [],
        }

    llm = await get_llm(
        user_id=state["user_id"],
        purpose="primary",
        temperature=0.1,
        streaming=True,
    )
    response = await llm.bind_tools(get_chat_local_tools(state)).ainvoke(
        [SystemMessage(content=CHAT_SYSTEM)] + messages
    )

    result = {
        "messages": [response],
        "chat_route": "answer",
        "active_agent": "chat" if getattr(response, "tool_calls", None) else "",
    }

    if not getattr(response, "tool_calls", None):
        replacement_messages = _recent_tool_exchange_removals(messages)
        if replacement_messages:
            replacement_messages.append(response)
            result["messages"] = replacement_messages
        result.update(
            {
                "execution_brief": "",
                "execution_plan": "",
                "execution_steps": [],
                "execution_query": "",
                "execution_completed": False,
                "planner_iterations": 0,
                "active_tool_ids": [],
            }
        )

    return result
